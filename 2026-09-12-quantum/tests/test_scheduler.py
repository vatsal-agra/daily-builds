"""Correctness tests for the CPU scheduler engine.

Where possible these check against *independently hand-computed* textbook
numbers (Silberschatz-style examples), not just internal self-consistency.
"""
from quantum.process import Burst, BurstKind, Process
from quantum.scheduler import simulate
from quantum.workload import make_processes


def _cpu_only(pid, arrival, burst, priority=0):
    return Process(pid=pid, arrival_time=arrival, bursts=[Burst(BurstKind.CPU, burst)], priority=priority)


class TestFCFS:
    def test_textbook_three_process_example(self):
        procs = [_cpu_only(1, 0, 5), _cpu_only(2, 1, 3), _cpu_only(3, 2, 8)]
        r = simulate(procs, "fcfs")
        by_pid = {m.pid: m for m in r.metrics}
        assert by_pid[1].waiting_time == 0
        assert by_pid[2].waiting_time == 4
        assert by_pid[3].waiting_time == 6
        assert r.avg_waiting == (0 + 4 + 6) / 3
        assert r.gantt == [(0, 5, 1, 0), (5, 8, 2, 0), (8, 16, 3, 0)]
        assert r.cpu_utilization == 1.0

    def test_runs_in_arrival_order_never_reorders(self):
        procs = [_cpu_only(1, 0, 2), _cpu_only(2, 0, 1), _cpu_only(3, 1, 1)]
        r = simulate(procs, "fcfs")
        pids_in_order = [seg[2] for seg in r.gantt]
        assert pids_in_order == [1, 2, 3]


class TestSJF:
    def test_shortest_job_picked_first_among_ready(self):
        # All arrive at 0: SJF must run 3, then 1, then 4, then 2 (by burst length)
        procs = [_cpu_only(1, 0, 6), _cpu_only(2, 0, 8), _cpu_only(3, 0, 2), _cpu_only(4, 0, 4)]
        r = simulate(procs, "sjf")
        order = [seg[2] for seg in r.gantt]
        assert order == [3, 4, 1, 2]


class TestSRTF:
    def test_textbook_preemptive_example(self):
        # Silberschatz OS Concepts preemptive SJF/SRTF example
        procs = [_cpu_only(1, 0, 8), _cpu_only(2, 1, 4), _cpu_only(3, 2, 9), _cpu_only(4, 3, 5)]
        r = simulate(procs, "srtf")
        assert r.avg_waiting == 6.5
        by_pid = {m.pid: m for m in r.metrics}
        assert by_pid[1].waiting_time == 9
        assert by_pid[2].waiting_time == 0
        assert by_pid[3].waiting_time == 15
        assert by_pid[4].waiting_time == 2

    def test_shorter_later_arrival_preempts_immediately(self):
        procs = [_cpu_only(1, 0, 10), _cpu_only(2, 3, 1)]
        r = simulate(procs, "srtf")
        # P2 must cut in at t=3 for exactly 1 tick, then P1 resumes
        assert (0, 3, 1, 0) in r.gantt
        assert (3, 4, 2, 0) in r.gantt


class TestRoundRobin:
    def test_textbook_quantum4_example(self):
        procs = [_cpu_only(1, 0, 24), _cpu_only(2, 0, 3), _cpu_only(3, 0, 3)]
        r = simulate(procs, "rr", quantum=4)
        assert abs(r.avg_waiting - 17 / 3) < 1e-9
        assert r.gantt == [(0, 4, 1, 0), (4, 7, 2, 0), (7, 10, 3, 0), (10, 30, 1, 0)]

    def test_quantum_one_is_maximally_fair_round_robin(self):
        procs = [_cpu_only(1, 0, 3), _cpu_only(2, 0, 3), _cpu_only(3, 0, 3)]
        r = simulate(procs, "rr", quantum=1)
        order = [seg[2] for seg in r.gantt]
        # strict round-robin: 1,2,3,1,2,3,1,2,3
        assert order == [1, 2, 3, 1, 2, 3, 1, 2, 3]


class TestPriorityAging:
    def test_lower_priority_number_runs_first(self):
        procs = [
            _cpu_only(1, 0, 5, priority=3),
            _cpu_only(2, 0, 5, priority=1),
            _cpu_only(3, 0, 5, priority=2),
        ]
        r = simulate(procs, "priority")
        order = [seg[2] for seg in r.gantt]
        assert order == [2, 3, 1]

    def test_aging_prevents_starvation(self):
        # One low-priority CPU hog plus a steady trickle of high-priority
        # short jobs arriving throughout. Without aging the hog would never
        # run; with aging it must complete in bounded time.
        procs = [_cpu_only(1, 0, 40, priority=10)]
        for i in range(2, 30):
            procs.append(_cpu_only(i, i * 3, 2, priority=0))
        r = simulate(procs, "priority", aging_rate=1.0, aging_interval=5)
        hog = next(m for m in r.metrics if m.pid == 1)
        assert hog.completion_time < 400  # finishes well before "never"


class TestMLFQ:
    def test_short_job_finishes_faster_than_long_job_sharing_top_queue(self):
        procs = [_cpu_only(1, 0, 30), _cpu_only(2, 0, 2)]
        r = simulate(procs, "mlfq", quantums=(4, 8, 16), boost_interval=None)
        by_pid = {m.pid: m for m in r.metrics}
        assert by_pid[2].completion_time < by_pid[1].completion_time

    def test_boost_prevents_starvation_of_demoted_cpu_hog(self):
        procs = [_cpu_only(1, 0, 200, priority=0)]
        for i in range(2, 40):
            procs.append(_cpu_only(i, i * 5, 3))
        with_boost = simulate(procs, "mlfq", quantums=(2, 4, 8), boost_interval=30)
        hog = next(m for m in with_boost.metrics if m.pid == 1)
        assert hog.completion_time < 2000

    def test_without_boost_hog_is_starved_far_longer(self):
        # Adversarial-review finding: disabling the periodic boost lets a
        # steady trickle of short jobs keep landing above the demoted hog
        # forever, in the same MLFQ engine used above.
        procs = [_cpu_only(1, 0, 200, priority=0)]
        for i in range(2, 200):
            procs.append(_cpu_only(i, i * 5, 3))
        no_boost = simulate(procs, "mlfq", quantums=(2, 4, 8), boost_interval=None)
        with_boost = simulate(procs, "mlfq", quantums=(2, 4, 8), boost_interval=30)
        hog_no_boost = next(m for m in no_boost.metrics if m.pid == 1)
        hog_with_boost = next(m for m in with_boost.metrics if m.pid == 1)
        assert hog_no_boost.completion_time > hog_with_boost.completion_time


class TestConservationLaws:
    """Invariants that must hold for *every* algorithm, on *every* input."""

    def _check(self, algorithm, **kwargs):
        procs = make_processes(10, seed=7)
        r = simulate(procs, algorithm, **kwargs)
        total_cpu = sum(p.total_cpu_time for p in procs)
        busy_ticks = sum(end - start for (start, end, pid, _) in r.gantt if pid != -1)
        assert busy_ticks == total_cpu, f"{algorithm}: CPU-busy ticks must equal total CPU demand"
        assert r.idle_ticks + busy_ticks == r.total_ticks
        for m in r.metrics:
            assert m.completion_time > m.arrival_time
            assert m.turnaround_time == m.completion_time - m.arrival_time
            assert m.waiting_time >= 0, f"{algorithm} pid {m.pid}: negative waiting time is a bug"
            assert m.response_time >= 0

    def test_all_algorithms_conserve_cpu_time(self):
        for algo, kwargs in [
            ("fcfs", {}), ("sjf", {}), ("srtf", {}), ("rr", {"quantum": 3}),
            ("priority", {}), ("mlfq", {}),
        ]:
            self._check(algo, **kwargs)


class TestContextSwitchCost:
    def test_overhead_is_paid_and_conserved(self):
        # Regression test: an earlier implementation discarded the
        # already-chosen next process while "paying" the switch cost,
        # so it vanished from the simulation and the run never
        # terminated. This exercises the exact scenario that hung.
        procs = [_cpu_only(1, 0, 24), _cpu_only(2, 0, 3), _cpu_only(3, 0, 3)]
        baseline = simulate(procs, "rr", quantum=4, context_switch_cost=0)
        with_cost = simulate(procs, "rr", quantum=4, context_switch_cost=2)
        total_cpu = sum(p.total_cpu_time for p in procs)
        busy = sum(end - start for (start, end, pid, _) in with_cost.gantt if pid != -1)
        assert busy == total_cpu, "context-switch overhead must never eat real CPU time"
        assert with_cost.total_ticks == baseline.total_ticks + with_cost.context_switches * 2
        assert len(with_cost.metrics) == len(procs)  # nobody vanished

    def test_zero_cost_matches_no_overhead_semantics(self):
        procs = [_cpu_only(1, 0, 10), _cpu_only(2, 0, 5)]
        a = simulate(procs, "rr", quantum=2, context_switch_cost=0)
        b = simulate(procs, "rr", quantum=2)
        assert a.as_dict() == b.as_dict()

    def test_rejects_negative_cost(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([_cpu_only(1, 0, 5)], "fcfs", context_switch_cost=-1)


class TestInputValidation:
    def test_rejects_duplicate_pids(self):
        import pytest
        procs = [_cpu_only(1, 0, 5), _cpu_only(1, 1, 3)]
        with pytest.raises(ValueError):
            simulate(procs, "fcfs")

    def test_rejects_empty_process_list(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([], "fcfs")

    def test_rejects_unknown_algorithm(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([_cpu_only(1, 0, 5)], "not_a_real_algorithm")

    def test_rejects_zero_aging_interval_instead_of_dividing_by_zero(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([_cpu_only(1, 0, 5)], "priority", aging_interval=0)

    def test_rejects_non_positive_mlfq_quantum(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([_cpu_only(1, 0, 5)], "mlfq", quantums=(4, 0, 8))

    def test_rejects_non_positive_boost_interval(self):
        import pytest
        with pytest.raises(ValueError):
            simulate([_cpu_only(1, 0, 5)], "mlfq", boost_interval=0)


class TestBursts:
    def test_process_with_io_bursts_alternates_correctly(self):
        # Regression test: an earlier version of Process had two
        # redundant fields (remaining_in_burst / io_remaining) that got
        # mixed up on the CPU->IO transition, so the I/O burst's
        # countdown was never actually initialized and it "completed"
        # instantly (0 ticks) instead of taking its real length.
        p = Process(
            pid=1, arrival_time=0,
            bursts=[Burst(BurstKind.CPU, 3), Burst(BurstKind.IO, 5), Burst(BurstKind.CPU, 2)],
        )
        r = simulate([p], "fcfs")
        m = r.metrics[0]
        # total time = cpu(3) + io(5) + cpu(2) = 10, no other process competing => waiting 0
        assert m.completion_time == 10
        assert m.waiting_time == 0
        assert m.total_cpu_time == 5
        assert m.total_io_time == 5

    def test_rejects_burst_list_starting_with_io(self):
        import pytest
        with pytest.raises(ValueError):
            Process(pid=1, arrival_time=0, bursts=[Burst(BurstKind.IO, 3)])

    def test_rejects_consecutive_same_kind_bursts(self):
        import pytest
        with pytest.raises(ValueError):
            Process(pid=1, arrival_time=0,
                     bursts=[Burst(BurstKind.CPU, 3), Burst(BurstKind.CPU, 2)])
