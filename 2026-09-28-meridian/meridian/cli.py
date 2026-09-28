"""Operator CLI for a real Meridian cluster of independent OS processes.

Cluster membership (host/port/pid per node) is tracked in a small JSON
state file (default `.meridian/cluster.json` under the current directory)
so that separate CLI invocations (`cluster start`, then later `put`,
`get`, `kill`, ...) can all find the same running cluster.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import client, hashing, node as node_mod
from .node import NodeRef, RPCError

DEFAULT_STATE_PATH = Path(".meridian/cluster.json")


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"m_bits": hashing.DEFAULT_M_BITS, "r": 4, "nodes": []}
    return json.loads(path.read_text())


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _node_ref(entry: dict, m_bits: int) -> NodeRef:
    return NodeRef(id=hashing.node_id_for_addr(entry["host"], entry["port"], m_bits), host=entry["host"], port=entry["port"])


def _first_alive_ref(state: dict) -> NodeRef:
    for entry in state["nodes"]:
        if not entry.get("killed"):
            return _node_ref(entry, state["m_bits"])
    raise SystemExit("no live nodes in cluster (everything has been killed)")


def cmd_cluster_start(args):
    state_path = Path(args.state)
    if state_path.exists() and not args.force:
        raise SystemExit(f"{state_path} already exists; pass --force to overwrite, or `cluster stop` first")

    nodes = []
    bootstrap_addr = None
    for i in range(args.n):
        port = args.base_port + i
        cmd = [sys.executable, "-m", "meridian.node_process", "--host", args.host, "--port", str(port),
               "--m-bits", str(args.m_bits), "--r", str(args.r)]
        if args.fast:
            cmd.append("--fast")
        if bootstrap_addr is not None:
            cmd += ["--join", bootstrap_addr]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not _wait_for_port(args.host, port):
            raise SystemExit(f"node on port {port} never came up")
        nodes.append({"host": args.host, "port": port, "pid": proc.pid, "killed": False})
        if bootstrap_addr is None:
            bootstrap_addr = f"{args.host}:{port}"
        # Give the join a brief moment before the next node bootstraps off
        # a slightly more settled ring; not required for correctness
        # (stabilization converges regardless) but makes demo output tidier.
        time.sleep(args.join_pause)

    state = {"m_bits": args.m_bits, "r": args.r, "nodes": nodes}
    _save_state(state_path, state)
    print(f"started {args.n} nodes; state written to {state_path}")
    for n in nodes:
        print(f"  {n['host']}:{n['port']}  pid={n['pid']}")


def cmd_cluster_stop(args):
    state_path = Path(args.state)
    state = _load_state(state_path)
    for entry in state["nodes"]:
        pid = entry.get("pid")
        if pid is None:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if state_path.exists():
        state_path.unlink()
    print(f"stopped {len(state['nodes'])} nodes")


def cmd_status(args):
    state = _load_state(Path(args.state))
    m_bits = state["m_bits"]
    print(f"{'ID':>12} {'ADDR':<22} {'PRED':>12} {'SUCC[0]':>12} {'KEYS':>6} {'REPLICAS':>9} {'STATUS'}")
    for entry in state["nodes"]:
        ref = _node_ref(entry, m_bits)
        if entry.get("killed"):
            print(f"{ref.id:>12} {ref.host + ':' + str(ref.port):<22} {'--':>12} {'--':>12} {'--':>6} {'--':>9} KILLED")
            continue
        try:
            snap = client.call(ref, "snapshot", {})
        except RPCError:
            print(f"{ref.id:>12} {ref.host + ':' + str(ref.port):<22} {'--':>12} {'--':>12} {'--':>6} {'--':>9} UNREACHABLE")
            continue
        pred = snap["predecessor"]["id"] if snap["predecessor"] else "--"
        succ0 = snap["successor_list"][0]["id"] if snap["successor_list"] else "--"
        print(f"{ref.id:>12} {ref.host + ':' + str(ref.port):<22} {str(pred):>12} {str(succ0):>12} "
              f"{snap['num_primary_keys']:>6} {snap['num_replica_owners']:>9} alive")


def cmd_put(args):
    state = _load_state(Path(args.state))
    start = _first_alive_ref(state)
    node_ref, hops = node_mod.put(args.key, args.value, start, client.call)
    print(f"stored {args.key!r} on node {node_ref} in {len(hops)} hop(s): " + " -> ".join(str(h) for h in hops))


def cmd_get(args):
    state = _load_state(Path(args.state))
    start = _first_alive_ref(state)
    try:
        value, hops = node_mod.get(args.key, start, client.call)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"get failed: {e}")
    print(f"{args.key!r} = {value!r}  (resolved in {len(hops)} hop(s): " + " -> ".join(str(h) for h in hops) + ")")


def cmd_kill(args):
    state_path = Path(args.state)
    state = _load_state(state_path)
    for entry in state["nodes"]:
        if entry["port"] == args.port:
            pid = entry["pid"]
            os.kill(pid, signal.SIGKILL)
            entry["killed"] = True
            _save_state(state_path, state)
            print(f"SIGKILL sent to pid {pid} (port {args.port}) -- simulating a hard crash")
            return
    raise SystemExit(f"no node on port {args.port} in {state_path}")


def cmd_trace(args):
    state = _load_state(Path(args.state))
    m_bits = state["m_bits"]
    alive_refs = [_node_ref(e, m_bits) for e in state["nodes"] if not e.get("killed")]
    if not alive_refs:
        raise SystemExit("no live nodes")

    snapshots = []
    for ref in alive_refs:
        try:
            snap = client.call(ref, "snapshot", {})
            snap["alive"] = True
        except RPCError:
            snap = {"id": ref.id, "host": ref.host, "port": ref.port, "alive": False,
                    "predecessor": None, "successor_list": [], "finger_table": [],
                    "num_primary_keys": 0, "num_replica_owners": 0}
        snapshots.append(snap)

    traces = []
    for key in args.keys:
        start = alive_refs[0]
        try:
            value, hops = node_mod.get(key, start, client.call)
            traces.append({"key": key, "value": value, "hops": [h.id for h in hops], "ok": True})
        except Exception as e:  # noqa: BLE001
            traces.append({"key": key, "error": str(e), "hops": [], "ok": False})

    payload = {"m_bits": m_bits, "nodes": snapshots, "traces": traces}
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(f"wrote trace snapshot to {args.out} ({len(snapshots)} nodes, {len(traces)} lookups)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="meridian", description="Operate a real Meridian Chord DHT cluster.")
    ap.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="cluster state file")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("cluster-start", help="spawn N real node processes and join them into a ring")
    p.add_argument("n", type=int)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--base-port", type=int, default=9000)
    p.add_argument("--m-bits", type=int, default=hashing.DEFAULT_M_BITS)
    p.add_argument("--r", type=int, default=4)
    p.add_argument("--fast", action="store_true")
    p.add_argument("--join-pause", type=float, default=0.05)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_cluster_start)

    p = sub.add_parser("cluster-stop", help="terminate all node processes in the cluster")
    p.set_defaults(fn=cmd_cluster_stop)

    p = sub.add_parser("status", help="dump ring topology from every node's own point of view")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("put", help="store a key/value pair in the ring")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(fn=cmd_put)

    p = sub.add_parser("get", help="look up a key in the ring")
    p.add_argument("key")
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("kill", help="SIGKILL the node process listening on the given port")
    p.add_argument("port", type=int)
    p.set_defaults(fn=cmd_kill)

    p = sub.add_parser("trace", help="capture ring topology + lookup traces to JSON for the visualizer")
    p.add_argument("keys", nargs="+")
    p.add_argument("--out", default="trace.json")
    p.set_defaults(fn=cmd_trace)

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
