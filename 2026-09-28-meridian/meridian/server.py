"""RPC server: wraps a ChordNode with a real TCP listener, a method
dispatch table, and the three background maintenance loops (stabilize,
fix_fingers, check_predecessor) the Chord paper requires every node to run
continuously."""

from __future__ import annotations

import logging
import random
import socket
import socketserver
import threading
import time

from . import client, protocol
from .node import ChordNode, KeyNotFoundError, NodeRef, RPCError

log = logging.getLogger("meridian.server")


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            req = protocol.recv_msg(self.request)
        except (protocol.ProtocolError, OSError, ValueError):
            # Malformed/truncated message or a connection that dropped
            # mid-read: nothing useful to reply with, and definitely not
            # worth taking the server down over -- just drop this request.
            return
        if not isinstance(req, dict):
            return
        method = req.get("method")
        params = req.get("params", {})
        handler = self.server.dispatch.get(method)
        if handler is None:
            protocol.send_msg(self.request, {"error": f"unknown method {method!r}"})
            return
        try:
            result = handler(**params)
            protocol.send_msg(self.request, {"result": result})
        except KeyNotFoundError as e:
            protocol.send_msg(self.request, {"error": str(e), "error_type": "KeyNotFoundError"})
        except Exception as e:  # noqa: BLE001 - a handler crash must not take the process down
            log.exception("RPC handler for %s crashed", method)
            protocol.send_msg(self.request, {"error": f"{type(e).__name__}: {e}"})


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ChordServer:
    """A real node process's networking + maintenance shell around a ChordNode."""

    def __init__(self, host: str, port: int, m_bits: int, r: int, intervals: dict | None = None):
        self.node = ChordNode(host, port, m_bits=m_bits, r=r)
        self.node._rpc_pusher = self._rpc_call  # used by ChordNode.notify()'s key migration
        self._intervals = intervals or {"stabilize": 0.3, "fix_fingers": 0.3, "check_predecessor": 0.5, "replicate": 1.0}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        self._tcp = _ThreadingTCPServer((host, port), _Handler)
        self._tcp.dispatch = self._build_dispatch()

    # -- lifecycle --------------------------------------------------------

    def serve_forever_in_background(self):
        t = threading.Thread(target=self._tcp.serve_forever, daemon=True)
        t.start()
        self._threads.append(t)
        for name, fn in (
            ("stabilize", self._stabilize_loop),
            ("fix_fingers", self._fix_fingers_loop),
            ("check_predecessor", self._check_predecessor_loop),
            ("replicate", self._replicate_loop),
        ):
            th = threading.Thread(target=fn, name=name, daemon=True)
            th.start()
            self._threads.append(th)

    def shutdown(self):
        self._stop.set()
        self._tcp.shutdown()
        self._tcp.server_close()

    def join_ring(self, bootstrap: NodeRef | None):
        self.node.join(bootstrap, self._rpc_call)

    @property
    def ref(self) -> NodeRef:
        return self.node.ref

    # -- maintenance loops --------------------------------------------------

    def _rpc_call(self, node_ref: NodeRef, method: str, params: dict):
        if node_ref.id == self.node.ref.id:
            return self._local_call(method, params)
        return client.call(node_ref, method, params)

    def _local_call(self, method: str, params: dict):
        handler = self._tcp.dispatch[method]
        return handler(**params)

    def _loop(self, key: str, fn):
        base = self._intervals[key]
        while not self._stop.is_set():
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("maintenance loop %s crashed", key)
            time.sleep(base * (0.75 + 0.5 * random.random()))

    def _stabilize_loop(self):
        self._loop("stabilize", lambda: self.node.stabilize(self._rpc_call))

    def _fix_fingers_loop(self):
        self._loop("fix_fingers", lambda: self.node.fix_fingers(self._rpc_call))

    def _check_predecessor_loop(self):
        self._loop("check_predecessor", lambda: self.node.check_predecessor(self._rpc_call))

    def _replicate_loop(self):
        self._loop("replicate", lambda: self.node.replicate_to_successors(self._rpc_call))

    # -- RPC dispatch table --------------------------------------------------

    def _build_dispatch(self):
        n = self.node
        return {
            "find_successor_step": lambda id: n.local_find_successor_step(id),
            "get_successor_list": lambda: {"successors": [x.to_dict() for x in n.get_successor_list()]},
            "get_predecessor": lambda: {"predecessor": n.get_predecessor().to_dict() if n.get_predecessor() else None},
            "notify": lambda node: n.notify(NodeRef.from_dict(node)),
            "ping": lambda: {"id": n.ref.id},
            "store": lambda key, value: n.rpc_store(key, value),
            "replicate": lambda owner_id, key, value: n.rpc_replicate(owner_id, key, value),
            "retrieve": lambda key: n.rpc_retrieve(key),
            "transfer_keys": lambda new_node_id: n.rpc_transfer_keys(new_node_id),
            "snapshot": lambda: n.snapshot(),
        }
