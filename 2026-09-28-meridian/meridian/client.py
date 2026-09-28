"""Real-socket RPC client: the `rpc_call` implementation node.py's transport
-agnostic algorithms use once nodes are actual separate OS processes."""

from __future__ import annotations

import socket

from . import protocol
from .node import KeyNotFoundError, NodeRef, RPCError

DEFAULT_TIMEOUT = 2.0


def call(node_ref: NodeRef, method: str, params: dict, timeout: float = DEFAULT_TIMEOUT):
    """Open a fresh connection, send one request, read one response, close.

    One-shot-per-call keeps the protocol trivial (no connection pooling,
    no multiplexing, no partial-write bookkeeping across calls) at the
    cost of a TCP handshake per RPC -- an entirely reasonable trade for a
    from-scratch teaching implementation, and it is what makes killing a
    node mid-demo behave exactly like a real crash: the next call to it
    simply fails to connect.
    """
    try:
        with socket.create_connection(node_ref.addr(), timeout=timeout) as sock:
            sock.settimeout(timeout)
            protocol.send_msg(sock, {"method": method, "params": params})
            resp = protocol.recv_msg(sock)
    except (OSError, protocol.ProtocolError, socket.timeout) as e:
        raise RPCError(f"{node_ref}: {method} failed: {e}") from e

    if "error" in resp:
        if resp.get("error_type") == "KeyNotFoundError":
            raise KeyNotFoundError(resp["error"])
        raise RPCError(f"{node_ref}: {method} returned error: {resp['error']}")
    return resp.get("result")
