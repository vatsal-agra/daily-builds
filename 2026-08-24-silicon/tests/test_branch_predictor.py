import unittest
from pathlib import Path

from silicon.assembler import assemble
from silicon.pipeline_sim import PipelineSimulator
from silicon.branch_predictor import StaticNotTakenPredictor, TwoBitDynamicPredictor

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"


class TestBranchPredictorUnit(unittest.TestCase):
    def test_static_always_predicts_not_taken(self):
        p = StaticNotTakenPredictor()
        for pc in (0, 4, 100, 99999):
            self.assertEqual(p.predict(pc), (False, None))

    def test_dynamic_learns_a_taken_branch(self):
        p = TwoBitDynamicPredictor()
        pc = 40
        self.assertEqual(p.predict(pc), (False, None))  # cold start
        p.update(pc, True, 8)
        # counter is now "weakly taken" (2) -- predicts taken with the learned target
        self.assertEqual(p.predict(pc), (True, 8))
        p.update(pc, True, 8)  # now "strongly taken" (3)
        self.assertEqual(p.predict(pc), (True, 8))

    def test_dynamic_counter_saturates_both_directions(self):
        p = TwoBitDynamicPredictor()
        pc = 8
        for _ in range(10):
            p.update(pc, True, 100)
        idx = p._index(pc)
        self.assertEqual(p.counters[idx], 3)  # saturates at 3, doesn't overflow
        for _ in range(10):
            p.update(pc, False, 0)
        self.assertEqual(p.counters[idx], 0)  # saturates at 0, doesn't underflow


class TestDynamicBeatsStaticOnALoop(unittest.TestCase):
    def test_fibonacci_dynamic_has_fewer_mispredictions_than_static(self):
        src = (PROGRAMS_DIR / "fibonacci.s").read_text()

        def run(pred):
            sim = PipelineSimulator(assemble(src), predictor_kind=pred)
            sim.run()
            return sim.stats

        static_stats = run("static")
        dynamic_stats = run("dynamic")

        self.assertLess(dynamic_stats.mispredictions, static_stats.mispredictions)
        self.assertLess(dynamic_stats.cycles, static_stats.cycles)
        # both must still retire the exact same number of real instructions
        self.assertEqual(static_stats.instret, dynamic_stats.instret)


if __name__ == "__main__":
    unittest.main()
