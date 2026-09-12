"""Command-line entry point: `python -m quantum.cli <subcommand> ...`"""
from __future__ import annotations

import argparse
import json
import sys

from .compare import brute_force_min_faults, compare_memory, compare_schedulers
from .memory import simulate_memory
from .process import Process
from .scheduler import POLICIES, simulate
from .viz_export import export_to_file
from .workload import make_belady_anomaly_string, make_processes, make_reference_string


def _print_schedule_table(result) -> None:
    print(f"\n=== {result.algorithm} ===")
    print(f"{'PID':>4} {'Name':<8} {'Arrival':>8} {'Complete':>9} {'Turnaround':>11} "
          f"{'Waiting':>8} {'Response':>9}")
    for m in result.metrics:
        print(f"{m.pid:>4} {m.name:<8} {m.arrival_time:>8} {m.completion_time:>9} "
              f"{m.turnaround_time:>11} {m.waiting_time:>8} {m.response_time:>9}")
    print(f"avg waiting={result.avg_waiting:.2f}  avg turnaround={result.avg_turnaround:.2f}  "
          f"avg response={result.avg_response:.2f}  cpu_util={result.cpu_utilization:.1%}  "
          f"context_switches={result.context_switches}  ticks={result.total_ticks}")


def cmd_schedule(args: argparse.Namespace) -> None:
    processes = make_processes(args.n, seed=args.seed)
    kwargs = {}
    if args.algo == "rr":
        kwargs["quantum"] = args.quantum
    if args.algo == "mlfq":
        kwargs["boost_interval"] = args.boost_interval
    if args.context_switch_cost:
        kwargs["context_switch_cost"] = args.context_switch_cost
    result = simulate(processes, args.algo, **kwargs)
    _print_schedule_table(result)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result.as_dict(), f, indent=2)
        print(f"wrote {args.out}")


def cmd_memory(args: argparse.Namespace) -> None:
    if args.belady:
        ref = make_belady_anomaly_string()
    else:
        ref = make_reference_string(args.length, num_pages=args.pages, seed=args.seed,
                                     working_set_size=args.working_set)
    result = simulate_memory(ref, args.frames, args.algo, tlb_capacity=args.tlb)
    print(f"\n=== {result.algorithm}, {args.frames} frames ===")
    print(f"reference string ({len(ref)} accesses): {ref}")
    print(f"page faults: {result.page_faults} ({result.fault_rate:.1%})")
    print(f"TLB hit rate: {result.tlb_hit_rate:.1%}")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result.as_dict(), f, indent=2)
        print(f"wrote {args.out}")


def cmd_compare(args: argparse.Namespace) -> None:
    processes = make_processes(args.n, seed=args.seed)
    sched_cmp = compare_schedulers(processes)
    print("\n=== Scheduler comparison ===")
    print(f"{'Algorithm':<18}{'AvgWait':>10}{'AvgTurn':>10}{'AvgResp':>10}"
          f"{'CPU%':>8}{'Switches':>10}")
    for label, r in sched_cmp.results.items():
        print(f"{label:<18}{r['avg_waiting']:>10.2f}{r['avg_turnaround']:>10.2f}"
              f"{r['avg_response']:>10.2f}{r['cpu_utilization']*100:>7.1f}%{r['context_switches']:>10}")

    frame_counts = [int(x) for x in args.frames.split(",")]
    ref = make_reference_string(args.length, num_pages=args.pages, seed=args.seed,
                                 working_set_size=args.working_set)
    mem_cmp = compare_memory(ref, frame_counts)
    print("\n=== Memory comparison (locality workload) ===")
    print(f"{'Frames':<8}" + "".join(f"{a.upper():>10}" for a in ("fifo", "lru", "clock", "optimal")))
    for frames in frame_counts:
        row = mem_cmp.by_frames[frames]
        print(f"{frames:<8}" + "".join(f"{row[a]['page_faults']:>10}" for a in ("fifo", "lru", "clock", "optimal")))
    print(f"Optimal-minimality holds: {mem_cmp.optimal_is_minimal}")
    print(f"Belady's Anomaly detected: {mem_cmp.belady_anomaly}")

    if args.out:
        payload = {"scheduler": sched_cmp.as_dict(), "memory": mem_cmp.as_dict()}
        with open(args.out, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"wrote {args.out}")


def cmd_export(args: argparse.Namespace) -> None:
    export_to_file(args.out, seed=args.seed, n_processes=args.n, ref_length=args.length)
    print(f"wrote {args.out}")


def cmd_oracle(args: argparse.Namespace) -> None:
    ref = [int(x) for x in args.ref.split(",")]
    bruteforce = brute_force_min_faults(ref, args.frames)
    optimal = simulate_memory(ref, args.frames, "optimal", tlb_capacity=0).page_faults
    print(f"brute-force minimum: {bruteforce}")
    print(f"Belady's MIN (Optimal): {optimal}")
    print("MATCH" if bruteforce == optimal else "MISMATCH -- bug!")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quantum", description="OS scheduler + VM simulator")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("schedule", help="run one scheduling algorithm")
    sp.add_argument("--algo", choices=sorted(POLICIES), default="fcfs")
    sp.add_argument("--n", type=int, default=6)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--quantum", type=int, default=4)
    sp.add_argument("--boost-interval", type=int, default=50)
    sp.add_argument("--context-switch-cost", type=int, default=0)
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_schedule)

    mp = sub.add_parser("memory", help="run one page-replacement algorithm")
    mp.add_argument("--algo", choices=["fifo", "lru", "clock", "optimal"], default="lru")
    mp.add_argument("--frames", type=int, default=4)
    mp.add_argument("--length", type=int, default=40)
    mp.add_argument("--pages", type=int, default=12)
    mp.add_argument("--working-set", type=int, default=4)
    mp.add_argument("--seed", type=int, default=0)
    mp.add_argument("--tlb", type=int, default=4)
    mp.add_argument("--belady", action="store_true", help="use the classic Belady's Anomaly string")
    mp.add_argument("--out")
    mp.set_defaults(func=cmd_memory)

    cp = sub.add_parser("compare", help="run the full algorithm matrix")
    cp.add_argument("--n", type=int, default=8)
    cp.add_argument("--seed", type=int, default=0)
    cp.add_argument("--frames", default="2,3,4,5,6")
    cp.add_argument("--length", type=int, default=60)
    cp.add_argument("--pages", type=int, default=12)
    cp.add_argument("--working-set", type=int, default=4)
    cp.add_argument("--out")
    cp.set_defaults(func=cmd_compare)

    ep = sub.add_parser("export", help="export the full visualizer JSON")
    ep.add_argument("--out", default="visualizer/data.json")
    ep.add_argument("--seed", type=int, default=42)
    ep.add_argument("--n", type=int, default=8)
    ep.add_argument("--length", type=int, default=60)
    ep.set_defaults(func=cmd_export)

    op = sub.add_parser("oracle", help="check Belady's MIN against a brute-force oracle")
    op.add_argument("--ref", default="1,2,3,1,4,2,3,4,1")
    op.add_argument("--frames", type=int, default=3)
    op.set_defaults(func=cmd_oracle)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as e:  # surface real errors clearly instead of a traceback wall
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
