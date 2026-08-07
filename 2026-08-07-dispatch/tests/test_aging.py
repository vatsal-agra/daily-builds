import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.process import Process
from core import scheduler, aging
from core.scheduler import SchedulerError


class StarvationFixTest(unittest.TestCase):
    """The central claim of this feature: aging measurably bounds the worst-case
    wait a plain preemptive-priority process can suffer. Proven by construction
    and by diffing actual Gantt segments, not asserted from theory alone."""

    def _starve_scenario(self):
        procs = [Process("LOW", 0, 5, priority=10)]
        procs += [Process(f"H{i}", i, 1, priority=1) for i in range(1, 60)]
        return procs

    def _max_gap(self, sched, pid):
        segs = [s for s in sched.gantt if s[0] == pid]
        if len(segs) < 2:
            return 0
        return max(b[1] - a[2] for a, b in zip(segs, segs[1:]))

    def test_plain_preemptive_priority_actually_starves_in_this_scenario(self):
        procs = self._starve_scenario()
        plain = scheduler.priority_scheduling(procs, preemptive=True)
        # after its first (forced, since it's the only ready process at t=0) run,
        # LOW must not run again until literally everything else has finished
        self.assertGreater(self._max_gap(plain, "LOW"), 50)

    def test_aging_bounds_the_max_wait_far_below_the_plain_case(self):
        procs = self._starve_scenario()
        plain = scheduler.priority_scheduling(procs, preemptive=True)
        aged = aging.priority_aging(procs, aging_rate=2, aging_period=4)
        plain_gap = self._max_gap(plain, "LOW")
        aged_gap = self._max_gap(aged, "LOW")
        self.assertLess(aged_gap, plain_gap)
        self.assertLessEqual(aged_gap, 25)  # derivable: gap to close priority 10->1 at rate 2/4 ticks is 18-20

    def test_aging_disabled_rate_zero_behaves_like_plain_priority_at_the_extremes(self):
        # aging_rate=0 means effective priority never improves -- LOW should starve
        # exactly as badly as plain preemptive priority scheduling
        procs = self._starve_scenario()
        aged_no_rate = aging.priority_aging(procs, aging_rate=0, aging_period=4)
        self.assertGreater(self._max_gap(aged_no_rate, "LOW"), 50)


class AgingInvariantFuzzTest(unittest.TestCase):
    def test_definitional_identities_and_gantt_integrity(self):
        for seed in range(100):
            rnd = random.Random(seed)
            n = rnd.randint(1, 8)
            procs = []
            t = 0
            for i in range(n):
                t += rnd.choice([0, 0, 1, 2])
                procs.append(Process(f"P{i}", t, rnd.randint(1, 12), priority=rnd.randint(0, 5)))
            sched = aging.priority_aging(procs, aging_rate=rnd.randint(1, 3), aging_period=rnd.randint(1, 6))
            g = sched.gantt
            for i in range(1, len(g)):
                self.assertEqual(g[i][1], g[i - 1][2])
            busy = sum(e - s for pid, s, e in g if pid is not None)
            self.assertEqual(busy, sum(p.burst_time for p in procs))
            for r in sched.results.values():
                self.assertGreaterEqual(r.waiting_time, 0)


class AgingEdgeCaseTest(unittest.TestCase):
    def test_zero_or_negative_aging_period_rejected(self):
        procs = [Process("P1", 0, 5)]
        with self.assertRaises(SchedulerError):
            aging.priority_aging(procs, aging_period=0)
        with self.assertRaises(SchedulerError):
            aging.priority_aging(procs, aging_period=-2)

    def test_negative_aging_rate_rejected(self):
        procs = [Process("P1", 0, 5)]
        with self.assertRaises(SchedulerError):
            aging.priority_aging(procs, aging_rate=-1)


class WorkloadGeneratorTest(unittest.TestCase):
    def test_deterministic_given_same_seed(self):
        a = aging.generate_poisson_workload(10, 0.3, seed=42)
        b = aging.generate_poisson_workload(10, 0.3, seed=42)
        self.assertEqual([(p.pid, p.arrival_time, p.burst_time, p.priority) for p in a],
                          [(p.pid, p.arrival_time, p.burst_time, p.priority) for p in b])

    def test_different_seeds_differ(self):
        a = aging.generate_poisson_workload(10, 0.3, seed=1)
        b = aging.generate_poisson_workload(10, 0.3, seed=2)
        self.assertNotEqual([p.arrival_time for p in a], [p.arrival_time for p in b])

    def test_arrivals_non_decreasing(self):
        procs = aging.generate_poisson_workload(30, 0.5, seed=7)
        arrivals = [p.arrival_time for p in procs]
        self.assertEqual(arrivals, sorted(arrivals))

    def test_generated_workload_is_schedulable(self):
        procs = aging.generate_poisson_workload(15, 0.4, seed=3)
        sched = scheduler.fcfs(procs)
        self.assertEqual(len(sched.results), 15)

    def test_invalid_params_rejected(self):
        with self.assertRaises(SchedulerError):
            aging.generate_poisson_workload(0, 0.3)
        with self.assertRaises(SchedulerError):
            aging.generate_poisson_workload(5, 0)
        with self.assertRaises(SchedulerError):
            aging.generate_poisson_workload(5, -1)


if __name__ == "__main__":
    unittest.main()
