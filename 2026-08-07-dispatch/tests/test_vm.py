import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import vm
from core.vm import VMError


class BeladyAnomalyTest(unittest.TestCase):
    """The canonical, published example (confirmed against GeeksforGeeks /
    TutorialsPoint before implementing anything): FIFO takes 9 faults at 3
    frames but 10 at 4 frames on this exact reference string."""

    def test_exact_fault_counts(self):
        trace3, trace4 = vm.belady_anomaly_demo()
        self.assertEqual(trace3.faults, 9)
        self.assertEqual(trace4.faults, 10)
        self.assertGreater(trace4.faults, trace3.faults, "Belady's Anomaly must reproduce: more frames, more faults")

    def test_lru_and_optimal_are_stack_algorithms_on_the_same_string(self):
        # stack algorithms: fault count is monotonically non-increasing as frames increase
        ref = vm.BELADY_REFERENCE_STRING
        for algo in (vm.lru, vm.optimal):
            faults_by_frames = [algo(ref, f).faults for f in range(1, 8)]
            for a, b in zip(faults_by_frames, faults_by_frames[1:]):
                self.assertGreaterEqual(a, b, f"{algo.__name__} must never take more faults with more frames")


class AlgorithmSanityTest(unittest.TestCase):
    def test_fifo_basic_trace(self):
        trace = vm.fifo([1, 2, 3, 1, 2], 2)
        self.assertEqual(trace.faults, 5)  # every distinct-from-resident ref faults with only 2 frames here
        self.assertEqual([s.fault for s in trace.steps], [True, True, True, True, True])

    def test_frames_exceeding_unique_pages_never_evicts(self):
        trace = vm.fifo([1, 2, 1, 2, 1, 2], 10)
        self.assertEqual(trace.faults, 2)  # only the first sight of 1 and of 2 fault
        for step in trace.steps:
            self.assertIsNone(step.evicted)

    def test_optimal_evicts_the_page_used_furthest_in_future(self):
        # classic optimal example: resident {1,2,3}, next ref 4 -> evict whichever of
        # 1/2/3 is used furthest in the future (or never again)
        trace = vm.optimal([1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5], 3)
        fourth_step = trace.steps[3]  # ref=4, the first eviction
        self.assertEqual(fourth_step.page, 4)
        self.assertTrue(fourth_step.fault)
        self.assertEqual(fourth_step.evicted, 3)  # 3 is never referenced again -> correct eviction


class OptimalIsLowerBoundFuzzTest(unittest.TestCase):
    def test_optimal_never_exceeded_by_any_other_algorithm(self):
        for seed in range(200):
            rnd = random.Random(seed + 7000)
            n_pages = rnd.randint(2, 6)
            length = rnd.randint(5, 40)
            ref = [rnd.randint(1, n_pages) for _ in range(length)]
            frames = rnd.randint(1, n_pages)
            opt = vm.optimal(ref, frames).faults
            for name in ("fifo", "lru", "clock"):
                faults = vm.ALGORITHMS[name](ref, frames).faults
                self.assertGreaterEqual(faults, opt,
                                         f"{name} beat optimal ({faults} < {opt}) on ref={ref} frames={frames} -- impossible")


class TraceConsistencyTest(unittest.TestCase):
    def test_hits_plus_faults_equals_length_for_all_algorithms(self):
        ref = [4, 3, 2, 1, 4, 3, 5, 4, 3, 2, 1, 5]
        for name, fn in vm.ALGORITHMS.items():
            trace = fn(ref, 3)
            self.assertEqual(trace.hits + trace.faults, len(ref))
            self.assertEqual(len(trace.steps), len(ref))
            self.assertAlmostEqual(trace.fault_rate, trace.faults / len(ref))

    def test_fault_step_pages_match_reference_string(self):
        ref = [1, 2, 3, 4, 1, 2, 5]
        for name, fn in vm.ALGORITHMS.items():
            trace = fn(ref, 3)
            self.assertEqual([s.page for s in trace.steps], ref)


class EdgeCaseTest(unittest.TestCase):
    def test_zero_or_negative_frames_rejected(self):
        for name, fn in vm.ALGORITHMS.items():
            with self.assertRaises(VMError):
                fn([1, 2, 3], 0)
            with self.assertRaises(VMError):
                fn([1, 2, 3], -1)

    def test_empty_reference_string_rejected(self):
        for name, fn in vm.ALGORITHMS.items():
            with self.assertRaises(VMError):
                fn([], 3)

    def test_single_unique_page_never_faults_after_first(self):
        for name, fn in vm.ALGORITHMS.items():
            trace = fn([7, 7, 7, 7, 7], 2)
            self.assertEqual(trace.faults, 1)


if __name__ == "__main__":
    unittest.main()
