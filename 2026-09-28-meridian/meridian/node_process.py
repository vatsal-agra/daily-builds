"""Process entrypoint: one Meridian Chord node per OS process.

    python -m meridian.node_process --port 9001
    python -m meridian.node_process --port 9002 --join 127.0.0.1:9001

Each invocation is an independent process with its own socket; there is no
shared memory between nodes; a `kill -9` on this process is exactly what
the ring's fault tolerance has to survive.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from . import hashing
from .node import NodeRef
from .server import ChordServer


def parse_addr(s: str) -> tuple[str, int]:
    host, _, port = s.rpartition(":")
    if not host:
        raise argparse.ArgumentTypeError(f"expected host:port, got {s!r}")
    return host, int(port)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run one Meridian Chord DHT node.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--join", type=parse_addr, default=None, metavar="HOST:PORT")
    ap.add_argument("--m-bits", type=int, default=hashing.DEFAULT_M_BITS)
    ap.add_argument("--r", type=int, default=4, help="successor-list length (replication factor)")
    ap.add_argument("--fast", action="store_true", help="short maintenance intervals, for tests/demos")
    args = ap.parse_args(argv)

    intervals = {"stabilize": 0.15, "fix_fingers": 0.15, "check_predecessor": 0.25, "replicate": 0.4} if args.fast else None

    server = ChordServer(args.host, args.port, m_bits=args.m_bits, r=args.r, intervals=intervals)
    server.serve_forever_in_background()

    bootstrap = None
    if args.join is not None:
        jhost, jport = args.join
        bootstrap = NodeRef(id=hashing.node_id_for_addr(jhost, jport, args.m_bits), host=jhost, port=jport)
    server.join_ring(bootstrap)

    print(f"READY {server.ref.id} {server.ref.host} {server.ref.port}", flush=True)

    stop = {"flag": False}

    def _handle_signal(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while not stop["flag"]:
            time.sleep(0.2)
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
