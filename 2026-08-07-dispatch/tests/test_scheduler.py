import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.process import Process
from core import scheduler
from core.scheduler import SchedulerError
from tests.oracle import tick_oracle, rr_oracle


def random_workload(n, seed):
    rnd = random.Random(seed)
    procs = []
    t = 0
    for i in range(n):
        t += rnd.choice([0, 0, 1, 2, 3])
        procs.append(Process(pid=f"P{i}", arrival_time=t, burst_time=rnd.randint(1, 12),
                              priority=rnd.randint(0, 5)))
    return procs


class TextbookExamplesTest(unittest.TestCase):
    """Every number here is independently re-derivable by hand from the
    algorithm's definition -- see workloads/textbook_*.json for the arithmetic."""

    def test_fcfs(self):
        procs = [Process("P1", 0, 5), Process("P2", 1, 3), Process("P3", 2, 8), Process("P4", 3, 6)]
        sched = scheduler.fcfs(procs)
        completions = {r.pid: r.completion_time for r in sched.results.values()}
        self.assertEqual(completions, {"P1": 5, "P2": 8, "P3": 16, "P4": 22})
        avg_wait = sum(r.waiting_time for r in sched.results.values()) / 4
        self.assertAlmostEqual(avg_wait, 5.75)

    def test_sjf(self):
        procs = [Process("P1", 0, 5), Process("P2", 1, 3), Process("P3", 2, 8), Process("P4", 3, 6)]
        sched = scheduler.sjf(procs)
        completions = {r.pid: r.completion_time for r in sched.results.values()}
        self.assertEqual(completions, {"P1": 5, "P2": 8, "P4": 14, "P3": 22})
        avg_wait = sum(r.waiting_time for r in sched.results.values()) / 4
        self.assertAlmostEqual(avg_wait, 5.25)

    def test_srtf(self):
        procs = [Process("P1", 0, 8), Process("P2", 1, 4), Process("P3", 2, 9), Process("P4", 3, 5)]
        sched = scheduler.srtf(procs)
        completions = {r.pid: r.completion_time for r in sched.results.values()}
        self.assertEqual(completions, {"P1": 17, "P2": 5, "P3": 26, "P4": 10})
        avg_wait = sum(r.waiting_time for r in sched.results.values()) / 4
        self.assertAlmostEqual(avg_wait, 6.5)

    def test_round_robin(self):
        procs = [Process("P1", 0, 24), Process("P2", 0, 3), Process("P3", 0, 3)]
        sched = scheduler.round_robin(procs, quantum=4)
        completions = {r.pid: r.completion_time for r in sched.results.values()}
        self.assertEqual(completions, {"P1": 30, "P2": 7, "P3": 10})
        avg_wait = sum(r.waiting_time for r in sched.results.values()) / 3
        self.assertAlmostEqual(avg_wait, 17 / 3)

    def test_priority_non_preemptive(self):
        procs = [Process("P1", 0, 10, priority=3), Process("P2", 0, 1, priority=1),
                 Process("P3", 0, 2, priority=4), Process("P4", 0, 1, priority=5),
                 Process("P5", 0, 5, priority=2)]
        sched = scheduler.priority_scheduling(procs, preemptive=False)
        completions = {r.pid: r.completion_time for r in sched.results.values()}
        self.assertEqual(completions, {"P1": 16, "P2": 1, "P3": 18, "P4": 19, "P5": 6})
        avg_wait = sum(r.waiting_time for r in sched.results.values()) / 5
        self.assertAlmostEqual(avg_wait, 8.2)


class DefinitionalIdentitiesTest(unittest.TestCase):
    def test_identities_hold_for_random_workloads(self):
        for seed in range(50):
            n = random.Random(seed).randint(1, 6)
            procs = random_workload(n, seed)
            for engine_fn in [
                scheduler.fcfs, scheduler.sjf, scheduler.srtf,
                lambda p: scheduler.round_robin(p, 3),
                lambda p: scheduler.priority_scheduling(p, False),
                lambda p: scheduler.priority_scheduling(p, True),
                lambda p: scheduler.mlfq(p),
            ]:
                sched = engine_fn(procs)
                for r in sched.results.values():
                    self.assertEqual(r.turnaround_time, r.completion_time - r.arrival_time)
                    self.assertEqual(r.waiting_time, r.turnaround_time - r.burst_time)
                    self.assertGreaterEqual(r.waiting_time, 0, "waiting time must never be negative")
                    self.assertGreaterEqual(r.response_time, 0)

    def test_gantt_contiguous_and_busy_time_matches_total_burst(self):
        for seed in range(80):
            n = random.Random(seed + 1000).randint(1, 6)
            procs = random_workload(n, seed + 1000)
            for engine_fn in [
                scheduler.fcfs, scheduler.sjf, scheduler.srtf,
                lambda p: scheduler.round_robin(p, 3),
                lambda p: scheduler.priority_scheduling(p, False),
                lambda p: scheduler.priority_scheduling(p, True),
                lambda p: scheduler.mlfq(p),
            ]:
                sched = engine_fn(procs)
                g = sched.gantt
                for i in range(1, len(g)):
                    self.assertEqual(g[i][1], g[i - 1][2], "Gantt chart must have no gaps or overlaps")
                busy = sum(e - s for pid, s, e in g if pid is not None)
                self.assertEqual(busy, sum(p.burst_time for p in procs))
                self.assertEqual(busy + sched.idle_time(), sched.makespan())


class OracleCrossCheckTest(unittest.TestCase):
    """The strongest check in this suite: a completely independently
    re-implemented tick-based simulator must agree exactly with the
    event-driven engine on every process's start/completion time."""

    def test_matches_independent_tick_oracle(self):
        trials = 150
        for seed in range(trials):
            n = random.Random(seed).randint(1, 8)
            procs = random_workload(n, seed)
            for policy, engine_fn in [
                ("fcfs", scheduler.fcfs), ("sjf", scheduler.sjf), ("srtf", scheduler.srtf),
                ("priority", lambda p: scheduler.priority_scheduling(p, preemptive=False)),
                ("priority_p", lambda p: scheduler.priority_scheduling(p, preemptive=True)),
            ]:
                sched = engine_fn(procs)
                st, co = tick_oracle(procs, policy)
                for pid, r in sched.results.items():
                    self.assertEqual(r.start_time, st[pid], f"{policy} seed={seed} pid={pid} start mismatch")
                    self.assertEqual(r.completion_time, co[pid], f"{policy} seed={seed} pid={pid} completion mismatch")

    def test_round_robin_matches_oracle(self):
        for seed in range(100):
            n = random.Random(seed).randint(1, 8)
            procs = random_workload(n, seed)
            quantum = random.Random(seed + 999).randint(1, 6)
            sched = scheduler.round_robin(procs, quantum)
            st, co = rr_oracle(procs, quantum)
            for pid, r in sched.results.items():
                self.assertEqual(r.start_time, st[pid])
                self.assertEqual(r.completion_time, co[pid])


class MlfqTest(unittest.TestCase):
    def test_demotes_after_full_quantum(self):
        # two long, co-arriving processes so consecutive quantum slices for the
        # same process can't merge into one Gantt segment (a single process
        # with nothing else ready would run its slices back-to-back and
        # _append_run's cosmetic same-pid merge would erase the internal
        # level boundaries -- interleaving with a second process is what
        # makes demotion externally observable at all).
        procs = [Process("P1", 0, 100), Process("P2", 0, 100)]
        sched = scheduler.mlfq(procs, level_quanta=(2, 4, 8))
        p1_durations = [e - s for pid, s, e in sched.gantt if pid == "P1"]
        # each process's slice length must be non-decreasing (never promoted, only demoted)
        # and must climb 2 -> 4 -> 8 before settling at the floor quantum of 8
        self.assertEqual(p1_durations[:3], [2, 4, 8])
        # every slice at the floor level is the full quantum (8) except possibly
        # the very last one, which is however much burst remained at that point
        self.assertTrue(all(d == 8 for d in p1_durations[3:-1]))
        self.assertLessEqual(p1_durations[-1], 8)

    def test_boost_reduces_max_wait_for_starved_process(self):
        procs = [Process("LOW", 0, 10)]
        procs += [Process(f"S{i}", i, 1) for i in range(1, 40)]
        no_boost = scheduler.mlfq(procs, level_quanta=(2, 4, 8))
        with_boost = scheduler.mlfq(procs, level_quanta=(2, 4, 8), boost_interval=10)

        def max_gap(sched, pid):
            segs = [s for s in sched.gantt if s[0] == pid]
            if len(segs) < 2:
                return 0
            return max(b[1] - a[2] for a, b in zip(segs, segs[1:]))

        self.assertLessEqual(max_gap(with_boost, "LOW"), max_gap(no_boost, "LOW"))

    def test_boost_interval_zero_or_negative_rejected(self):
        procs = [Process("P1", 0, 5), Process("P2", 1, 3)]
        with self.assertRaises(SchedulerError):
            scheduler.mlfq(procs, boost_interval=0)
        with self.assertRaises(SchedulerError):
            scheduler.mlfq(procs, boost_interval=-3)

    def test_zero_level_quanta_rejected(self):
        procs = [Process("P1", 0, 5)]
        with self.assertRaises(SchedulerError):
            scheduler.mlfq(procs, level_quanta=(4, 0, 8))
        with self.assertRaises(SchedulerError):
            scheduler.mlfq(procs, level_quanta=())


class EdgeCaseTest(unittest.TestCase):
    def test_empty_workload_rejected(self):
        with self.assertRaises(SchedulerError):
            scheduler.fcfs([])

    def test_duplicate_pid_rejected(self):
        with self.assertRaises(SchedulerError):
            scheduler.fcfs([Process("P1", 0, 3), Process("P1", 1, 2)])

    def test_zero_or_negative_quantum_rejected(self):
        procs = [Process("P1", 0, 3)]
        with self.assertRaises(SchedulerError):
            scheduler.round_robin(procs, 0)
        with self.assertRaises(SchedulerError):
            scheduler.round_robin(procs, -1)

    def test_negative_burst_or_arrival_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            Process("P1", 0, -5)
        with self.assertRaises(ValueError):
            Process("P1", -1, 5)
        with self.assertRaises(ValueError):
            Process("P1", 0, 0)

    def test_single_process(self):
        p = [Process("P1", 0, 5)]
        for fn in [scheduler.fcfs, scheduler.sjf, scheduler.srtf,
                   lambda p: scheduler.round_robin(p, 4),
                   lambda p: scheduler.priority_scheduling(p),
                   lambda p: scheduler.mlfq(p)]:
            sched = fn(p)
            r = sched.results["P1"]
            self.assertEqual((r.start_time, r.completion_time), (0, 5))

    def test_oversized_rr_quantum_degenerates_to_fcfs_like_order(self):
        procs = [Process("P1", 0, 3), Process("P2", 0, 2)]
        sched = scheduler.round_robin(procs, 100)
        self.assertEqual(sched.gantt, [("P1", 0, 3), ("P2", 3, 5)])


if __name__ == "__main__":
    unittest.main()
