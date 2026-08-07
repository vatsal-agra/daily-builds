#!/usr/bin/env python3
"""dispatch: CPU scheduling + virtual memory simulator CLI.

Subcommands:
  run       Run one CPU-scheduling algorithm over a workload, print Gantt + metrics.
  compare   Run all CPU-scheduling algorithms over the same workload, print a table.
  vm        Run one or all page-replacement algorithms over a reference string.
  deadlock  Banker's-algorithm safety check, or resource-allocation-graph cycle detection.
  report    Render the interactive HTML visualizer for a CPU workload + VM reference string.
  demo      Run a scripted walkthrough of every feature end-to-end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import scheduler, metrics, vm, deadlock, aging
from core.process import load_workload, Process
from workloads import presets


def _err(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _load_cpu_workload(args):
    """Resolve --workload as a preset name first, then as a file path."""
    if args.workload in presets.CPU_PRESETS:
        procs, preset_quantum, desc = presets.load_cpu_preset(args.workload)
        quantum = args.quantum if args.quantum is not None else preset_quantum
        return procs, quantum, desc
    path = Path(args.workload)
    if not path.exists():
        raise FileNotFoundError(
            f"{args.workload!r} is not a known preset ({presets.list_cpu_presets()}) "
            f"and no such file exists"
        )
    procs = load_workload(path)
    quantum = args.quantum if args.quantum is not None else 4
    return procs, quantum, ""


def render_gantt(schedule, width_scale=1) -> str:
    lines = []
    for pid, start, end in schedule.gantt:
        label = pid if pid is not None else "·idle·"
        bar = "█" * max(1, (end - start) * width_scale)
        lines.append(f"  [{start:>4} - {end:<4}] {label:<8} {bar}")
    return "\n".join(lines)


def render_metrics_table(rows) -> str:
    # the algorithm column is sized to the longest name actually present (e.g.
    # "Priority (non-preemptive)" is far wider than the other columns' fixed width;
    # a hardcoded width here previously misaligned every column after it) instead
    # of a hardcoded width that only happened to fit short names like "FCFS"/"SJF".
    algo_w = max(9, max(len(r["algorithm"]) for r in rows)) if rows else 9
    headers = ["algorithm", "avg_wait", "avg_turnaround", "avg_response",
               "cpu_util", "throughput", "ctx_switches", "makespan"]
    out = [" | ".join(f"{h:>{algo_w if i == 0 else 14}}" for i, h in enumerate(headers))]
    out.append("-" * len(out[0]))
    for r in rows:
        out.append(" | ".join([
            f"{r['algorithm']:>{algo_w}}",
            f"{r['avg_waiting_time']:>14.2f}",
            f"{r['avg_turnaround_time']:>14.2f}",
            f"{r['avg_response_time']:>14.2f}",
            f"{r['cpu_utilization']:>14.1%}",
            f"{r['throughput']:>14.3f}",
            f"{r['context_switches']:>14}",
            f"{r['makespan']:>14}",
        ]))
    return "\n".join(out)


def render_process_table(schedule) -> str:
    rows = sorted(schedule.results.values(), key=lambda r: r.pid)
    header = f"{'pid':>6} {'arrival':>8} {'burst':>6} {'start':>6} {'completion':>11} " \
             f"{'waiting':>8} {'turnaround':>11} {'response':>9}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(f"{r.pid:>6} {r.arrival_time:>8} {r.burst_time:>6} {r.start_time:>6} "
                      f"{r.completion_time:>11} {r.waiting_time:>8} {r.turnaround_time:>11} "
                      f"{r.response_time:>9}")
    return "\n".join(lines)


ALGO_CHOICES = ["fcfs", "sjf", "srtf", "rr", "priority", "priority-preemptive", "priority-aging", "mlfq"]


def _run_one(algo, procs, quantum, level_quanta, boost, aging_rate=1, aging_period=5):
    if algo == "fcfs":
        return scheduler.fcfs(procs)
    if algo == "sjf":
        return scheduler.sjf(procs)
    if algo == "srtf":
        return scheduler.srtf(procs)
    if algo == "rr":
        return scheduler.round_robin(procs, quantum=quantum)
    if algo == "priority":
        return scheduler.priority_scheduling(procs, preemptive=False)
    if algo == "priority-preemptive":
        return scheduler.priority_scheduling(procs, preemptive=True)
    if algo == "priority-aging":
        return aging.priority_aging(procs, aging_rate=aging_rate, aging_period=aging_period)
    if algo == "mlfq":
        return scheduler.mlfq(procs, level_quanta=level_quanta, boost_interval=boost)
    raise ValueError(f"unknown algorithm {algo!r}")


def cmd_run(args):
    procs, quantum, desc = _load_cpu_workload(args)
    level_quanta = tuple(int(x) for x in args.level_quanta.split(",")) if args.level_quanta else (4, 8, 16)
    sched = _run_one(args.algo, procs, quantum, level_quanta, args.boost, args.aging_rate, args.aging_period)
    if desc:
        print(f"# {desc}\n")
    print(f"=== {sched.algorithm} ===\n")
    print(render_gantt(sched))
    print()
    print(render_process_table(sched))
    print()
    agg = metrics.aggregate(sched)
    print(f"avg waiting={agg['avg_waiting_time']:.2f}  avg turnaround={agg['avg_turnaround_time']:.2f}  "
          f"avg response={agg['avg_response_time']:.2f}  cpu_util={agg['cpu_utilization']:.1%}  "
          f"throughput={agg['throughput']:.3f}  context_switches={agg['context_switches']}")
    return 0


def cmd_compare(args):
    procs, quantum, desc = _load_cpu_workload(args)
    rows, _runs = metrics.compare(procs, quantum=quantum)
    if desc:
        print(f"# {desc}\n")
    print(render_metrics_table(rows))
    return 0


def cmd_vm(args):
    if args.ref in presets.list_vm_presets():
        ref_string, desc = presets.load_vm_preset(args.ref)
    else:
        ref_string = [int(x) for x in args.ref.split(",")]
        desc = ""
    if desc:
        print(f"# {desc}\n")
    algos = list(vm.ALGORITHMS) if args.algo == "all" else [args.algo]
    for name in algos:
        trace = vm.ALGORITHMS[name](ref_string, args.frames)
        print(f"=== {trace.algorithm} ({args.frames} frames) ===")
        for step in trace.steps:
            frames_str = " ".join(f"{p!s:>3}" if p is not None else "  ·" for p in step.frames)
            tag = "FAULT" if step.fault else " hit "
            evict = f" (evicted {step.evicted})" if step.evicted is not None else ""
            print(f"  ref={step.page!s:>3}  [{frames_str}]  {tag}{evict}")
        print(f"  -> faults={trace.faults}  hits={trace.hits}  fault_rate={trace.fault_rate:.1%}\n")
    if args.ref == "belady" and args.algo in ("fifo", "all"):
        t3, t4 = vm.belady_anomaly_demo()
        print(f"Belady's Anomaly check: FIFO faults @3 frames={t3.faults}, @4 frames={t4.faults} "
              f"-> anomaly {'CONFIRMED' if t4.faults > t3.faults else 'NOT REPRODUCED'}")
    return 0


def cmd_deadlock(args):
    import json
    if args.mode == "bankers":
        available = json.loads(args.available)
        max_matrix = json.loads(args.max_matrix)
        allocation = json.loads(args.allocation)
        safe, sequence = deadlock.bankers_safety(available, max_matrix, allocation)
        if safe:
            print(f"SAFE state. Safe sequence: {[f'P{i}' for i in sequence]}")
        else:
            print("UNSAFE state -- no safe sequence exists.")
        if args.request_process is not None:
            request = json.loads(args.request)
            granted, reason = deadlock.bankers_request(available, max_matrix, allocation,
                                                         args.request_process, request)
            print(f"Request {request} from P{args.request_process}: "
                  f"{'GRANTED' if granted else 'DENIED'} ({reason})")
        return 0
    if args.mode == "detect":
        assignment = json.loads(args.assignment)
        request_edges = json.loads(args.request_edges) if args.request_edges else []
        cycle = deadlock.detect_cycle(assignment, request_edges)
        if cycle:
            print(f"DEADLOCK DETECTED. Cycle: {' -> '.join(cycle)}")
        else:
            print("No deadlock: resource-allocation graph is acyclic.")
        return 0
    return _err(f"unknown deadlock mode {args.mode!r}")


def cmd_generate(args):
    procs = aging.generate_poisson_workload(args.n, args.rate, seed=args.seed)
    out = {"description": f"Synthetic Poisson-arrival workload (n={args.n}, rate={args.rate}, seed={args.seed})",
           "quantum": 4,
           "processes": [{"pid": p.pid, "arrival_time": p.arrival_time, "burst_time": p.burst_time,
                           "priority": p.priority} for p in procs]}
    import json
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.output} ({args.n} processes)")
    return 0


def cmd_report(args):
    from html_report import build_report
    procs, quantum, _desc = _load_cpu_workload(args)
    ref_string, _vmdesc = presets.load_vm_preset(args.vm_ref) if args.vm_ref in presets.list_vm_presets() \
        else ([int(x) for x in args.vm_ref.split(",")], "")
    out_path = build_report(procs, quantum, ref_string, args.frames, args.output)
    print(f"wrote {out_path}")
    return 0


def cmd_demo(args):
    """A short scripted walkthrough (the exhaustive one lives in demo.sh)."""
    print(">>> dispatch demo: textbook FCFS/SJF workload")
    procs, quantum, _ = presets.load_cpu_preset("textbook_fcfs_sjf")
    for algo in ("fcfs", "sjf"):
        sched = _run_one(algo, procs, quantum, (4, 8, 16), None)
        agg = metrics.aggregate(sched)
        print(f"  {algo}: avg_waiting={agg['avg_waiting_time']:.2f}")
    print(">>> dispatch demo: Belady's Anomaly")
    t3, t4 = vm.belady_anomaly_demo()
    print(f"  FIFO faults: 3 frames={t3.faults}, 4 frames={t4.faults}")
    print(">>> dispatch demo: Banker's algorithm (classic Silberschatz example)")
    avail = [3, 3, 2]
    max_m = [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]]
    alloc = [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]]
    safe, seq = deadlock.bankers_safety(avail, max_m, alloc)
    print(f"  safe={safe} sequence={[f'P{i}' for i in seq] if seq else None}")
    print(">>> dispatch demo: RAG deadlock detection")
    cycle = deadlock.detect_cycle([("R0", "P0"), ("R1", "P1")], [("P0", "R1"), ("P1", "R0")])
    print(f"  cycle detected: {cycle}")
    print(">>> dispatch demo: priority-aging fixes starvation")
    from core.process import Process
    starve_procs = [Process("LOW", 0, 5, priority=10)]
    starve_procs += [Process(f"H{i}", i, 1, priority=1) for i in range(1, 60)]
    plain = scheduler.priority_scheduling(starve_procs, preemptive=True)
    aged = aging.priority_aging(starve_procs, aging_rate=2, aging_period=4)
    plain_low_runs = [s for s in plain.gantt if s[0] == "LOW"]
    aged_low_runs = [s for s in aged.gantt if s[0] == "LOW"]
    print(f"  plain preemptive priority: LOW runs {len(plain_low_runs)} times, longest gap "
          f"{max(b[1]-a[2] for a, b in zip(plain_low_runs, plain_low_runs[1:]))}")
    print(f"  with aging: LOW runs {len(aged_low_runs)} times, longest gap "
          f"{max(b[1]-a[2] for a, b in zip(aged_low_runs, aged_low_runs[1:]))}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="dispatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run one CPU-scheduling algorithm")
    r.add_argument("--algo", required=True, choices=ALGO_CHOICES)
    r.add_argument("--workload", required=True, help=f"preset ({presets.list_cpu_presets()}) or JSON file path")
    r.add_argument("--quantum", type=int, default=None)
    r.add_argument("--level-quanta", default=None, help="comma-separated MLFQ quanta, e.g. 4,8,16")
    r.add_argument("--boost", type=int, default=None, help="MLFQ priority-boost interval")
    r.add_argument("--aging-rate", dest="aging_rate", type=int, default=1,
                    help="priority-aging: effective-priority improvement per aging_period waited")
    r.add_argument("--aging-period", dest="aging_period", type=int, default=5,
                    help="priority-aging: time units of waiting per aging_rate step")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", help="compare all CPU-scheduling algorithms on one workload")
    c.add_argument("--workload", required=True)
    c.add_argument("--quantum", type=int, default=None)
    c.set_defaults(func=cmd_compare)

    v = sub.add_parser("vm", help="run page-replacement algorithm(s) over a reference string")
    v.add_argument("--algo", required=True, choices=list(vm.ALGORITHMS) + ["all"])
    v.add_argument("--ref", required=True, help=f"preset ({presets.list_vm_presets()}) or comma-separated ints")
    v.add_argument("--frames", type=int, required=True)
    v.set_defaults(func=cmd_vm)

    d = sub.add_parser("deadlock", help="Banker's algorithm safety/request check, or RAG cycle detection")
    d.add_argument("--mode", required=True, choices=["bankers", "detect"])
    d.add_argument("--available", default="[]", help="bankers: JSON list, e.g. [3,3,2]")
    d.add_argument("--max", dest="max_matrix", default="[]", help="bankers: JSON n x m matrix")
    d.add_argument("--allocation", default="[]", help="bankers: JSON n x m matrix")
    d.add_argument("--request-process", dest="request_process", type=int, default=None,
                    help="bankers: process index to test a resource request for")
    d.add_argument("--request", default="[]", help="bankers: JSON resource-count vector")
    d.add_argument("--assignment", default="[]",
                    help='detect: JSON [[resource,process],...] edges, e.g. [["R0","P0"],["R1","P1"]]')
    d.add_argument("--request-edges", dest="request_edges", default=None,
                    help='detect: JSON [[process,resource],...] edges')
    d.set_defaults(func=cmd_deadlock)

    gen = sub.add_parser("generate", help="generate a synthetic Poisson-arrival workload JSON file")
    gen.add_argument("--n", type=int, required=True)
    gen.add_argument("--rate", type=float, required=True, help="mean arrivals per time unit")
    gen.add_argument("--seed", type=int, default=None)
    gen.add_argument("--output", required=True)
    gen.set_defaults(func=cmd_generate)

    rep = sub.add_parser("report", help="render the interactive HTML visualizer")
    rep.add_argument("--workload", default="mixed_general")
    rep.add_argument("--quantum", type=int, default=None)
    rep.add_argument("--vm-ref", dest="vm_ref", default="belady")
    rep.add_argument("--frames", type=int, default=3)
    rep.add_argument("--output", default="dispatch_report.html")
    rep.set_defaults(func=cmd_report)

    dem = sub.add_parser("demo", help="short scripted walkthrough")
    dem.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        return _err(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
