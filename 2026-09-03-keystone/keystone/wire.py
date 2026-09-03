"""Length-prefixed JSON message framing over a TCP socket — the wire
protocol every peer connection speaks."""
from __future__ import annotations

import json
import socket
import struct

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class ConnectionClosed(Exception):
    pass


def send_msg(sock: socket.socket, obj: dict) -> None:
    payload = json.dumps(obj).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    header = struct.pack(">I", len(payload))
    sock.sendall(header + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionClosed("peer closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_msg(sock: socket.socket) -> dict:
    header = _recv_exact(sock, 4)
    (length,) = struct.unpack(">I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    payload = _recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))
