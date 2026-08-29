"""RFC 6455 WebSockets, built directly on the same raw sockets the HTTP
side uses -- the handshake is just a normal HTTP request/response (with an
`Upgrade` header) parsed by our own `RequestParser`; everything after that
is this module's frame codec running straight off the socket's byte
stream.
"""

import base64
import hashlib
import struct
from collections import namedtuple

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

_CONTROL_OPCODES = (OP_CLOSE, OP_PING, OP_PONG)
_DATA_OPCODES = (OP_TEXT, OP_BINARY)

MAX_FRAME_PAYLOAD = 16 * 1024 * 1024

Frame = namedtuple("Frame", "fin opcode payload")
Message = namedtuple("Message", "kind opcode payload")  # kind: 'data' | 'control'


class WSProtocolError(Exception):
    pass


def compute_accept(client_key: str) -> str:
    """Sec-WebSocket-Accept = base64(SHA1(key + magic GUID))."""
    digest = hashlib.sha1((client_key.strip() + WS_MAGIC).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def is_upgrade_request(headers) -> bool:
    conn = (headers.get("Connection") or "").lower()
    upgrade = (headers.get("Upgrade") or "").lower()
    return "upgrade" in conn and upgrade == "websocket"


def validate_handshake(headers):
    """Returns the Sec-WebSocket-Key, or raises WSProtocolError."""
    if headers.get("Sec-WebSocket-Version") != "13":
        raise WSProtocolError("unsupported Sec-WebSocket-Version")
    key = headers.get("Sec-WebSocket-Key")
    if not key:
        raise WSProtocolError("missing Sec-WebSocket-Key")
    try:
        if len(base64.b64decode(key)) != 16:
            raise WSProtocolError("malformed Sec-WebSocket-Key")
    except Exception:
        raise WSProtocolError("malformed Sec-WebSocket-Key")
    return key


class WebSocketParser:
    """Incremental RFC 6455 frame decoder. Feed raw bytes; get back
    assembled `Message`s (continuation frames are reassembled here so
    callers never see fragmentation)."""

    def __init__(self, max_frame_payload=MAX_FRAME_PAYLOAD, require_mask=True):
        self._buf = b""
        self.max_frame_payload = max_frame_payload
        self.require_mask = require_mask
        self._msg_opcode = None
        self._msg_chunks = None
        self._msg_total = 0

    def feed(self, data: bytes):
        if data:
            self._buf += data
        out = []
        while True:
            frame = self._try_parse_frame()
            if frame is None:
                break
            msg = self._assemble(frame)
            if msg is not None:
                out.append(msg)
        return out

    def _try_parse_frame(self):
        buf = self._buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        fin = bool(b0 & 0x80)
        rsv = b0 & 0x70
        if rsv != 0:
            raise WSProtocolError("nonzero RSV bits (no extension negotiated)")
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        if self.require_mask and not masked:
            raise WSProtocolError("client frames must be masked")
        plen = b1 & 0x7F
        pos = 2
        if plen == 126:
            if len(buf) < pos + 2:
                return None
            plen = struct.unpack("!H", buf[pos:pos + 2])[0]
            pos += 2
        elif plen == 127:
            if len(buf) < pos + 8:
                return None
            plen = struct.unpack("!Q", buf[pos:pos + 8])[0]
            pos += 8
        if plen > self.max_frame_payload:
            raise WSProtocolError("frame payload exceeds limit")
        mask_key = None
        if masked:
            if len(buf) < pos + 4:
                return None
            mask_key = buf[pos:pos + 4]
            pos += 4
        if len(buf) < pos + plen:
            return None
        raw_payload = buf[pos:pos + plen]
        self._buf = buf[pos + plen:]
        if masked:
            payload = bytearray(raw_payload)
            for i in range(len(payload)):
                payload[i] ^= mask_key[i % 4]
            payload = bytes(payload)
        else:
            payload = bytes(raw_payload)
        if opcode in _CONTROL_OPCODES and (not fin or plen > 125):
            raise WSProtocolError("control frames must not be fragmented and must be <=125 bytes")
        if opcode not in _CONTROL_OPCODES and opcode not in _DATA_OPCODES and opcode != OP_CONTINUATION:
            raise WSProtocolError(f"unknown opcode 0x{opcode:x}")
        return Frame(fin, opcode, payload)

    def _assemble(self, frame: Frame):
        if frame.opcode in _CONTROL_OPCODES:
            return Message("control", frame.opcode, frame.payload)
        if frame.opcode in _DATA_OPCODES:
            if self._msg_opcode is not None:
                raise WSProtocolError("expected a continuation frame, got a new data frame")
            if frame.fin:
                return Message("data", frame.opcode, frame.payload)
            self._msg_opcode = frame.opcode
            self._msg_chunks = [frame.payload]
            self._msg_total = len(frame.payload)
            return None
        # OP_CONTINUATION
        if self._msg_opcode is None:
            raise WSProtocolError("unexpected continuation frame")
        self._msg_total += len(frame.payload)
        if self._msg_total > self.max_frame_payload:
            raise WSProtocolError("assembled message exceeds limit")
        self._msg_chunks.append(frame.payload)
        if frame.fin:
            payload = b"".join(self._msg_chunks)
            opcode = self._msg_opcode
            self._msg_opcode = None
            self._msg_chunks = None
            return Message("data", opcode, payload)
        return None


def encode_frame(opcode: int, payload: bytes, fin: bool = True, mask: bool = False) -> bytes:
    b0 = (0x80 if fin else 0) | (opcode & 0x0F)
    length = len(payload)
    if length <= 125:
        header = struct.pack("!BB", b0, length | (0x80 if mask else 0))
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", b0, 126 | (0x80 if mask else 0), length)
    else:
        header = struct.pack("!BBQ", b0, 127 | (0x80 if mask else 0), length)
    if not mask:
        return header + payload
    import os
    mask_key = os.urandom(4)
    masked = bytearray(payload)
    for i in range(len(masked)):
        masked[i] ^= mask_key[i % 4]
    return header + mask_key + bytes(masked)


def encode_text(s: str) -> bytes:
    return encode_frame(OP_TEXT, s.encode("utf-8"))


def encode_binary(b: bytes) -> bytes:
    return encode_frame(OP_BINARY, b)


def encode_close(code: int = 1000, reason: str = "") -> bytes:
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    return encode_frame(OP_CLOSE, payload)


def encode_ping(payload: bytes = b"") -> bytes:
    return encode_frame(OP_PING, payload)


def encode_pong(payload: bytes = b"") -> bytes:
    return encode_frame(OP_PONG, payload)


def parse_close_payload(payload: bytes):
    if len(payload) == 0:
        return 1005, ""
    if len(payload) < 2:
        raise WSProtocolError("malformed close frame")
    code = struct.unpack("!H", payload[:2])[0]
    reason = payload[2:].decode("utf-8", errors="replace")
    return code, reason
