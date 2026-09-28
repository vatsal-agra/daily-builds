"""Test-only scaffolding: a no-socket in-memory RPC transport for fast,
deterministic unit tests of the Chord algorithms themselves, and real
multi-process cluster orchestration for the integration tests."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian import client, hashing  # noqa: E402
from meridian.node import ChordNode, NodeRef, RPCError  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_ports(n: int) -> list[int]:
    """Allocate `n` free ports. `Cluster` used to grab one free port and
    assume the following n-1 consecutive port numbers were also free,
    which is not guaranteed -- a port a moment "free" for the single probe
    can already belong to some unrelated process, or to another test's
    cluster still in the process of releasing it. Binding all `n` sockets
    at once (so the OS hands out `n` genuinely distinct free ports) before
    closing any of them removes that assumption; the only race left is the
    much smaller window between closing a socket here and this process's
    own subsequent bind() of the same port."""
    socks = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def build_in_memory_rpc(registry: dict[int, ChordNode]):
    """A same-process rpc_call: dispatches straight into other ChordNode
    objects' own RPC-handler methods, mirroring server.py's dispatch table
    exactly but with zero sockets -- lets the Chord algorithms themselves
    be tested fast and deterministically, independent of any network or
    timing flakiness."""

    def rpc_call(node_ref: NodeRef, method: str, params: dict):
        node = registry.get(node_ref.id)
        if node is None:
            raise RPCError(f"no such in-memory node {node_ref.id}")
        if method == "find_successor_step":
            return node.local_find_successor_step(params["id"])
        if method == "get_successor_list":
            return {"successors": [n.to_dict() for n in node.get_successor_list()]}
        if method == "get_predecessor":
            p = node.get_predecessor()
            return {"predecessor": p.to_dict() if p else None}
        if method == "notify":
            node.notify(NodeRef.from_dict(params["node"]))
            return None
        if method == "ping":
            return {"id": node.ref.id}
        if method == "store":
            node.rpc_store(params["key"], params["value"])
            return None
        if method == "replicate":
            node.rpc_replicate(params["owner_id"], params["key"], params["value"])
            return None
        if method == "retrieve":
            return node.rpc_retrieve(params["key"])
        if method == "transfer_keys":
            return node.rpc_transfer_keys(params["new_node_id"])
        if method == "snapshot":
            return node.snapshot()
        raise RPCError(f"unknown method {method!r}")

    return rpc_call


def make_node_at_id(node_id: int, host: str, port: int, m_bits: int, r: int = 1) -> ChordNode:
    """Build a ChordNode and force it to a specific ring identifier instead
    of the usual hash-of-address one, so tests can reconstruct an exact
    published worked example (e.g. the Chord paper's own 3-bit ring)."""
    node = ChordNode(host, port, m_bits=m_bits, r=r)
    node.ref = NodeRef(id=node_id, host=host, port=port)
    node.successor_list = [node.ref] * r
    return node


def converge(nodes: list[ChordNode], rpc_call, rounds: int = 30) -> None:
    """Run enough stabilize()/fix_fingers()/check_predecessor() passes for
    an in-memory ring to reach its steady state. Deterministic (no sleeps):
    each round is just direct function calls."""
    for _ in range(rounds):
        for n in nodes:
            n.stabilize(rpc_call)
        for n in nodes:
            n.check_predecessor(rpc_call)
        for n in nodes:
            n.fix_fingers(rpc_call, batch=n.m_bits)


class Cluster:
    """A real multi-process Meridian cluster for integration tests."""

    def __init__(self, n: int, m_bits: int = hashing.DEFAULT_M_BITS, r: int = 4, host: str = "127.0.0.1"):
        self.m_bits = m_bits
        self.r = r
        self.host = host
        self.procs: list[subprocess.Popen] = []
        self.refs: list[NodeRef] = []
        ports = free_ports(n)
        bootstrap = None
        try:
            for port in ports:
                cmd = [sys.executable, "-m", "meridian.node_process", "--host", host, "--port", str(port),
                       "--m-bits", str(m_bits), "--r", str(r), "--fast"]
                if bootstrap is not None:
                    cmd += ["--join", bootstrap]
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         cwd=str(Path(__file__).resolve().parent.parent))
                self.procs.append(proc)
                ref = NodeRef(id=hashing.node_id_for_addr(host, port, m_bits), host=host, port=port)
                self._wait_ready(proc, ref)
                self.refs.append(ref)
                if bootstrap is None:
                    bootstrap = f"{host}:{port}"
                time.sleep(0.02)
        except Exception:
            # A partially-constructed cluster must not leak already-spawned
            # processes: the caller never gets a `Cluster` object back to
            # call .shutdown() on if __init__ raises, so clean up here.
            self.shutdown()
            raise

    @staticmethod
    def _wait_ready(proc: subprocess.Popen, ref: NodeRef, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"node process for {ref} exited early (code {proc.returncode})")
            try:
                client.call(ref, "ping", {}, timeout=0.3)
                return
            except RPCError:
                time.sleep(0.05)
        raise RuntimeError(f"node {ref} never came up")

    def kill(self, index: int) -> None:
        self.procs[index].kill()
        self.procs[index].wait(timeout=5)

    def alive_refs(self) -> list[NodeRef]:
        return [r for p, r in zip(self.procs, self.refs) if p.poll() is None]

    def wait_for_convergence(self, timeout: float = 8.0) -> bool:
        """Poll until every still-alive node's successor/predecessor
        pointers agree with the exact sorted cycle over alive nodes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ring_is_correct():
                return True
            time.sleep(0.2)
        return self._ring_is_correct()

    def _ring_is_correct(self) -> bool:
        alive = self.alive_refs()
        if not alive:
            return True
        ids_sorted = sorted(r.id for r in alive)
        for ref in alive:
            try:
                snap = client.call(ref, "snapshot", {}, timeout=1.0)
            except RPCError:
                return False
            idx = ids_sorted.index(ref.id)
            expected_succ = ids_sorted[(idx + 1) % len(ids_sorted)]
            expected_pred = ids_sorted[idx - 1]
            actual_succ = snap["successor_list"][0]["id"] if snap["successor_list"] else None
            actual_pred = snap["predecessor"]["id"] if snap["predecessor"] else None
            if actual_succ != expected_succ or actual_pred != expected_pred:
                return False
        return True

    def shutdown(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                p.kill()
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
