"""The core correctness gate for the whole project: the pipeline
simulator's final architectural state (registers + full memory image)
must exactly match the sequential golden-model simulator's, for every
example program, under every predictor and cache configuration. Any
divergence here means a timing optimization silently changed *what* the
program computes, not just *when* -- a real bug, full stop.
"""

import unittest
from pathlib import Path

from silicon.assembler import assemble
from silicon.cache import Cache
from silicon.functional_sim import FunctionalSimulator
from silicon.pipeline_sim import PipelineSimulator

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"
PROGRAMS = ["fibonacci", "gcd", "sumarray", "bubblesort", "matmul"]

CONFIGS = [
    ("static", None, None, 1),
    ("dynamic", None, None, 1),
    ("static", (256, 8, 1), (256, 8, 1), 3),
    ("dynamic", (256, 8, 1), (256, 8, 1), 3),
    ("static", (128, 16, 4), (128, 16, 4), 15),
    ("dynamic", (128, 16, 4), (128, 16, 4), 15),
    ("dynamic", (64, 8, 2), (64, 8, 2), 2),
]


def _load(name: str) -> str:
    return (PROGRAMS_DIR / f"{name}.s").read_text()


def _make_test(program_name, predictor, icache_cfg, dcache_cfg, mem_latency):
    def test(self):
        src = _load(program_name)
        gold = FunctionalSimulator(assemble(src))
        gold.run(max_steps=2_000_000)

        icache = Cache("I$", *icache_cfg) if icache_cfg else None
        dcache = Cache("D$", *dcache_cfg) if dcache_cfg else None
        pipe = PipelineSimulator(
            assemble(src), predictor_kind=predictor, icache=icache, dcache=dcache,
            mem_miss_latency=mem_latency,
        )
        pipe.run(max_cycles=2_000_000)

        self.assertEqual(
            gold.regs.snapshot(), pipe.regs.snapshot(),
            msg=f"{program_name}/{predictor}/icache={icache_cfg}/dcache={dcache_cfg}: register file mismatch",
        )
        self.assertEqual(
            gold.mem.data, pipe.mem.data,
            msg=f"{program_name}/{predictor}/icache={icache_cfg}/dcache={dcache_cfg}: memory image mismatch",
        )
        # instret must also agree exactly -- the pipeline must retire the
        # *same number* of real instructions as the sequential model, not
        # just end up with the same final state by coincidence.
        self.assertEqual(gold.instret, pipe.instret)

    return test


class TestPipelineCrossCheck(unittest.TestCase):
    pass


for _pname in PROGRAMS:
    for _pred, _ic, _dc, _lat in CONFIGS:
        _test_name = f"test_{_pname}_{_pred}_ic{_ic}_dc{_dc}_lat{_lat}".replace(
            "None", "none").replace("(", "").replace(")", "").replace(", ", "x").replace(",", "x")
        setattr(TestPipelineCrossCheck, _test_name, _make_test(_pname, _pred, _ic, _dc, _lat))


if __name__ == "__main__":
    unittest.main()
