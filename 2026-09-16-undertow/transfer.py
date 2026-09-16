#!/usr/bin/env python3
"""Undertow file-transfer CLI and demo harness.

    transfer.py serve   <bind_port> <out_file>
    transfer.py send    <host> <port> <in_file>
    transfer.py demo    [--loss L] [--dup D] [--reorder R] [--size BYTES]
                         [--seed N] [--cc reno|vegas] [--trace-out FILE]

`demo` is the flagship end-to-end check: it spins up a real receiver and
sender talking through a real lossy NetworkSimulator in one process, and
verifies the transferred file is byte-identical (SHA-256) to what was sent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

from undertow.congestion import RenoCongestionController
from undertow.netsim import NetworkSimulator
from undertow.socket_api import UndertowSocket

try:
    from undertow.vegas import VegasCongestionController
except ImportError:  # stretch module, added in a later phase
    VegasCongestionController = None


def _cc_factory(name: str):
    if name == "reno":
        return RenoCongestionController
    if name == "vegas":
        if VegasCongestionController is None:
            raise SystemExit("vegas controller not available yet")
        return VegasCongestionController
    raise SystemExit(f"unknown congestion controller: {name}")


def cmd_serve(args: argparse.Namespace) -> None:
    sock = UndertowSocket(bind_addr=("0.0.0.0", args.bind_port))
    print(f"undertow: listening on {sock.local_address()}, waiting for a peer...", file=sys.stderr)
    conn = sock.accept(remote_addr=(args.peer_host, args.peer_port), timeout=args.timeout)
    print("undertow: connection established, receiving...", file=sys.stderr)
    data = conn.recv_all(timeout=args.timeout)
    Path(args.out_file).write_bytes(data)
    conn.close()
    sock.close()
    print(f"undertow: wrote {len(data)} bytes to {args.out_file}", file=sys.stderr)
    print(f"undertow: sha256={hashlib.sha256(data).hexdigest()}", file=sys.stderr)


def cmd_send(args: argparse.Namespace) -> None:
    data = Path(args.in_file).read_bytes()
    sock = UndertowSocket(
        congestion_controller_factory=_cc_factory(args.cc),
        bind_addr=("0.0.0.0", args.bind_port),
    )
    print(f"undertow: bound to {sock.local_address()}, connecting to {(args.host, args.port)}...", file=sys.stderr)
    conn = sock.connect((args.host, args.port), timeout=args.timeout)
    print(f"undertow: connected, sending {len(data)} bytes...", file=sys.stderr)
    t0 = time.monotonic()
    conn.send(data)
    conn.close(timeout=args.timeout)
    sock.close()
    dt = time.monotonic() - t0
    print(f"undertow: sent {len(data)} bytes in {dt:.2f}s ({len(data)/max(dt,1e-6)/1024:.1f} KB/s)", file=sys.stderr)
    print(f"undertow: sha256={hashlib.sha256(data).hexdigest()}", file=sys.stderr)


def run_transfer(
    payload: bytes,
    loss: float,
    dup: float,
    reorder: float,
    min_delay: float,
    max_delay: float,
    seed: int,
    cc_name: str,
    timeout: float = 60.0,
    bottleneck_bps: float = 0.0,
    bottleneck_buffer_bytes: int = 0,
) -> dict:
    """Runs one full send/receive over a fresh lossy simulator, in-process.

    Returns a dict with the received bytes, both endpoints' stats, the
    simulator's stats, and both connections' trace logs (for the
    visualizer / for tests to assert against).
    """
    server = UndertowSocket()
    client = UndertowSocket(congestion_controller_factory=_cc_factory(cc_name))
    saddr = server.local_address()
    caddr = client.local_address()

    sim = NetworkSimulator(
        peer_a=caddr,
        peer_b=saddr,
        loss=loss,
        dup=dup,
        reorder=reorder,
        min_delay=min_delay,
        max_delay=max_delay,
        seed=seed,
        bottleneck_bps=bottleneck_bps,
        bottleneck_buffer_bytes=bottleneck_buffer_bytes,
    )
    sim.start()

    result: dict = {}

    def run_server() -> None:
        conn = server.accept(sim.leg_b_addr, timeout=timeout)
        data = conn.recv_all(timeout=timeout)
        result["recv"] = data
        result["server_stats"] = conn.stats()
        result["server_trace"] = conn.trace_log
        conn.close()

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    conn = client.connect(sim.leg_a_addr, timeout=timeout)
    t0 = time.monotonic()
    conn.send(payload)
    conn.close(timeout=timeout)
    dt = time.monotonic() - t0
    t.join(timeout=timeout)

    sim.stop()
    client.close()
    server.close()

    return {
        "sent": payload,
        "recv": result.get("recv", b""),
        "elapsed": dt,
        "client_stats": conn.stats(),
        "server_stats": result.get("server_stats"),
        "client_trace": conn.trace_log,
        "server_trace": result.get("server_trace", []),
        "sim_stats": sim.stats,
    }


def cmd_demo(args: argparse.Namespace) -> None:
    import random

    rng = random.Random(args.seed)
    payload = bytes(rng.getrandbits(8) for _ in range(args.size))

    outcome = run_transfer(
        payload=payload,
        loss=args.loss,
        dup=args.dup,
        reorder=args.reorder,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        seed=args.seed,
        cc_name=args.cc,
        timeout=args.timeout,
        bottleneck_bps=args.bottleneck_bps,
        bottleneck_buffer_bytes=args.bottleneck_buffer,
    )

    sent_hash = hashlib.sha256(outcome["sent"]).hexdigest()
    recv_hash = hashlib.sha256(outcome["recv"]).hexdigest()
    ok = sent_hash == recv_hash and len(outcome["recv"]) == len(outcome["sent"])

    print(f"undertow demo: {args.size} bytes, loss={args.loss} dup={args.dup} reorder={args.reorder} cc={args.cc}")
    print(f"  sent {len(outcome['sent'])} bytes, received {len(outcome['recv'])} bytes")
    print(f"  sha256 match: {ok}  ({sent_hash[:12]}... vs {recv_hash[:12]}...)")
    print(f"  elapsed: {outcome['elapsed']:.2f}s  throughput: {args.size / max(outcome['elapsed'], 1e-6) / 1024:.1f} KB/s")
    print(f"  network: {outcome['sim_stats']}")
    print(f"  client final state: {outcome['client_stats']}")

    if args.trace_out:
        Path(args.trace_out).write_text(
            json.dumps(
                {
                    "params": {k: v for k, v in vars(args).items() if k != "func"},
                    "client_trace": outcome["client_trace"],
                    "server_trace": outcome["server_trace"],
                    "sim_stats": outcome["sim_stats"],
                },
                indent=None,
            )
        )
        print(f"  trace written to {args.trace_out}")

    if not ok:
        print("DEMO FAILED: transferred data does not match", file=sys.stderr)
        sys.exit(1)


def cmd_compare(args: argparse.Namespace) -> None:
    """Runs the *same* payload over the *same* real bottleneck link once
    with Reno and once with Vegas, and reports the difference -- a real
    A/B measured from two independent live transfers, not a narrated one.
    """
    import random

    rng = random.Random(args.seed)
    payload = bytes(rng.getrandbits(8) for _ in range(args.size))

    print(
        f"undertow compare: {args.size} bytes over a {args.bottleneck_bps:.0f} B/s "
        f"bottleneck with a {args.bottleneck_buffer} byte queue (loss={args.loss})"
    )
    rows = []
    for cc_name in ("reno", "vegas"):
        outcome = run_transfer(
            payload=payload,
            loss=args.loss,
            dup=args.dup,
            reorder=args.reorder,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            seed=args.seed,
            cc_name=cc_name,
            timeout=args.timeout,
            bottleneck_bps=args.bottleneck_bps,
            bottleneck_buffer_bytes=args.bottleneck_buffer,
        )
        ok = outcome["recv"] == outcome["sent"]
        retransmits = len([e for e in outcome["client_trace"] if e["event"] == "retransmit"])
        timeouts = len([e for e in outcome["client_trace"] if e["event"] == "rto_timeout"])
        throughput_kbps = args.size / max(outcome["elapsed"], 1e-6) / 1024
        rows.append((cc_name, ok, outcome["elapsed"], retransmits, timeouts, throughput_kbps))
        print(
            f"  {cc_name:>5}: ok={ok!s:<5} time={outcome['elapsed']:7.2f}s  "
            f"throughput={throughput_kbps:7.1f} KB/s  retransmits={retransmits:3d}  rto_timeouts={timeouts:3d}"
        )
        if args.trace_out:
            Path(f"{args.trace_out}.{cc_name}.json").write_text(
                json.dumps(
                    {
                        "cc": cc_name,
                        "params": {k: v for k, v in vars(args).items() if k != "func"},
                        "client_trace": outcome["client_trace"],
                        "server_trace": outcome["server_trace"],
                        "sim_stats": outcome["sim_stats"],
                    }
                )
            )

    if not all(r[1] for r in rows):
        print("COMPARE FAILED: at least one transfer did not complete correctly", file=sys.stderr)
        sys.exit(1)

    reno_t, vegas_t = rows[0][2], rows[1][2]
    if vegas_t < reno_t:
        print(f"  -> Vegas finished {reno_t / max(vegas_t, 1e-6):.1f}x faster than Reno on this bottleneck.")
    elif reno_t < vegas_t:
        print(f"  -> Reno finished {vegas_t / max(reno_t, 1e-6):.1f}x faster than Vegas on this bottleneck.")
    else:
        print("  -> both controllers finished in the same time.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="transfer.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="receive a file from a peer")
    serve.add_argument("bind_port", type=int)
    serve.add_argument("out_file")
    serve.add_argument("--peer-host", default="127.0.0.1")
    serve.add_argument("--peer-port", type=int, required=True)
    serve.add_argument("--timeout", type=float, default=30.0)
    serve.set_defaults(func=cmd_serve)

    send = sub.add_parser(
        "send",
        help="send a file to a peer",
        description="Send a file to a peer running `transfer.py serve`. Since Undertow is "
        "point-to-point (no dynamic multi-client rendezvous), the receiver's `serve --peer-port` "
        "must name this sender's own bind port, so pass --bind-port to pin it to something known.",
    )
    send.add_argument("host")
    send.add_argument("port", type=int)
    send.add_argument("in_file")
    send.add_argument("--cc", choices=["reno", "vegas"], default="reno")
    send.add_argument("--timeout", type=float, default=30.0)
    send.add_argument("--bind-port", type=int, default=0, help="local port to send from (must match the receiver's --peer-port)")
    send.set_defaults(func=cmd_send)

    demo = sub.add_parser("demo", help="run a full send/receive over a real lossy simulated network")
    demo.add_argument("--loss", type=float, default=0.05)
    demo.add_argument("--dup", type=float, default=0.02)
    demo.add_argument("--reorder", type=float, default=0.05)
    demo.add_argument("--min-delay", type=float, default=0.002)
    demo.add_argument("--max-delay", type=float, default=0.015)
    demo.add_argument("--size", type=int, default=500_000)
    demo.add_argument("--seed", type=int, default=1)
    demo.add_argument("--cc", choices=["reno", "vegas"], default="reno")
    demo.add_argument("--timeout", type=float, default=60.0)
    demo.add_argument("--trace-out", default=None)
    demo.add_argument("--bottleneck-bps", type=float, default=0.0, help="0 disables the bottleneck queue model")
    demo.add_argument("--bottleneck-buffer", type=int, default=0)
    demo.set_defaults(func=cmd_demo)

    compare = sub.add_parser(
        "compare", help="run the same transfer over the same real bottleneck with Reno and with Vegas, side by side"
    )
    compare.add_argument("--loss", type=float, default=0.0)
    compare.add_argument("--dup", type=float, default=0.0)
    compare.add_argument("--reorder", type=float, default=0.0)
    compare.add_argument("--min-delay", type=float, default=0.0)
    compare.add_argument("--max-delay", type=float, default=0.0)
    compare.add_argument("--size", type=int, default=60_000)
    compare.add_argument("--seed", type=int, default=5)
    compare.add_argument("--bottleneck-bps", type=float, default=60_000.0)
    compare.add_argument("--bottleneck-buffer", type=int, default=20_000)
    compare.add_argument("--timeout", type=float, default=60.0)
    compare.add_argument("--trace-out", default=None)
    compare.set_defaults(func=cmd_compare)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"undertow: error: file not found: {e.filename}", file=sys.stderr)
        sys.exit(1)
    except IsADirectoryError as e:
        print(f"undertow: error: expected a file, got a directory: {e.filename}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        print(f"undertow: error: {e}", file=sys.stderr)
        sys.exit(1)
    except ConnectionError as e:
        print(f"undertow: error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"undertow: error: {e.strerror or e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
