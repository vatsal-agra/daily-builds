"""Benchmark suite: runs the bundled example programs through the pipeline
simulator and reports real, measured cycles / CPI / cache hit-rate /
speedup numbers -- not invented ones.

The "naive baseline" used for the speedup comparison is a non-pipelined
multi-cycle design that takes 5 cycles per instruction (one per stage,
never overlapped) -- the textbook number for exactly this pipeline depth,
and the number every 5-stage-pipeline course compares against.
"""

from __future__ import annotations

from pathlib import Path

from .assembler import assemble
from .cache import Cache
from .functional_sim import FunctionalSimulator
from .pipeline_sim import PipelineSimulator

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"
NAIVE_CYCLES_PER_INSTR = 5


def _load(name: str):
    path = PROGRAMS_DIR / f"{name}.s"
    return assemble(path.read_text())


def _run_one(name: str, predictor: str, use_cache: bool, mem_latency: int):
    prog = _load(name)
    icache = Cache("I$", 1024, 16, 2) if use_cache else None
    dcache = Cache("D$", 1024, 16, 2) if use_cache else None
    sim = PipelineSimulator(
        prog, predictor_kind=predictor, icache=icache, dcache=dcache,
        mem_miss_latency=mem_latency,
    )
    sim.run()

    gold_prog = _load(name)
    gold = FunctionalSimulator(gold_prog)
    gold.run()
    correct = gold.state_fingerprint() == sim.state_fingerprint()

    s = sim.stats
    naive_cycles = s.instret * NAIVE_CYCLES_PER_INSTR
    speedup = naive_cycles / s.cycles if s.cycles else 0.0
    return {
        "name": name, "predictor": predictor, "correct": correct,
        "cycles": s.cycles, "instret": s.instret, "cpi": s.cpi,
        "mispredictions": s.mispredictions, "branches": s.branches_resolved,
        "load_use_stalls": s.load_use_stall_cycles, "mem_stalls": s.mem_stall_cycles,
        "icache_hit_rate": icache.stats.hit_rate if icache else None,
        "dcache_hit_rate": dcache.stats.hit_rate if dcache else None,
        "naive_cycles": naive_cycles, "speedup": speedup,
    }


def run_benchmark_suite(programs, predictor: str, use_cache: bool, mem_latency: int) -> list:
    predictors = ["static", "dynamic"] if predictor == "both" else [predictor]
    results = []
    header = (
        f"{'program':<12}{'pred':<9}{'ok':<4}{'cycles':>9}{'instr':>8}{'CPI':>7}"
        f"{'mispred':>9}{'I$hit':>8}{'D$hit':>8}{'speedup':>9}"
    )
    print(header)
    print("-" * len(header))
    for name in programs:
        for pred in predictors:
            r = _run_one(name, pred, use_cache, mem_latency)
            results.append(r)
            i_hit = f"{r['icache_hit_rate']:.0%}" if r["icache_hit_rate"] is not None else "n/a"
            d_hit = f"{r['dcache_hit_rate']:.0%}" if r["dcache_hit_rate"] is not None else "n/a"
            ok = "OK" if r["correct"] else "FAIL"
            print(
                f"{r['name']:<12}{r['predictor']:<9}{ok:<4}{r['cycles']:>9}{r['instret']:>8}"
                f"{r['cpi']:>7.2f}{r['mispredictions']:>9}{i_hit:>8}{d_hit:>8}{r['speedup']:>8.2f}x"
            )
    if not all(r["correct"] for r in results):
        raise AssertionError("benchmark suite: at least one program's pipeline state diverged from the golden model!")
    return results
