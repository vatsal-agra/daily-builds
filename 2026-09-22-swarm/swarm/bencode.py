"""Bencode: the encoding BitTorrent uses for .torrent files and the tracker
wire protocol. Four types only: integers, byte strings, lists, dicts.

    i<base-10 digits>e      integer, no leading zeros, "i0e" is the only
                             representation of zero, "i-0e" is invalid
    <len>:<bytes>            byte string, length-prefixed, no separator
                             ambiguity possible since length is explicit
    l<bencoded items>e       list
    d<bencoded key/value>e   dict; keys must be byte strings and, per spec,
                             must appear in sorted order in valid bencode

Decoding is strict: malformed input raises BencodeError rather than
guessing, since this dict is later re-encoded to derive a torrent's
info_hash and even one accepted-but-wrong byte would silently produce a
different swarm identity than a spec-compliant peer would compute.
"""
from __future__ import annotations


class BencodeError(ValueError):
    pass


def encode(obj) -> bytes:
    if isinstance(obj, bool):
        # bool is an int subclass in Python; bencode has no boolean type and
        # BitTorrent never encodes one, so refuse rather than silently
        # emitting "i1e"/"i0e" for something that isn't actually an integer.
        raise BencodeError("bencode has no boolean type")
    if isinstance(obj, int):
        return b"i%de" % obj
    if isinstance(obj, (bytes, bytearray)):
        return b"%d:%s" % (len(obj), bytes(obj))
    if isinstance(obj, str):
        data = obj.encode("utf-8")
        return b"%d:%s" % (len(data), data)
    if isinstance(obj, (list, tuple)):
        return b"l" + b"".join(encode(item) for item in obj) + b"e"
    if isinstance(obj, dict):
        # Canonical bencode requires dict keys sorted by raw byte value.
        items = []
        for key in obj:
            if not isinstance(key, (bytes, bytearray, str)):
                raise BencodeError(f"dict keys must be strings/bytes, got {type(key)!r}")
        keys = sorted(obj.keys(), key=lambda k: k.encode("utf-8") if isinstance(k, str) else bytes(k))
        for key in keys:
            items.append(encode(key))
            items.append(encode(obj[key]))
        return b"d" + b"".join(items) + b"e"
    raise BencodeError(f"cannot bencode type {type(obj)!r}")


class _Decoder:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _peek(self) -> bytes:
        if self.pos >= len(self.data):
            raise BencodeError("unexpected end of input")
        return self.data[self.pos : self.pos + 1]

    def decode_value(self):
        marker = self._peek()
        if marker == b"i":
            return self._decode_int()
        if marker == b"l":
            return self._decode_list()
        if marker == b"d":
            return self._decode_dict()
        if marker.isdigit():
            return self._decode_bytes()
        raise BencodeError(f"invalid token {marker!r} at offset {self.pos}")

    def _read_until(self, delim: bytes) -> bytes:
        end = self.data.find(delim, self.pos)
        if end == -1:
            raise BencodeError(f"expected {delim!r} before end of input")
        chunk = self.data[self.pos : end]
        self.pos = end + 1
        return chunk

    def _decode_int(self) -> int:
        assert self.data[self.pos : self.pos + 1] == b"i"
        self.pos += 1
        raw = self._read_until(b"e")
        if raw == b"" or raw == b"-":
            raise BencodeError("empty integer")
        try:
            text = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise BencodeError(f"non-ASCII byte in integer literal: {raw!r}") from exc
        if text == "0":
            return 0
        if text.startswith("-0") or (text.startswith("0") and text != "0"):
            raise BencodeError(f"invalid integer with leading zero: {raw!r}")
        if text.startswith("-") and text[1:].startswith("0"):
            raise BencodeError(f"invalid integer: {raw!r}")
        if not (text.lstrip("-")).isdigit():
            raise BencodeError(f"invalid integer literal: {raw!r}")
        return int(text)

    def _decode_bytes(self) -> bytes:
        raw_len = self._read_until(b":")
        if not raw_len.isdigit():
            raise BencodeError(f"invalid byte-string length: {raw_len!r}")
        length = int(raw_len)
        end = self.pos + length
        if end > len(self.data):
            raise BencodeError("byte string runs past end of input")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def _decode_list(self) -> list:
        assert self.data[self.pos : self.pos + 1] == b"l"
        self.pos += 1
        items = []
        while True:
            if self.pos >= len(self.data):
                raise BencodeError("unterminated list")
            if self.data[self.pos : self.pos + 1] == b"e":
                self.pos += 1
                return items
            items.append(self.decode_value())

    def _decode_dict(self) -> dict:
        assert self.data[self.pos : self.pos + 1] == b"d"
        self.pos += 1
        result = {}
        prev_key = None
        while True:
            if self.pos >= len(self.data):
                raise BencodeError("unterminated dict")
            if self.data[self.pos : self.pos + 1] == b"e":
                self.pos += 1
                return result
            key_marker = self._peek()
            if not key_marker.isdigit():
                raise BencodeError("dict keys must be byte strings")
            key = self._decode_bytes()
            if prev_key is not None and key <= prev_key:
                raise BencodeError(f"dict keys not in strict sorted order: {prev_key!r} >= {key!r}")
            prev_key = key
            result[key] = self.decode_value()


def decode(data: bytes):
    """Decode a single bencoded value. Raises BencodeError on trailing junk."""
    if not isinstance(data, (bytes, bytearray)):
        raise BencodeError("bencode input must be bytes")
    decoder = _Decoder(bytes(data))
    value = decoder.decode_value()
    if decoder.pos != len(decoder.data):
        raise BencodeError(f"trailing data after top-level value (byte {decoder.pos} of {len(decoder.data)})")
    return value


def decode_prefix(data: bytes, start: int = 0):
    """Decode one bencoded value starting at `start`, return (value, next_pos).

    Used by the tracker/peer wire code to pull one bencoded value out of a
    larger buffer without requiring the whole buffer to be exactly one value.
    """
    decoder = _Decoder(bytes(data))
    decoder.pos = start
    value = decoder.decode_value()
    return value, decoder.pos
