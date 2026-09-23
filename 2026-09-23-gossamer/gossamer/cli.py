"""gossamer: command-line interface.

    gossamer cluster start --nodes A,B,C,D,E --base-port 9500 --n 3 --r 2 --w 2
    gossamer put mykey '"some json value"'
    gossamer get mykey
    gossamer status
    gossamer cluster stop
    gossamer demo
"""
import argparse
import json
import os
import signal
import sys

from . import client
from .cluster import Cluster, DEFAULT_KWARGS

STATE_FILE = ".gossamer-cluster.json"


class _StubCluster:
    """A read-only view of a running cluster, reconstructed from the state
    file, so `put`/`get`/`status` can be separate CLI invocations from
    whatever process ran `cluster start`."""

    def __init__(self, peers):
        self.peers = peers

    def address_of(self, node_id):
        return tuple(self.peers[node_id])


def _load_state():
    if not os.path.exists(STATE_FILE):
        print(f"no running cluster found ({STATE_FILE} missing) -- run "
              f"'gossamer cluster start' first", file=sys.stderr)
        sys.exit(1)
    with open(STATE_FILE) as f:
        return json.load(f)


def cmd_cluster_start(args):
    node_ids = args.nodes.split(",")
    kwargs = dict(DEFAULT_KWARGS)
    kwargs.update(n=args.n, r=args.r, w=args.w, vnodes=args.vnodes)
    c = Cluster(node_ids, base_port=args.base_port, **kwargs)
    c.start_all()
    state = {
        "peers": {nid: list(addr) for nid, addr in c.peers.items()},
        "pids": {nid: proc.pid for nid, proc in c.procs.items()},
        "config_dir": c.config_dir,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"cluster up: {node_ids} on ports starting at {args.base_port}")
    print(f"state written to {STATE_FILE}")


def cmd_cluster_stop(args):
    state = _load_state()
    for nid, pid in state["pids"].items():
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"killed {nid} (pid {pid})")
        except ProcessLookupError:
            print(f"{nid} (pid {pid}) already gone")
    os.remove(STATE_FILE)


def cmd_cluster_kill(args):
    state = _load_state()
    pid = state["pids"].get(args.node)
    if pid is None:
        print(f"unknown node {args.node}", file=sys.stderr)
        sys.exit(1)
    os.kill(pid, signal.SIGKILL)
    print(f"killed {args.node} (pid {pid})")


def _resolve_coordinator(state, via):
    if via is None:
        return next(iter(state["peers"]))
    if via not in state["peers"]:
        known = ", ".join(sorted(state["peers"]))
        print(f"unknown node {via!r} -- known nodes: {known}", file=sys.stderr)
        sys.exit(1)
    return via


def _run_client_call(fn, *args):
    from . import httpjson
    try:
        return fn(*args)
    except httpjson.NodeUnreachable as e:
        print(f"coordinator unreachable: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_put(args):
    state = _load_state()
    cluster = _StubCluster(state["peers"])
    coordinator = _resolve_coordinator(state, args.via)
    try:
        context = json.loads(args.context) if args.context else None
    except json.JSONDecodeError:
        print(f"--context is not valid JSON: {args.context!r}", file=sys.stderr)
        sys.exit(1)
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    status, body = _run_client_call(client.put, cluster, coordinator, args.key, value, context)
    print(json.dumps(body, indent=2))
    sys.exit(0 if status == 200 else 1)


def cmd_get(args):
    state = _load_state()
    cluster = _StubCluster(state["peers"])
    coordinator = _resolve_coordinator(state, args.via)
    status, body = _run_client_call(client.get, cluster, coordinator, args.key)
    print(json.dumps(body, indent=2))
    sys.exit(0 if status == 200 else 1)


def cmd_status(args):
    state = _load_state()
    from . import httpjson
    for nid, addr in state["peers"].items():
        host, port = addr
        try:
            status, body = httpjson.get_json(host, port, "/admin/status", timeout=1.0)
            print(f"{nid}: {json.dumps(body)}")
        except httpjson.NodeUnreachable:
            print(f"{nid}: unreachable")


def cmd_demo(args):
    from . import demo
    demo.main()


def build_parser():
    p = argparse.ArgumentParser(prog="gossamer")
    sub = p.add_subparsers(dest="command", required=True)

    cluster_p = sub.add_parser("cluster", help="manage a local cluster")
    cluster_sub = cluster_p.add_subparsers(dest="cluster_command", required=True)

    start_p = cluster_sub.add_parser("start")
    start_p.add_argument("--nodes", default="A,B,C,D,E")
    start_p.add_argument("--base-port", type=int, default=9500)
    start_p.add_argument("--n", type=int, default=3)
    start_p.add_argument("--r", type=int, default=2)
    start_p.add_argument("--w", type=int, default=2)
    start_p.add_argument("--vnodes", type=int, default=32)
    start_p.set_defaults(func=cmd_cluster_start)

    stop_p = cluster_sub.add_parser("stop")
    stop_p.set_defaults(func=cmd_cluster_stop)

    kill_p = cluster_sub.add_parser("kill")
    kill_p.add_argument("node")
    kill_p.set_defaults(func=cmd_cluster_kill)

    put_p = sub.add_parser("put")
    put_p.add_argument("key")
    put_p.add_argument("value", help="JSON value (or a plain string)")
    put_p.add_argument("--context", help="JSON list of vector-clock contexts from a prior get")
    put_p.add_argument("--via", help="node id to coordinate through")
    put_p.set_defaults(func=cmd_put)

    get_p = sub.add_parser("get")
    get_p.add_argument("key")
    get_p.add_argument("--via", help="node id to coordinate through")
    get_p.set_defaults(func=cmd_get)

    status_p = sub.add_parser("status")
    status_p.set_defaults(func=cmd_status)

    demo_p = sub.add_parser("demo", help="run the full flagship demo")
    demo_p.set_defaults(func=cmd_demo)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
