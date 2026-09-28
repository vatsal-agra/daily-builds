"""Length-prefixed JSON framing over a TCP stream.

Every message is a 4-byte big-endian length prefix followed by that many
bytes of UTF-8 JSON. This is the whole wire protocol: no HTTP, no
serialization library, just enough framing to know where one message ends
and the next begins on a raw stream socket.
"""

import json
import struct

_LEN_STRUCT = struct.Struct(">I")
MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class ProtocolError(Exception):
    pass


def send_msg(sock, obj) -> None:
    data = json.dumps(obj).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message too large: {len(data)} bytes")
    sock.sendall(_LEN_STRUCT.pack(len(data)) + data)


def _recv_exact(sock, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ProtocolError("connection closed mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_msg(sock):
    header = _recv_exact(sock, _LEN_STRUCT.size)
    (length,) = _LEN_STRUCT.unpack(header)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message too large: {length} bytes")
    data = _recv_exact(sock, length)
    return json.loads(data.decode("utf-8"))
