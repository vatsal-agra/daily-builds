import pytest

from quantum.thrash import find_thrashing_cliff, simulate_multiprogramming, working_set_sizes


class TestWorkingSetSizes:
    def test_matches_hand_computed_windows(self):
        ref = [1, 2, 1, 3, 4, 1, 1]
        sizes = working_set_sizes(ref, window=3)
        # window of the last <=3 accesses at each point:
        # [1] [1,2] [1,2,1]->{1,2} [2,1,3]->{1,2,3} [1,3,4]->{1,3,4}
        # [3,4,1]->{1,3,4} [4,1,1]->{1,4}
        assert sizes == [1, 2, 2, 3, 3, 3, 2]

    def test_all_same_page_has_working_set_size_one(self):
        assert working_set_sizes([5, 5, 5, 5], window=2) == [1, 1, 1, 1]

    def test_all_distinct_pages_grows_up_to_window(self):
        assert working_set_sizes([1, 2, 3, 4, 5], window=3) == [1, 2, 3, 3, 3]


class TestSimulateMultiprogramming:
    def test_processes_a_fixed_amount_of_real_work(self):
        r = simulate_multiprogramming(num_frames=8, num_processes=3, ref_length=50)
        assert r.total_accesses == 150  # 3 processes x 50 accesses each, always, regardless of faults

    def test_more_frames_never_increases_fault_rate_here(self):
        # Not a formal proof (this uses *global* LRU across concurrent
        # streams, not the single-stream LRU stack property), but a real
        # sanity check: giving the whole system strictly more physical
        # memory for the same workload should not make it fault more.
        low = simulate_multiprogramming(num_frames=6, num_processes=4, ref_length=80, seed=1)
        high = simulate_multiprogramming(num_frames=20, num_processes=4, ref_length=80, seed=1)
        assert high.page_faults <= low.page_faults
        assert high.throughput >= low.throughput

    def test_rejects_bad_input(self):
        with pytest.raises(ValueError):
            simulate_multiprogramming(num_frames=0, num_processes=2)
        with pytest.raises(ValueError):
            simulate_multiprogramming(num_frames=4, num_processes=0)


class TestThrashingCliff:
    def test_throughput_rises_then_collapses(self):
        # The classic Denning curve: throughput improves as concurrency
        # first hides fault latency, then collapses once the aggregate
        # working set overruns the fixed frame pool and the single disk
        # becomes a queueing bottleneck every process is stuck behind.
        results = find_thrashing_cliff(
            num_frames=28, max_processes=16, working_set_size=4, num_pages=12,
            ref_length=150, fault_service_time=20,
        )
        throughputs = [r.throughput for r in results]
        peak = max(throughputs)
        peak_idx = throughputs.index(peak)

        assert 0 < peak_idx < len(throughputs) - 1, "peak should be an interior point, not an endpoint"
        assert throughputs[-1] < peak / 3, (
            f"expected a real collapse well past the peak, got {throughputs}"
        )
        # fault rate must climb essentially monotonically with degree of
        # multiprogramming -- more contention for the same fixed frames
        # can only make things worse, never better, in aggregate.
        fault_rates = [r.fault_rate for r in results]
        assert fault_rates[-1] > fault_rates[0] * 3

    def test_more_frames_delays_the_cliff(self):
        tight = find_thrashing_cliff(num_frames=12, max_processes=10, ref_length=100, fault_service_time=15)
        loose = find_thrashing_cliff(num_frames=40, max_processes=10, ref_length=100, fault_service_time=15)
        # at the highest degree tested, more physical memory must still
        # be doing strictly better (fewer faults, no worse throughput)
        assert loose[-1].page_faults < tight[-1].page_faults
        assert loose[-1].throughput >= tight[-1].throughput * 0.9
