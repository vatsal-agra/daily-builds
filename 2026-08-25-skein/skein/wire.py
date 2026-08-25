"""The real BitTorrent peer wire protocol: handshake + framed messages.

Handshake (fixed 68 bytes, sent by both sides immediately on connect):

    1 byte    pstrlen              = 19
    19 bytes  pstr                 = "BitTorrent protocol"
    8 bytes   reserved             = all zero (no extensions)
    20 bytes  info_hash            identifies the torrent/swarm
    20 bytes  peer_id              identifies the sending peer

After the handshake, every message is length-prefixed:

    4 bytes   length (big-endian, NOT including these 4 bytes)
    1 byte    message id           (absent iff length == 0: "keep-alive")
    ...       payload              (message-id specific)

Message ids implemented here match the real spec (BEP 3):
    0 choke            4 have          payload: <4-byte piece index>
    1 unchoke          5 bitfield      payload: <bitfield bytes>
    2 interested       6 request       payload: <index><begin><length>, 4B each
    3 not interested   7 piece         payload: <index><begin><block bytes>
                       8 cancel        payload: <index><begin><length>, 4B each
"""

from __future__ import annotations

import socket
import struct

PSTR = b"BitTorrent protocol"
HANDSHAKE_LEN = 49 + len(PSTR)  # 68

CHOKE = 0
UNCHOKE = 1
INTERESTED = 2
NOT_INTERESTED = 3
HAVE = 4
BITFIELD = 5
REQUEST = 6
PIECE = 7
CANCEL = 8

_NAMES = {
    CHOKE: "choke", UNCHOKE: "unchoke", INTERESTED: "interested",
    NOT_INTERESTED: "not_interested", HAVE: "have", BITFIELD: "bitfield",
    REQUEST: "request", PIECE: "piece", CANCEL: "cancel",
}


class WireError(ConnectionError):
    pass


class WireTimeout(WireError):
    """Raised by recv_message when no message arrives within `timeout`.

    Distinct from a real disconnect: callers that pass `timeout` (to poll
    periodically for other work, e.g. request scheduling) should treat
    this as "nothing to read right now," not "the connection is dead."
    """


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        try:
            chunk = sock.recv(remaining)
        except socket.timeout:
            if remaining == n:
                # Nothing at all arrived yet — a normal "no message right
                # now" poll timeout, safe for the caller to retry.
                raise WireTimeout(f"timed out waiting for the first byte of {n}") from None
            # We're mid-message: bailing out here would desync the stream
            # for whoever reads next, so this is a real protocol failure.
            raise WireError(f"stalled mid-message after {n - remaining}/{n} bytes") from None
        if not chunk:
            raise WireError(f"connection closed after {n - remaining}/{n} bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


# -- handshake ----------------------------------------------------------

def build_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    if len(info_hash) != 20:
        raise WireError("info_hash must be 20 bytes")
    if len(peer_id) != 20:
        raise WireError("peer_id must be 20 bytes")
    return (
        bytes([len(PSTR)]) + PSTR + (b"\0" * 8) + info_hash + peer_id
    )


def send_handshake(sock: socket.socket, info_hash: bytes, peer_id: bytes) -> None:
    sock.sendall(build_handshake(info_hash, peer_id))


def recv_handshake(sock: socket.socket):
    """Returns (info_hash, peer_id). Raises WireError on a malformed handshake."""
    raw = _recv_exact(sock, HANDSHAKE_LEN)
    pstrlen = raw[0]
    if pstrlen != len(PSTR):
        raise WireError(f"unexpected pstrlen {pstrlen}")
    pstr = raw[1:1 + pstrlen]
    if pstr != PSTR:
        raise WireError(f"unexpected protocol string {pstr!r}")
    info_hash = raw[1 + pstrlen + 8: 1 + pstrlen + 8 + 20]
    peer_id = raw[1 + pstrlen + 28: 1 + pstrlen + 28 + 20]
    return info_hash, peer_id


# -- message framing ------------------------------------------------------

def encode_message(msg_id: int, payload: bytes = b"") -> bytes:
    length = 1 + len(payload)
    return struct.pack(">I", length) + bytes([msg_id]) + payload


def encode_keepalive() -> bytes:
    return struct.pack(">I", 0)


def recv_message(sock: socket.socket, timeout: float | None = None):
    """Read one message. Returns (msg_id, payload) or (None, b"") for
    keep-alive. Raises WireError on disconnect/timeout.
    """
    old_timeout = sock.gettimeout()
    if timeout is not None:
        sock.settimeout(timeout)
    try:
        length_raw = _recv_exact(sock, 4)
        # Once the length prefix has arrived, commit to reading the full
        # body without the poll timeout — a partial body is a desync risk,
        # not something worth bailing out of early.
        if timeout is not None:
            sock.settimeout(None)
        (length,) = struct.unpack(">I", length_raw)
        if length == 0:
            return None, b""
        body = _recv_exact(sock, length)
        return body[0], body[1:]
    finally:
        if timeout is not None:
            sock.settimeout(old_timeout)


def message_name(msg_id):
    return _NAMES.get(msg_id, f"unknown({msg_id})")


# -- payload helpers --------------------------------------------------

def pack_have(index: int) -> bytes:
    return struct.pack(">I", index)


def unpack_have(payload: bytes) -> int:
    return struct.unpack(">I", payload)[0]


def pack_request(index: int, begin: int, length: int) -> bytes:
    return struct.pack(">III", index, begin, length)


def unpack_request(payload: bytes):
    return struct.unpack(">III", payload)


def pack_piece(index: int, begin: int, block: bytes) -> bytes:
    return struct.pack(">II", index, begin) + block


def unpack_piece(payload: bytes):
    index, begin = struct.unpack(">II", payload[:8])
    return index, begin, payload[8:]


def bitfield_has(bitfield: bytes, index: int) -> bool:
    byte_i, bit_i = index // 8, index % 8
    if byte_i >= len(bitfield):
        return False
    return bool(bitfield[byte_i] & (0x80 >> bit_i))


def bitfield_indices(bitfield: bytes, num_pieces: int):
    return {i for i in range(num_pieces) if bitfield_has(bitfield, i)}
