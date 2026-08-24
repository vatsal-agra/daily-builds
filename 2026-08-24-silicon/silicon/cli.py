"""The `silicon` command-line tool."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import isa
from .assembler import assemble, AssemblerError
from .cache import Cache
from .functional_sim import FunctionalSimulator, SimulatorTrap
from .pipeline_sim import PipelineSimulator
from .viz import render_pipeline_html

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"


def _read_source(path: str) -> str:
    p = Path(path)
    if not p.exists():
        # allow bare names ("fibonacci") to resolve against programs/
        candidate = PROGRAMS_DIR / f"{path}.s"
        if candidate.exists():
            p = candidate
        else:
            print(f"error: no such file: {path}", file=sys.stderr)
            sys.exit(1)
    return p.read_text()


def _load(path: str):
    src = _read_source(path)
    try:
        return assemble(src)
    except AssemblerError as exc:
        print(f"assembler error: {exc}", file=sys.stderr)
        sys.exit(1)


def _make_cache(spec: str, name: str) -> Cache:
    # spec format: "size:block:assoc" e.g. "1024:16:2"
    try:
        size, block, assoc = (int(x) for x in spec.split(":"))
        return Cache(name, size, block, assoc)
    except (ValueError, TypeError) as exc:
        print(f"error: bad cache spec {spec!r} (want size:block:assoc)", file=sys.stderr)
        sys.exit(1)


def cmd_assemble(args) -> None:
    prog = _load(args.file)
    for i, word in enumerate(prog.words):
        addr = prog.base_address + 4 * i
        text = prog.text.get(i, "")
        print(f"0x{addr:08x}: 0x{word:08x}  {text}")


def cmd_run(args) -> None:
    prog = _load(args.file)
    sim = FunctionalSimulator(prog)
    try:
        steps = sim.run(max_steps=args.max_steps)
    except SimulatorTrap as exc:
        print(f"trap: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"retired {steps} instructions")
    _print_regs(sim.regs)
    if args.dump_mem:
        lo, hi = args.dump_mem
        for addr in range(lo, hi, 4):
            print(f"  mem[0x{addr:04x}] = {sim.mem.load_word(addr)}")


def cmd_pipeline(args) -> None:
    prog = _load(args.file)
    icache = _make_cache(args.icache, "I$") if args.icache else None
    dcache = _make_cache(args.dcache, "D$") if args.dcache else None
    sim = PipelineSimulator(
        prog, predictor_kind=args.predictor, icache=icache, dcache=dcache,
        mem_miss_latency=args.mem_latency, trace_cycles=args.viz is not None,
    )
    try:
        sim.run(max_cycles=args.max_cycles)
    except SimulatorTrap as exc:
        print(f"trap: {exc}", file=sys.stderr)
        sys.exit(1)

    s = sim.stats
    print(f"cycles={s.cycles} instructions={s.instret} CPI={s.cpi:.3f}")
    print(f"  load-use stalls: {s.load_use_stall_cycles} cycles")
    print(f"  mem-stall cycles: {s.mem_stall_cycles}")
    print(f"  branches resolved: {s.branches_resolved}  mispredictions: {s.mispredictions}"
          f"  ({_pct(s.mispredictions, s.branches_resolved)})")
    if icache:
        print(f"  icache: {icache.stats.hits} hits / {icache.stats.misses} misses "
              f"({icache.stats.hit_rate:.1%} hit rate)")
    if dcache:
        print(f"  dcache: {dcache.stats.hits} hits / {dcache.stats.misses} misses "
              f"({dcache.stats.hit_rate:.1%} hit rate)")
    _print_regs(sim.regs)

    if args.check:
        prog2 = _load(args.file)
        gold = FunctionalSimulator(prog2)
        gold.run(max_steps=args.max_steps)
        if gold.state_fingerprint() == sim.state_fingerprint():
            print("check: pipeline state MATCHES sequential golden model")
        else:
            print("check: MISMATCH -- pipeline diverged from golden model!", file=sys.stderr)
            sys.exit(1)

    if args.viz:
        html = render_pipeline_html(sim, title=Path(args.file).stem)
        Path(args.viz).write_text(html)
        print(f"wrote visualizer to {args.viz}")


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def _print_regs(regs) -> None:
    print("registers:")
    for row in range(0, 32, 4):
        parts = []
        for i in range(row, row + 4):
            parts.append(f"{isa.reg_name(i):>4}(x{i:<2})={regs.read(i):>10}")
        print("  " + "  ".join(parts))


BENCH_PROGRAMS = ["fibonacci", "bubblesort", "gcd", "sumarray", "matmul"]


def cmd_bench(args) -> None:
    from .bench import run_benchmark_suite
    run_benchmark_suite(
        programs=args.programs or BENCH_PROGRAMS,
        predictor=args.predictor,
        use_cache=not args.no_cache,
        mem_latency=args.mem_latency,
    )


def cmd_viz(args) -> None:
    prog = _load(args.file)
    icache = _make_cache(args.icache, "I$") if args.icache else None
    dcache = _make_cache(args.dcache, "D$") if args.dcache else None
    sim = PipelineSimulator(
        prog, predictor_kind=args.predictor, icache=icache, dcache=dcache,
        mem_miss_latency=args.mem_latency, trace_cycles=True,
    )
    sim.run(max_cycles=args.max_cycles)
    html = render_pipeline_html(sim, title=Path(args.file).stem)
    Path(args.out).write_text(html)
    print(f"wrote {args.out} ({sim.stats.cycles} cycles, {sim.stats.instret} instructions)")


def _run_cli(argv) -> None:
    # Re-enter through the real parser rather than hand-building Namespace
    # objects: that way `demo` can never drift out of sync with a
    # subcommand's actual flags/defaults again (a hand-built Namespace
    # missing a newly-added required attribute is exactly the bug this
    # caught -- see REVIEW.md).
    ns = build_parser().parse_args(argv)
    ns.func(ns)


def cmd_demo(args) -> None:
    from .bench import run_benchmark_suite
    print("=== Silicon demo ===\n")
    print("-- assemble + disassemble fibonacci.s --")
    _run_cli(["assemble", "fibonacci"])
    print("\n-- sequential golden-model run --")
    _run_cli(["run", "fibonacci"])
    print("\n-- pipelined run, cross-checked against golden model --")
    _run_cli(["pipeline", "fibonacci", "--predictor", "dynamic", "--check"])
    print("\n-- static vs dynamic branch prediction, with caches, full bench suite --")
    run_benchmark_suite(BENCH_PROGRAMS, predictor="both", use_cache=True, mem_latency=10)
    out = str(Path(__file__).resolve().parent.parent / "demo_pipeline.html")
    print(f"\n-- rendering pipeline visualizer to {out} --")
    _run_cli(["viz", "gcd", "-o", out, "--predictor", "dynamic"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="silicon", description="A from-scratch pipelined RV32I CPU simulator")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("assemble", help="assemble a .s file and print machine code")
    pa.add_argument("file")
    pa.set_defaults(func=cmd_assemble)

    pr = sub.add_parser("run", help="run a program on the sequential golden-model simulator")
    pr.add_argument("file")
    pr.add_argument("--max-steps", type=int, default=2_000_000)
    pr.add_argument("--dump-mem", type=int, nargs=2, metavar=("LO", "HI"))
    pr.set_defaults(func=cmd_run)

    pp = sub.add_parser("pipeline", help="run a program on the cycle-accurate pipeline simulator")
    pp.add_argument("file")
    pp.add_argument("--predictor", choices=["static", "dynamic"], default="dynamic")
    pp.add_argument("--icache", help="size:block:assoc, e.g. 1024:16:2")
    pp.add_argument("--dcache", help="size:block:assoc, e.g. 1024:16:2")
    pp.add_argument("--mem-latency", type=int, default=10)
    pp.add_argument("--max-cycles", type=int, default=5_000_000)
    pp.add_argument("--max-steps", type=int, default=2_000_000, help="cap for the --check golden-model run")
    pp.add_argument("--check", action="store_true", help="cross-check final state against the golden model")
    pp.add_argument("--viz", help="also render an HTML pipeline visualizer to this path")
    pp.set_defaults(func=cmd_pipeline)

    pb = sub.add_parser("bench", help="run the benchmark program suite")
    pb.add_argument("programs", nargs="*", help=f"defaults to: {' '.join(BENCH_PROGRAMS)}")
    pb.add_argument("--predictor", choices=["static", "dynamic", "both"], default="both")
    pb.add_argument("--no-cache", action="store_true")
    pb.add_argument("--mem-latency", type=int, default=10)
    pb.set_defaults(func=cmd_bench)

    pv = sub.add_parser("viz", help="render an interactive HTML pipeline visualizer")
    pv.add_argument("file")
    pv.add_argument("-o", "--out", default="pipeline.html")
    pv.add_argument("--predictor", choices=["static", "dynamic"], default="dynamic")
    pv.add_argument("--icache", help="size:block:assoc")
    pv.add_argument("--dcache", help="size:block:assoc")
    pv.add_argument("--mem-latency", type=int, default=10)
    pv.add_argument("--max-cycles", type=int, default=5_000_000)
    pv.set_defaults(func=cmd_viz)

    pd = sub.add_parser("demo", help="run the full feature walkthrough")
    pd.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SimulatorTrap as exc:
        print(f"trap: {exc}", file=sys.stderr)
        sys.exit(1)
    except AssemblerError as exc:
        print(f"assembler error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
