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

from core import scheduler, metrics, vm
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
    headers = ["algorithm", "avg_wait", "avg_turnaround", "avg_response",
               "cpu_util", "throughput", "ctx_switches", "makespan"]
    out = [" | ".join(f"{h:>14}" for h in headers)]
    out.append("-" * len(out[0]))
    for r in rows:
        out.append(" | ".join([
            f"{r['algorithm']:>14}",
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


ALGO_CHOICES = ["fcfs", "sjf", "srtf", "rr", "priority", "priority-preemptive", "mlfq"]


def _run_one(algo, procs, quantum, level_quanta, boost):
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
    if algo == "mlfq":
        return scheduler.mlfq(procs, level_quanta=level_quanta, boost_interval=boost)
    raise ValueError(f"unknown algorithm {algo!r}")


def cmd_run(args):
    procs, quantum, desc = _load_cpu_workload(args)
    level_quanta = tuple(int(x) for x in args.level_quanta.split(",")) if args.level_quanta else (4, 8, 16)
    sched = _run_one(args.algo, procs, quantum, level_quanta, args.boost)
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
