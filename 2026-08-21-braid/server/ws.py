"""A from-scratch RFC 6455 WebSocket server layer over raw TCP sockets.

No `websockets`, no `ws4py`, no asyncio websocket lib — just `socket`,
`hashlib`, `base64`, and `struct`. Implements exactly what Braid needs:
the opening HTTP Upgrade handshake, unmasked server->client text frames,
masked client->server frame decoding (with the 7/16/64-bit payload-length
forms), and close/ping/pong opcodes. Documented, deliberate scope limit:
inbound message fragmentation (`fin=0` continuation frames) is not
implemented — every Braid message is a single small JSON object that
fits comfortably in one frame, and a real browser `WebSocket.send()` of
a JS string never fragments on its own, so this is a real, accepted
limitation rather than a hidden one (see REVIEW.md).
"""

from __future__ import annotations

import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONT = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketClosed(Exception):
    pass


def compute_accept(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _readline(conn, limit=8192) -> bytes:
    """Read exactly one CRLF-terminated line, byte at a time, so we never
    over-read past the HTTP headers into what will become WebSocket frame
    bytes on the same socket (a buffered readline() risks exactly that)."""
    buf = bytearray()
    while True:
        b = conn.recv(1)
        if not b:
            break
        buf += b
        if buf.endswith(b"\r\n") or buf.endswith(b"\n"):
            break
        if len(buf) > limit:
            raise ValueError("HTTP header line too long")
    return bytes(buf)


def parse_http_request(conn):
    """Read a request line + headers from `conn`. Returns (method, path,
    headers_dict) or (None, None, {}) on empty/broken request."""
    request_line = _readline(conn).decode("iso-8859-1")
    if not request_line.strip():
        return None, None, {}
    parts = request_line.split()
    if len(parts) < 2:
        return None, None, {}
    method, path = parts[0], parts[1]
    headers = {}
    while True:
        line = _readline(conn).decode("iso-8859-1")
        if line in ("\r\n", "\n", ""):
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return method, path, headers


def is_websocket_upgrade(headers: dict) -> bool:
    return (
        headers.get("upgrade", "").lower() == "websocket"
        and "sec-websocket-key" in headers
    )


def do_handshake(conn, headers: dict) -> None:
    accept = compute_accept(headers["sec-websocket-key"])
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    conn.sendall(response.encode("ascii"))


def encode_frame(payload: bytes, opcode: int = OPCODE_TEXT) -> bytes:
    fin_opcode = 0x80 | opcode
    length = len(payload)
    if length <= 125:
        header = bytes([fin_opcode, length])
    elif length <= 0xFFFF:
        header = bytes([fin_opcode, 126]) + struct.pack(">H", length)
    else:
        header = bytes([fin_opcode, 127]) + struct.pack(">Q", length)
    return header + payload  # server -> client frames are never masked


def _recv_exact(conn, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise WebSocketClosed("connection closed mid-frame")
        buf += chunk
    return bytes(buf)


def decode_frame(conn):
    """Read and decode exactly one client->server frame. Returns
    (opcode, payload_bytes, fin_bit)."""
    b0, b1 = _recv_exact(conn, 2)
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(conn, 8))[0]
    mask_key = _recv_exact(conn, 4) if masked else b"\x00\x00\x00\x00"
    payload = _recv_exact(conn, length) if length else b""
    if masked:
        payload = bytes(byte ^ mask_key[i % 4] for i, byte in enumerate(payload))
    return opcode, payload, fin


def send_text(conn, text: str) -> None:
    conn.sendall(encode_frame(text.encode("utf-8"), OPCODE_TEXT))


def send_close(conn) -> None:
    try:
        conn.sendall(encode_frame(b"", OPCODE_CLOSE))
    except OSError:
        pass


def send_pong(conn, payload: bytes = b"") -> None:
    conn.sendall(encode_frame(payload, OPCODE_PONG))


def recv_text(conn) -> str:
    """Read one complete text message (single-frame only, see module
    docstring), handling ping frames transparently by replying pong and
    continuing to wait for the actual text frame."""
    while True:
        opcode, payload, fin = decode_frame(conn)
        if opcode == OPCODE_CLOSE:
            raise WebSocketClosed("peer sent close frame")
        if opcode == OPCODE_PING:
            send_pong(conn, payload)
            continue
        if opcode == OPCODE_PONG:
            continue
        if opcode in (OPCODE_TEXT, OPCODE_CONT):
            if not fin:
                raise NotImplementedError(
                    "fragmented WebSocket messages are not supported by this "
                    "from-scratch server (see server/ws.py docstring)"
                )
            return payload.decode("utf-8")
        raise NotImplementedError(f"unsupported opcode {opcode:#x}")
