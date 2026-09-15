"""The `causeway` command-line tool."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time

from .clock import RealClock
from .connection import Connection
from .simdriver import SimulationStalled, run_transfer
from .wire import RealUdpWire

DEFAULT_MSS = 536


def _validate_common(args) -> None:
    """Shared input validation for every subcommand that takes these flags.
    Raises ValueError with a clean, specific message; main() turns that into
    a one-line CLI error instead of a raw traceback."""
    for name in ("loss", "dup", "reorder"):
        val = getattr(args, name, None)
        if val is not None and not (0.0 <= val <= 1.0):
            raise ValueError(f"--{name} must be between 0 and 1, got {val}")
    mss = getattr(args, "mss", None)
    if mss is not None and mss < 1:
        raise ValueError(f"--mss must be >= 1, got {mss}")
    num_bytes = getattr(args, "bytes", None)
    if num_bytes is not None and num_bytes < 0:
        raise ValueError(f"--bytes must be >= 0, got {num_bytes}")


def _cmd_demo(args) -> int:
    _validate_common(args)
    data = os.urandom(args.bytes)
    events = {"client": [], "server": []}

    def on_event(who, e):
        if args.log_json:
            events[who].append(e)

    t0 = time.perf_counter()
    result = run_transfer(
        data, mss=args.mss, loss=args.loss, dup=args.dup, reorder=args.reorder,
        base_delay=args.delay_ms / 1000.0, jitter=args.jitter_ms / 1000.0, seed=args.seed,
        client_recv_capacity=args.recv_capacity, server_recv_capacity=args.recv_capacity,
        max_virtual_time=args.max_time,
        on_event=on_event if args.log_json else None,
    )
    wall = time.perf_counter() - t0

    print(f"transferred:      {result['bytes_sent']} bytes")
    print(f"byte-exact match: {result['success']}")
    print(f"sha256 (sent):    {result['sha_sent']}")
    print(f"sha256 (recv):    {result['sha_received']}")
    print(f"simulated time:   {result['virtual_time']:.3f}s  (wall time to simulate: {wall*1000:.1f}ms)")
    print(f"link stats:       {result['link_stats']}")
    print(f"client stats:     {result['client_stats']}")
    print(f"server stats:     {result['server_stats']}")

    if args.log_json:
        params = {k: v for k, v in vars(args).items() if k != "func"}
        with open(args.log_json, "w") as f:
            json.dump({
                "params": params,
                "result": {k: v for k, v in result.items() if k != "received"},
                "events": events,
            }, f)
        print(f"event log written to {args.log_json}")

    return 0 if result["success"] else 1


def _parse_addr(s: str):
    host, port = s.rsplit(":", 1)
    return (host, int(port))


def _pump_realtime(conn: Connection, poll_interval: float = 0.002, on_tick=None, deadline=None):
    clock = conn.clock
    while not conn.closed:
        conn.step(clock.now())
        if on_tick:
            on_tick()
        if deadline is not None and clock.now() > deadline:
            raise TimeoutError("connection did not reach CLOSED before the deadline")
        time.sleep(poll_interval)


def _cmd_send(args) -> int:
    _validate_common(args)
    with open(args.file, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.bind:
        sock.bind(_parse_addr(args.bind))
    peer = _parse_addr(args.peer)
    wire = RealUdpWire(sock, peer)
    clock = RealClock()
    conn = Connection("client", wire, clock, mss=args.mss, recv_capacity=args.recv_capacity)

    conn.send(data)
    conn.close()

    last_report = 0.0

    def report():
        nonlocal last_report
        now = clock.now()
        if now - last_report >= 0.5:
            last_report = now
            print(f"  acked {conn.snd_una}/{conn.snd_nxt - 1} bytes  cwnd={conn.cwnd:.0f} "
                  f"ssthresh={conn.ssthresh:.0f} srtt={conn.rtt.srtt} rto={conn.rtt.rto:.3f} "
                  f"retransmits={conn.stats['retransmits']}", file=sys.stderr)

    print(f"causeway send: {args.file} ({len(data)} bytes) -> {peer} sha256={sha}")
    try:
        _pump_realtime(conn, on_tick=report, deadline=clock.now() + args.timeout)
    except TimeoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"done. segments_sent={conn.stats['segments_sent']} retransmits={conn.stats['retransmits']} "
          f"timeouts={conn.stats['timeouts']} fast_retransmits={conn.stats['fast_retransmits']}")
    print(f"SHA256: {sha}")
    print(f"BYTES: {len(data)}")
    return 0


def _cmd_recv(args) -> int:
    _validate_common(args)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(_parse_addr(args.bind))
    wire = RealUdpWire(sock, peer_addr=None)
    clock = RealClock()
    conn = Connection("server", wire, clock, mss=args.mss, recv_capacity=args.recv_capacity)

    print(f"causeway recv: listening on {args.bind}, writing to {args.out}")
    received = bytearray()
    last_report = 0.0

    def drain_and_report():
        nonlocal last_report
        received.extend(conn.recv())
        if conn.eof and not conn.close_requested:
            conn.close()
        now = clock.now()
        if now - last_report >= 0.5:
            last_report = now
            print(f"  received {len(received)} bytes so far", file=sys.stderr)

    try:
        _pump_realtime(conn, on_tick=drain_and_report, deadline=clock.now() + args.timeout)
    except TimeoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    with open(args.out, "wb") as f:
        f.write(bytes(received))

    sha = hashlib.sha256(bytes(received)).hexdigest()
    print(f"done. wrote {len(received)} bytes to {args.out}")
    print(f"SHA256: {sha}")
    print(f"BYTES: {len(received)}")
    return 0


def _cmd_viz(args) -> int:
    template_path = os.path.join(os.path.dirname(__file__), "viz_template.html")
    with open(template_path, "r") as f:
        template = f.read()
    with open(args.log_json, "r") as f:
        payload = f.read()
    out = template.replace("__CAUSEWAY_EVENTS_JSON__", payload)
    with open(args.out, "w") as f:
        f.write(out)
    print(f"wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="causeway", description="A from-scratch reliable transport over UDP.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="run a fast, seeded, in-process simulated transfer")
    d.add_argument("--bytes", type=int, default=200_000)
    d.add_argument("--mss", type=int, default=DEFAULT_MSS)
    d.add_argument("--loss", type=float, default=0.05)
    d.add_argument("--dup", type=float, default=0.02)
    d.add_argument("--reorder", type=float, default=0.05)
    d.add_argument("--delay-ms", type=float, default=20.0)
    d.add_argument("--jitter-ms", type=float, default=10.0)
    d.add_argument("--recv-capacity", type=int, default=64 * 1024)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--max-time", type=float, default=600.0)
    d.add_argument("--log-json", default=None, help="write a captured event log to this JSON file")
    d.set_defaults(func=_cmd_demo)

    s = sub.add_parser("send", help="send a real file over real UDP")
    s.add_argument("file")
    s.add_argument("--peer", required=True, help="host:port to send to (a real receiver, or a proxy)")
    s.add_argument("--bind", default=None, help="host:port to bind locally (default: OS-assigned)")
    s.add_argument("--mss", type=int, default=DEFAULT_MSS)
    s.add_argument("--recv-capacity", type=int, default=64 * 1024)
    s.add_argument("--timeout", type=float, default=120.0)
    s.set_defaults(func=_cmd_send)

    r = sub.add_parser("recv", help="receive a real file over real UDP")
    r.add_argument("--bind", required=True, help="host:port to listen on")
    r.add_argument("--out", required=True, help="path to write the received file to")
    r.add_argument("--mss", type=int, default=DEFAULT_MSS)
    r.add_argument("--recv-capacity", type=int, default=64 * 1024)
    r.add_argument("--timeout", type=float, default=120.0)
    r.set_defaults(func=_cmd_recv)

    v = sub.add_parser("viz", help="render a captured event log as an interactive HTML visualizer")
    v.add_argument("--log-json", required=True)
    v.add_argument("--out", required=True)
    v.set_defaults(func=_cmd_viz)

    # `proxy` is deliberately not a normal subparser: argparse's REMAINDER
    # handling is unreliable when the very next token is itself an option
    # (like `--listen`), so it's dispatched by hand in main() before
    # argparse ever sees it, and only registered here so `causeway --help`
    # lists it.
    sub.add_parser("proxy", help="run the lossy/reordering/duplicating UDP relay")

    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        if argv and argv[0] == "proxy":
            from . import proxy as proxy_mod
            return proxy_mod.main(argv[1:])
        parser = build_parser()
        args = parser.parse_args(argv)
        return args.func(args)
    except (ValueError, OSError, SimulationStalled, TimeoutError) as e:
        # Expected, "the user gave us something we can't work with" or "the
        # network/filesystem didn't cooperate" failures: a clean one-line
        # message and a non-zero exit, not a Python traceback. Anything
        # else (an AssertionError, a genuine internal bug) is deliberately
        # left to propagate with its full traceback.
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
