"""`swarm` command-line entry point."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from typing import Optional, Set

if os.environ.get("SWARM_DEBUG"):
    logging.basicConfig(level=logging.DEBUG, format="%(relativeCreated)8d %(threadName)s %(name)s %(message)s")

from . import torrentfile, tracker as tracker_mod
from .node import Node


def parse_piece_spec(spec: str) -> Set[int]:
    """"0-4,7,9-10" -> {0,1,2,3,4,7,9,10}"""
    out: Set[int] = set()
    spec = spec.strip()
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return out


def cmd_make_torrent(args: argparse.Namespace) -> int:
    info = torrentfile.create_torrent(args.file, announce=args.announce, piece_length=args.piece_length)
    out_path = args.output or (args.file + ".torrent")
    torrentfile.save_torrent(info, out_path)
    print(f"wrote {out_path}")
    print(f"  name:        {info.name}")
    print(f"  length:      {info.length} bytes")
    print(f"  piece_length:{info.piece_length} bytes")
    print(f"  pieces:      {info.num_pieces}")
    print(f"  info_hash:   {info.info_hash().hex()}")
    return 0


def cmd_tracker(args: argparse.Namespace) -> int:
    server = tracker_mod.run_tracker(args.host, args.port, interval=args.interval)
    print(f"tracker listening on http://{args.host}:{server.server_port}/announce")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def _make_node(args: argparse.Namespace, seed: bool) -> Node:
    info = torrentfile.load_torrent(args.torrent)
    tracker_url = args.tracker or info.announce
    preseed_pieces = parse_piece_spec(args.preseed) if getattr(args, "preseed", None) else None
    return Node(
        info,
        args.file if seed else args.out,
        tracker_url,
        host=args.host,
        port=args.port,
        seed=seed,
        preseed_source=getattr(args, "preseed_source", None),
        preseed_pieces=preseed_pieces,
        dashboard_url=getattr(args, "dashboard", None),
    )


def cmd_seed(args: argparse.Namespace) -> int:
    node = _make_node(args, seed=True)
    print(f"seeding on {node.host}:{node.port} peer_id={node.peer_id.hex()} info_hash={node.info_hash.hex()}")
    node.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
    return 0


def cmd_leech(args: argparse.Namespace) -> int:
    node = _make_node(args, seed=False)
    print(f"leeching on {node.host}:{node.port} peer_id={node.peer_id.hex()} info_hash={node.info_hash.hex()}")
    node.start()
    ok = node.wait_until_complete(timeout=args.timeout)
    if ok and args.seed_time > 0:
        # A real BitTorrent client doesn't vanish the instant its own
        # download finishes -- it keeps the connections it already has open
        # and keeps serving them, because other peers in the swarm may
        # still be relying on it as their only source for a piece (exactly
        # the case in the two-disjoint-halves demo scenario). Disconnecting
        # immediately on local completion would strand anyone still
        # mid-transfer with us the moment we're done, so stick around and
        # seed for a bit before actually stopping.
        time.sleep(args.seed_time)
    result = {
        "ok": ok,
        "peer_id": node.peer_id.hex(),
        "port": node.port,
        "have": node.piece_manager.have_count(),
        "total": node.piece_manager.num_pieces,
        "verified": node.piece_manager.verify_full_file() if ok else False,
        "piece_sources": {i: node.piece_manager.piece_source(i).hex() for i in range(node.piece_manager.num_pieces) if node.piece_manager.piece_source(i)},
    }
    node.stop()
    if args.status_file:
        with open(args.status_file, "w") as f:
            json.dump(result, f)
    print(json.dumps({k: v for k, v in result.items() if k != "piece_sources"}))
    return 0 if (ok and result["verified"]) else 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    from . import dashboard as dashboard_mod

    server = dashboard_mod.run_dashboard(args.host, args.port)
    print(f"dashboard listening on http://{args.host}:{server.server_port}/")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from . import demo as demo_mod

    return demo_mod.run_demo(verbose=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swarm", description="A from-scratch BitTorrent-style P2P file-sharing system")
    sub = p.add_subparsers(dest="command", required=True)

    mt = sub.add_parser("make-torrent", help="create a .torrent from a file")
    mt.add_argument("file")
    mt.add_argument("--announce", required=True, help="tracker URL, e.g. http://127.0.0.1:6969/announce")
    mt.add_argument("--piece-length", type=int, default=torrentfile.DEFAULT_PIECE_LENGTH)
    mt.add_argument("-o", "--output")
    mt.set_defaults(func=cmd_make_torrent)

    tr = sub.add_parser("tracker", help="run a standalone HTTP tracker")
    tr.add_argument("--host", default="127.0.0.1")
    tr.add_argument("--port", type=int, default=6969)
    tr.add_argument("--interval", type=int, default=tracker_mod.DEFAULT_INTERVAL)
    tr.set_defaults(func=cmd_tracker)

    db = sub.add_parser("dashboard", help="run a live SSE dashboard hub that Nodes can report events to")
    db.add_argument("--host", default="127.0.0.1")
    db.add_argument("--port", type=int, default=8642)
    db.set_defaults(func=cmd_dashboard)

    sd = sub.add_parser("seed", help="seed a complete file for a torrent")
    sd.add_argument("torrent")
    sd.add_argument("file", help="path to the already-complete file to seed")
    sd.add_argument("--host", default="127.0.0.1")
    sd.add_argument("--port", type=int, default=0)
    sd.add_argument("--tracker", default=None, help="override the tracker URL in the .torrent")
    sd.add_argument("--preseed", default=None)
    sd.add_argument("--preseed-source", default=None)
    sd.add_argument("--dashboard", default=None, help="dashboard hub URL, e.g. http://127.0.0.1:8642")
    sd.set_defaults(func=cmd_seed)

    lc = sub.add_parser("leech", help="download a torrent, optionally starting with some pieces already")
    lc.add_argument("torrent")
    lc.add_argument("--out", required=True, help="output file path")
    lc.add_argument("--host", default="127.0.0.1")
    lc.add_argument("--port", type=int, default=0)
    lc.add_argument("--tracker", default=None)
    lc.add_argument("--timeout", type=float, default=60.0)
    lc.add_argument("--seed-time", type=float, default=3.0, help="keep serving peers for this long after completing before exiting")
    lc.add_argument("--status-file", default=None)
    lc.add_argument("--preseed", default=None, help='e.g. "0-4,7,9-10"')
    lc.add_argument("--preseed-source", default=None, help="file to copy preseeded pieces' real bytes from")
    lc.add_argument("--dashboard", default=None, help="dashboard hub URL, e.g. http://127.0.0.1:8642")
    lc.set_defaults(func=cmd_leech)

    dm = sub.add_parser("demo", help="run the full end-to-end swarm demo")
    dm.set_defaults(func=cmd_demo)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
