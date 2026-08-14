"""DNS domain names: wire-format encode/decode (RFC 1035 section 3.1 and 4.1.4).

A DNS name is a sequence of length-prefixed labels terminated by a zero-length
root label. The wire format also supports *compression*: instead of repeating
a name (or a suffix of it) that already appeared earlier in the message, a
2-byte pointer (top two bits set, 14-bit offset) can point back to that
earlier occurrence. Real resolvers rely on both directions of this working
correctly -- decoding pointers, and *writing* pointers to keep responses
small enough to fit in a single UDP datagram.
"""

from __future__ import annotations

MAX_LABEL_LEN = 63
MAX_NAME_LEN = 255
POINTER_MASK = 0xC0
MAX_POINTER_OFFSET = 0x3FFF


class DNSFormatError(Exception):
    """Raised on malformed wire-format data."""


class Name:
    """An immutable, case-insensitively-compared DNS name.

    Internally stored as a tuple of raw label bytes (case preserved, as DNS
    requires for transmission) plus a lowercased tuple used for hashing and
    equality, since DNS name comparison is case-insensitive (RFC 1035 3.1 /
    RFC 4343).
    """

    __slots__ = ("labels", "_lower")

    def __init__(self, labels):
        labels = tuple(labels)
        for label in labels:
            if not isinstance(label, (bytes, bytearray)):
                raise TypeError("labels must be bytes")
            if len(label) == 0:
                raise DNSFormatError("empty label is only valid as the root")
            if len(label) > MAX_LABEL_LEN:
                raise DNSFormatError(f"label too long ({len(label)} bytes): {label!r}")
        wire_len = sum(len(l) + 1 for l in labels) + 1
        if wire_len > MAX_NAME_LEN:
            raise DNSFormatError(f"name too long ({wire_len} wire bytes)")
        self.labels = labels
        self._lower = tuple(l.lower() for l in labels)

    @classmethod
    def from_text(cls, text: str) -> "Name":
        text = text.strip()
        if text in ("", "."):
            return cls(())
        text = text.rstrip(".")
        parts = []
        for label in text.split("."):
            if label == "":
                raise DNSFormatError(f"empty label in name {text!r}")
            parts.append(label.encode("ascii"))
        return cls(parts)

    def to_text(self) -> str:
        if not self.labels:
            return "."
        return ".".join(l.decode("ascii") for l in self.labels) + "."

    def is_root(self) -> bool:
        return len(self.labels) == 0

    def is_subdomain_of(self, other: "Name") -> bool:
        """True if self is other, or a descendant of other."""
        if len(other._lower) == 0:
            return True
        if len(self._lower) < len(other._lower):
            return False
        return self._lower[len(self._lower) - len(other._lower):] == other._lower

    def relativize(self, origin: "Name") -> "Name":
        """Return the labels of self with origin's suffix stripped."""
        if not self.is_subdomain_of(origin):
            raise ValueError(f"{self.to_text()} is not a subdomain of {origin.to_text()}")
        n = len(self.labels) - len(origin.labels)
        return Name(self.labels[:n])

    def parent(self) -> "Name":
        if not self.labels:
            raise ValueError("root has no parent")
        return Name(self.labels[1:])

    def __truediv__(self, prefix: "Name") -> "Name":
        """prefix / self -- prepend prefix's labels onto self (origin composition)."""
        return Name(prefix.labels + self.labels)

    def __eq__(self, other):
        return isinstance(other, Name) and self._lower == other._lower

    def __hash__(self):
        return hash(self._lower)

    def __lt__(self, other):
        return self._lower < other._lower

    def __repr__(self):
        return f"Name({self.to_text()!r})"

    def __str__(self):
        return self.to_text()


ROOT = Name(())


def encode_name(name: Name, buf: bytearray, compression: dict | None) -> None:
    """Append the wire-format encoding of `name` to `buf`.

    `compression` maps a lowercased label-suffix tuple -> the offset in the
    overall message where that suffix already occurs, so it can be shared
    across every name written into a message. Pass ``None`` to disable
    compression entirely (produces a valid, larger, encoding).
    """
    labels = name.labels
    while True:
        suffix_key = tuple(l.lower() for l in labels)
        if compression is not None and suffix_key in compression:
            pointer = compression[suffix_key]
            buf.append(POINTER_MASK | (pointer >> 8))
            buf.append(pointer & 0xFF)
            return
        if compression is not None and len(buf) <= MAX_POINTER_OFFSET and labels:
            compression[suffix_key] = len(buf)
        if not labels:
            buf.append(0)
            return
        label = labels[0]
        buf.append(len(label))
        buf.extend(label)
        labels = labels[1:]


def decode_name(buf: bytes, offset: int, max_pointer_hops: int = 128) -> tuple[Name, int]:
    """Decode a wire-format name starting at `offset`.

    Returns (Name, offset_after_the_name_in_the_original_stream). Following a
    compression pointer does not advance the "official" returned offset past
    the 2-byte pointer itself, exactly like a real resolver: the *logical*
    name can be arbitrarily long, but that costs only 2 bytes on the wire at
    the point of reference.
    """
    labels = []
    cur = offset
    end_offset = None
    hops = 0
    while True:
        if cur >= len(buf):
            raise DNSFormatError("name extends past end of message")
        length = buf[cur]
        if length == 0:
            cur += 1
            if end_offset is None:
                end_offset = cur
            break
        elif (length & POINTER_MASK) == POINTER_MASK:
            if cur + 1 >= len(buf):
                raise DNSFormatError("truncated compression pointer")
            pointer = ((length & 0x3F) << 8) | buf[cur + 1]
            if end_offset is None:
                end_offset = cur + 2
            if pointer >= cur:
                # Pointers may only reference *earlier* data -- this is what
                # guarantees decoding terminates and can't be turned into an
                # infinite loop by a hostile/corrupt packet.
                raise DNSFormatError("compression pointer does not point backward")
            hops += 1
            if hops > max_pointer_hops:
                raise DNSFormatError("too many compression pointer hops (possible loop)")
            cur = pointer
        elif length & POINTER_MASK:
            raise DNSFormatError("reserved label-length bits set")
        else:
            cur += 1
            if cur + length > len(buf):
                raise DNSFormatError("label extends past end of message")
            labels.append(bytes(buf[cur:cur + length]))
            cur += length
    return Name(labels), end_offset
