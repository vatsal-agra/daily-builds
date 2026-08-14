"""UDP/TCP client transport for sending a DNS query and getting a validated
DNSMessage back -- used by both the recursive resolver and the CLI's `dig`.
No `dnspython`/`socket.getaddrinfo` DNS logic; just raw sockets.
"""

from __future__ import annotations

import socket
import struct

from .message import DNSMessage
from .name import DNSFormatError


class QueryTimeout(Exception):
    pass


class QueryError(Exception):
    pass


def _validate(resp: DNSMessage, query: DNSMessage, host: str, port: int) -> None:
    if resp.id != query.id:
        raise QueryError(f"response ID mismatch from {host}:{port}: sent {query.id}, got {resp.id}")
    if not resp.qr:
        raise QueryError(f"response from {host}:{port} does not have the QR bit set")
    if query.questions:
        want = query.questions[0]
        if not resp.questions or resp.questions[0].qname != want.qname or resp.questions[0].qtype != want.qtype:
            raise QueryError(f"response from {host}:{port} answers a different question than asked")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            raise QueryError("connection closed before a full message was received")
        chunks.extend(chunk)
    return bytes(chunks)


def udp_query(message: DNSMessage, host: str, port: int, timeout: float = 2.0) -> DNSMessage:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(message.to_wire(), (host, port))
        data, _ = sock.recvfrom(65535)
    except socket.timeout:
        raise QueryTimeout(f"no response from {host}:{port} within {timeout}s")
    finally:
        sock.close()
    try:
        resp = DNSMessage.from_wire(data)
    except DNSFormatError as e:
        raise QueryError(f"malformed response from {host}:{port}: {e}")
    _validate(resp, message, host, port)
    return resp


def tcp_query(message: DNSMessage, host: str, port: int, timeout: float = 5.0) -> DNSMessage:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        wire = message.to_wire()
        sock.sendall(struct.pack("!H", len(wire)) + wire)
        (length,) = struct.unpack("!H", _recv_exact(sock, 2))
        data = _recv_exact(sock, length)
    except socket.timeout:
        raise QueryTimeout(f"no TCP response from {host}:{port} within {timeout}s")
    finally:
        sock.close()
    try:
        resp = DNSMessage.from_wire(data)
    except DNSFormatError as e:
        raise QueryError(f"malformed TCP response from {host}:{port}: {e}")
    _validate(resp, message, host, port)
    return resp


def query(message: DNSMessage, host: str, port: int, timeout: float = 2.0, use_tcp: bool = False) -> DNSMessage:
    """Send `message` and return the validated response, transparently
    retrying over TCP if the UDP response comes back truncated (TC=1)."""
    if use_tcp:
        return tcp_query(message, host, port, timeout)
    resp = udp_query(message, host, port, timeout)
    if resp.tc:
        return tcp_query(message, host, port, timeout)
    return resp
