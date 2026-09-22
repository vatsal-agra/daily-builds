"""The real BEP-3 peer wire protocol: the handshake and the ten message
types two independent BitTorrent-speaking processes use to talk about a
single torrent over one already-open TCP connection.

Wire shapes (all multi-byte integers big-endian, per spec):

    handshake:  pstrlen(1) pstr(19="BitTorrent protocol") reserved(8)
                info_hash(20) peer_id(20)                    = 68 bytes

    message:    length_prefix(4) [ id(1) payload(length_prefix-1) ]
                length_prefix == 0  -> keep-alive, no id/payload at all

    id  name             payload
    0   choke            (none)
    1   unchoke          (none)
    2   interested       (none)
    3   not interested   (none)
    4   have             piece_index(4)
    5   bitfield         bytes, one bit per piece, MSB of byte 0 = piece 0
    6   request          index(4) begin(4) length(4)
    7   piece            index(4) begin(4) block(...)
    8   cancel           index(4) begin(4) length(4)

This module is pure encode/decode over bytes -- no sockets -- so both wire
correctness (round-tripping every message shape) and swarm behavior
(node.py, which does own the sockets) can be tested independently.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional, Union

PROTOCOL_NAME = b"BitTorrent protocol"
HANDSHAKE_LEN = 1 + len(PROTOCOL_NAME) + 8 + 20 + 20
PEER_ID_LEN = 20
INFO_HASH_LEN = 20

MSG_CHOKE = 0
MSG_UNCHOKE = 1
MSG_INTERESTED = 2
MSG_NOT_INTERESTED = 3
MSG_HAVE = 4
MSG_BITFIELD = 5
MSG_REQUEST = 6
MSG_PIECE = 7
MSG_CANCEL = 8

_NO_PAYLOAD = frozenset({MSG_CHOKE, MSG_UNCHOKE, MSG_INTERESTED, MSG_NOT_INTERESTED})


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Handshake:
    info_hash: bytes
    peer_id: bytes

    def __post_init__(self):
        if len(self.info_hash) != INFO_HASH_LEN:
            raise ProtocolError(f"info_hash must be {INFO_HASH_LEN} bytes, got {len(self.info_hash)}")
        if len(self.peer_id) != PEER_ID_LEN:
            raise ProtocolError(f"peer_id must be {PEER_ID_LEN} bytes, got {len(self.peer_id)}")

    def encode(self) -> bytes:
        return (
            bytes([len(PROTOCOL_NAME)])
            + PROTOCOL_NAME
            + b"\x00" * 8  # reserved extension bits; none of BEP-3's optional
            # extensions (DHT, fast, extension protocol) are implemented, so
            # every reserved bit is honestly zero rather than claiming a
            # capability that doesn't exist.
            + self.info_hash
            + self.peer_id
        )

    @staticmethod
    def decode(data: bytes) -> "Handshake":
        if len(data) != HANDSHAKE_LEN:
            raise ProtocolError(f"handshake must be exactly {HANDSHAKE_LEN} bytes, got {len(data)}")
        pstrlen = data[0]
        if pstrlen != len(PROTOCOL_NAME):
            raise ProtocolError(f"unexpected pstrlen {pstrlen}")
        pstr = data[1 : 1 + pstrlen]
        if pstr != PROTOCOL_NAME:
            raise ProtocolError(f"unexpected protocol string {pstr!r}")
        offset = 1 + pstrlen + 8
        info_hash = data[offset : offset + 20]
        peer_id = data[offset + 20 : offset + 40]
        return Handshake(info_hash=info_hash, peer_id=peer_id)


@dataclass(frozen=True)
class Message:
    id: int
    payload: bytes = b""

    def encode(self) -> bytes:
        body = bytes([self.id]) + self.payload
        return struct.pack(">I", len(body)) + body


KeepAlive = None  # sentinel returned by decode_message for a zero-length message


def choke() -> Message:
    return Message(MSG_CHOKE)


def unchoke() -> Message:
    return Message(MSG_UNCHOKE)


def interested() -> Message:
    return Message(MSG_INTERESTED)


def not_interested() -> Message:
    return Message(MSG_NOT_INTERESTED)


def have(piece_index: int) -> Message:
    return Message(MSG_HAVE, struct.pack(">I", piece_index))


def bitfield(bits: bytes) -> Message:
    return Message(MSG_BITFIELD, bytes(bits))


def request(index: int, begin: int, length: int) -> Message:
    return Message(MSG_REQUEST, struct.pack(">III", index, begin, length))


def piece(index: int, begin: int, block: bytes) -> Message:
    return Message(MSG_PIECE, struct.pack(">II", index, begin) + bytes(block))


def cancel(index: int, begin: int, length: int) -> Message:
    return Message(MSG_CANCEL, struct.pack(">III", index, begin, length))


@dataclass(frozen=True)
class HaveMsg:
    piece_index: int


@dataclass(frozen=True)
class BitfieldMsg:
    bits: bytes


@dataclass(frozen=True)
class RequestMsg:
    index: int
    begin: int
    length: int


@dataclass(frozen=True)
class PieceMsg:
    index: int
    begin: int
    block: bytes


@dataclass(frozen=True)
class CancelMsg:
    index: int
    begin: int
    length: int


@dataclass(frozen=True)
class SimpleMsg:
    """choke / unchoke / interested / not-interested: id only, no payload."""

    id: int


ParsedMessage = Union[SimpleMsg, HaveMsg, BitfieldMsg, RequestMsg, PieceMsg, CancelMsg]


def parse_message(msg: Message) -> ParsedMessage:
    """Turn a raw Message(id, payload) into a typed, field-named object."""
    if msg.id in _NO_PAYLOAD:
        if msg.payload:
            raise ProtocolError(f"message id {msg.id} must carry no payload, got {len(msg.payload)} bytes")
        return SimpleMsg(msg.id)
    if msg.id == MSG_HAVE:
        if len(msg.payload) != 4:
            raise ProtocolError(f"have payload must be 4 bytes, got {len(msg.payload)}")
        (index,) = struct.unpack(">I", msg.payload)
        return HaveMsg(index)
    if msg.id == MSG_BITFIELD:
        return BitfieldMsg(msg.payload)
    if msg.id == MSG_REQUEST:
        if len(msg.payload) != 12:
            raise ProtocolError(f"request payload must be 12 bytes, got {len(msg.payload)}")
        index, begin, length = struct.unpack(">III", msg.payload)
        return RequestMsg(index, begin, length)
    if msg.id == MSG_PIECE:
        if len(msg.payload) < 8:
            raise ProtocolError(f"piece payload must be >= 8 bytes, got {len(msg.payload)}")
        index, begin = struct.unpack(">II", msg.payload[:8])
        return PieceMsg(index, begin, msg.payload[8:])
    if msg.id == MSG_CANCEL:
        if len(msg.payload) != 12:
            raise ProtocolError(f"cancel payload must be 12 bytes, got {len(msg.payload)}")
        index, begin, length = struct.unpack(">III", msg.payload)
        return CancelMsg(index, begin, length)
    raise ProtocolError(f"unknown message id {msg.id}")


def decode_message(data: bytes) -> Message:
    """Decode a message body (id + payload, WITHOUT the length prefix)."""
    if not data:
        raise ProtocolError("empty message body has no id")
    return Message(id=data[0], payload=data[1:])


def recvall(sock, n: int) -> bytes:
    """Read exactly n bytes from a blocking socket, or raise on EOF."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(f"peer closed connection with {remaining} of {n} bytes still expected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_handshake(sock, info_hash: bytes, peer_id: bytes) -> None:
    sock.sendall(Handshake(info_hash, peer_id).encode())


def read_handshake(sock) -> Handshake:
    return Handshake.decode(recvall(sock, HANDSHAKE_LEN))


def send_message(sock, msg: Message) -> None:
    sock.sendall(msg.encode())


def read_message(sock, max_length: int = 32 * 1024 * 1024) -> Optional[ParsedMessage]:
    """Read one message off the wire. Returns None for a keep-alive.

    `max_length` bounds the length prefix we're willing to honor: an
    unbounded read here would let a malicious or buggy peer claim a
    multi-gigabyte message and force this process to buffer it, a classic
    protocol-level denial-of-service footgun this implementation refuses
    to have even though the demo itself is fully cooperative.
    """
    length_bytes = recvall(sock, 4)
    (length,) = struct.unpack(">I", length_bytes)
    if length == 0:
        return None
    if length > max_length:
        raise ProtocolError(f"message length {length} exceeds max_length {max_length}")
    body = recvall(sock, length)
    return parse_message(decode_message(body))


def send_keepalive(sock) -> None:
    sock.sendall(struct.pack(">I", 0))
