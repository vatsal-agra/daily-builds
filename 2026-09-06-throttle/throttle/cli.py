"""`throttle` command-line interface."""
from __future__ import annotations

import argparse
import sys

from .experiment import CANNED_EXPERIMENTS, run_all_named
from .viz import build_html


def _print_result(label: str, result) -> None:
    print(f"=== {label} ===")
    print(result.description)
    print(f"  duration: {result.duration_s:.2f}s   bottleneck: {result.bandwidth_Bps:,.0f} B/s "
          f"({result.utilization_pct:.1f}% utilized)   buffer: {result.buffer_bytes:,} B   "
          f"drops: {result.dropped_overflow} overflow / {result.dropped_random} random")
    if result.fairness_index is not None:
        print(f"  Jain's fairness index: {result.fairness_index:.4f}")
    for f in result.flows:
        status = f"done@{f.completion_time:.2f}s" if f.completed else "DID NOT FINISH (cap hit)"
        verified = "OK" if f.verified_correct else "MISMATCH!!"
        print(f"  - {f.name:16s} [{f.cc_name:5s}] {status:20s} "
              f"throughput={f.throughput_Bps:>10,.0f} B/s  timeouts={f.timeouts:3d}  "
              f"fast_retx={f.fast_retransmits:3d}  reassembly={verified}")
    print()


def cmd_experiment(args: argparse.Namespace) -> int:
    if args.name == "reno-vs-cubic":
        from .experiment import exp_reno_vs_cubic_high_bdp
        results = exp_reno_vs_cubic_high_bdp(seed=args.seed)
        for label, r in results.items():
            _print_result(f"reno-vs-cubic:{label}", r)
        return 0
    if args.name not in CANNED_EXPERIMENTS:
        print(f"unknown experiment {args.name!r}. choices: "
              f"{sorted(CANNED_EXPERIMENTS)} + reno-vs-cubic", file=sys.stderr)
        return 2
    result = CANNED_EXPERIMENTS[args.name](seed=args.seed)
    _print_result(args.name, result)
    if any((not f.completed) or (not f.verified_correct) for f in result.flows):
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import random
    from .network import Simulator
    from .tcp import Topology, TcpConnection

    if args.bytes < 0:
        raise ValueError(f"--bytes must be >= 0, got {args.bytes}")
    if args.cap <= 0:
        raise ValueError(f"--cap must be positive, got {args.cap}")

    rng = random.Random(args.seed)
    sim = Simulator()
    topo = Topology(sim, args.bandwidth, args.buffer, args.delay,
                     fwd_loss_prob=args.loss, fwd_reorder_prob=args.reorder, rng=rng)
    data = bytes(rng.getrandbits(8) for _ in range(args.bytes))
    conn = TcpConnection(sim, 0, topo, data, args.access_delay, cc_name=args.cc, rng=rng)
    conn.start()
    sim.run(until=args.cap)

    ok = conn.sender.done and conn.receiver.done
    verified = bytes(conn.receiver.assembled) == data[:len(conn.receiver.assembled)]
    print(f"transfer of {args.bytes:,} bytes over {args.cc} "
          f"({'completed' if ok else 'DID NOT COMPLETE (raise --cap)'})")
    if ok:
        print(f"  time: {conn.sender.done_time:.3f}s   "
              f"throughput: {args.bytes/conn.sender.done_time:,.0f} B/s")
    print(f"  timeouts: {conn.sender.timeouts}   fast retransmits: {conn.sender.fast_retransmits}   "
          f"segments sent: {conn.sender.segments_sent}")
    print(f"  link drops: {topo.fwd_link.stats.dropped_overflow} overflow / "
          f"{topo.fwd_link.stats.dropped_random} random   max queue: {topo.fwd_link.stats.max_queue_bytes} B")
    print(f"  bottleneck utilization: {topo.fwd_link.utilization(sim.now) * 100:.1f}%")
    print(f"  byte-for-byte reassembly correct: {verified}")
    return 0 if (ok and verified) else 1


def cmd_viz(args: argparse.Namespace) -> int:
    results = run_all_named()
    html_out = build_html(results)
    with open(args.out, "w") as fh:
        fh.write(html_out)
    print(f"wrote {args.out} ({len(html_out):,} bytes) covering {len(results)} experiments")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    print("Throttle demo: running every canned experiment...\n")
    ok = True
    for label, result in run_all_named():
        _print_result(label, result)
        if any((not f.completed) or (not f.verified_correct) for f in result.flows):
            ok = False
    if ok:
        print("all experiments completed with verified, correct reassembly.")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="throttle", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a single TCP flow transfer")
    run_p.add_argument("--bytes", type=int, default=1_000_000)
    run_p.add_argument("--cc", choices=["reno", "tahoe", "cubic"], default="reno")
    run_p.add_argument("--bandwidth", type=float, default=1_000_000, help="bottleneck bandwidth, bytes/sec")
    run_p.add_argument("--buffer", type=int, default=100_000, help="bottleneck buffer, bytes")
    run_p.add_argument("--delay", type=float, default=0.01, help="core one-way propagation delay, s")
    run_p.add_argument("--access-delay", type=float, default=0.02, help="flow's one-way access delay, s")
    run_p.add_argument("--loss", type=float, default=0.0, help="independent random loss probability")
    run_p.add_argument("--reorder", type=float, default=0.0, help="reordering probability")
    run_p.add_argument("--cap", type=float, default=120.0, help="simulated-time cap, s")
    run_p.add_argument("--seed", type=int, default=0)
    run_p.set_defaults(func=cmd_run)

    exp_p = sub.add_parser("experiment", help="run one canned multi-flow experiment")
    exp_p.add_argument("name", choices=sorted(list(CANNED_EXPERIMENTS) + ["reno-vs-cubic"]))
    exp_p.add_argument("--seed", type=int, default=1234)
    exp_p.set_defaults(func=cmd_experiment)

    viz_p = sub.add_parser("viz", help="run every canned experiment and write an HTML report")
    viz_p.add_argument("out", nargs="?", default="throttle_report.html")
    viz_p.set_defaults(func=cmd_viz)

    demo_p = sub.add_parser("demo", help="run every canned experiment and print a summary")
    demo_p.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as e:
        # Invalid simulation parameters (negative bandwidth, an
        # out-of-range probability, ...) raise ValueError from deep inside
        # network.py/tcp.py with a specific message -- surface that
        # message cleanly instead of a raw traceback.
        print(f"throttle: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
