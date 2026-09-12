"""Correctness tests for the virtual memory manager, checked against
published textbook numbers, an independent brute-force oracle, and
theoretical invariants (Optimal-minimality, the LRU stack property)."""
import itertools
import random

import pytest

from quantum.compare import brute_force_min_faults
from quantum.memory import TLB, simulate_memory
from quantum.workload import make_belady_anomaly_string, make_reference_string


class TestTextbookExamples:
    def test_silberschatz_lru_fifo_optimal_example(self):
        # OS Concepts (Silberschatz et al.) canonical example, 3 frames.
        ref = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
        assert simulate_memory(ref, 3, "fifo", tlb_capacity=0).page_faults == 15
        assert simulate_memory(ref, 3, "lru", tlb_capacity=0).page_faults == 12
        assert simulate_memory(ref, 3, "optimal", tlb_capacity=0).page_faults == 9

    def test_beladys_anomaly_reproduced_exactly(self):
        ref = make_belady_anomaly_string()
        faults_3 = simulate_memory(ref, 3, "fifo", tlb_capacity=0).page_faults
        faults_4 = simulate_memory(ref, 4, "fifo", tlb_capacity=0).page_faults
        assert faults_3 == 9
        assert faults_4 == 10
        assert faults_4 > faults_3, "Belady's Anomaly did not reproduce: more frames must be worse here"


class TestOptimalAgainstBruteForce:
    @pytest.mark.parametrize("seed", range(8))
    def test_matches_exhaustive_oracle_on_small_inputs(self, seed):
        rng = random.Random(seed)
        ref = [rng.randint(0, 3) for _ in range(9)]
        frames = rng.randint(1, 3)
        oracle = brute_force_min_faults(ref, frames)
        belady_min = simulate_memory(ref, frames, "optimal", tlb_capacity=0).page_faults
        assert belady_min == oracle, f"seed={seed} ref={ref} frames={frames}"


class TestOptimalMinimalityInvariant:
    @pytest.mark.parametrize("seed", range(15))
    def test_optimal_never_worse_than_others(self, seed):
        ref = make_reference_string(80, num_pages=10, seed=seed, working_set_size=4)
        for frames in (2, 3, 4, 5, 6):
            opt = simulate_memory(ref, frames, "optimal", tlb_capacity=0).page_faults
            for algo in ("fifo", "lru", "clock"):
                faults = simulate_memory(ref, frames, algo, tlb_capacity=0).page_faults
                assert opt <= faults, f"seed={seed} frames={frames} {algo}={faults} < optimal={opt}"


class TestLRUStackProperty:
    @pytest.mark.parametrize("seed", range(10))
    def test_resident_set_grows_monotonically_with_more_frames(self, seed):
        """LRU is a 'stack algorithm': the set of pages resident with k
        frames is always a subset of the set resident with k+1 frames, at
        every point in the reference string. This is *why* LRU never
        exhibits Belady's Anomaly, and it's a much stronger check than
        just comparing final fault counts."""
        ref = make_reference_string(60, num_pages=10, seed=seed, working_set_size=5)
        results = {
            k: simulate_memory(ref, k, "lru", tlb_capacity=0) for k in (2, 3, 4, 5, 6)
        }
        for k in (2, 3, 4, 5):
            for i in range(len(ref)):
                resident_k = {p for p in results[k].frame_timeline[i] if p is not None}
                resident_k1 = {p for p in results[k + 1].frame_timeline[i] if p is not None}
                assert resident_k <= resident_k1, (
                    f"seed={seed} tick={i}: LRU({k}) resident set {resident_k} is not a "
                    f"subset of LRU({k+1})'s {resident_k1}"
                )

    @pytest.mark.parametrize("seed", range(10))
    def test_lru_fault_count_never_increases_with_more_frames(self, seed):
        ref = make_reference_string(60, num_pages=10, seed=seed, working_set_size=5)
        faults = [simulate_memory(ref, k, "lru", tlb_capacity=0).page_faults for k in (2, 3, 4, 5, 6)]
        assert all(faults[i] >= faults[i + 1] for i in range(len(faults) - 1)), faults


class TestTLB:
    def test_repeated_access_to_same_page_hits_tlb(self):
        result = simulate_memory([1, 1, 1, 1], 2, "lru", tlb_capacity=4)
        # first access: TLB miss + page fault; next three: TLB hits
        assert result.tlb_hits == 3
        assert result.tlb_misses == 1
        assert result.page_faults == 1

    def test_tlb_eviction_on_capacity_causes_later_miss(self):
        tlb = TLB(capacity=2)
        tlb.install(1, 0)
        tlb.install(2, 1)
        tlb.install(3, 2)  # evicts vpage 1 (least recently used)
        assert tlb.lookup(1) is None
        assert tlb.misses == 1
        assert tlb.lookup(2) == 1
        assert tlb.lookup(3) == 2

    def test_tlb_invalidated_on_page_eviction(self):
        # 1 frame: 1,2 forces eviction of page 1's frame; a subsequent
        # access to page 1 must be a real page fault, not a stale TLB hit.
        result = simulate_memory([1, 2, 1], 1, "fifo", tlb_capacity=4)
        assert result.page_faults == 3
        assert not result.accesses[2].tlb_hit


class TestInputValidation:
    def test_rejects_zero_frames(self):
        with pytest.raises(ValueError):
            simulate_memory([1, 2, 3], 0, "lru")

    def test_rejects_empty_reference_string(self):
        with pytest.raises(ValueError):
            simulate_memory([], 3, "lru")

    def test_rejects_unknown_algorithm(self):
        with pytest.raises(ValueError):
            simulate_memory([1, 2], 3, "nonsense")


class TestClockApproximatesLRU:
    @pytest.mark.parametrize("seed", range(6))
    def test_clock_fault_count_between_fifo_and_optimal(self, seed):
        # Not a strict theorem, but a real sanity property: on a
        # locality-heavy workload, second-chance should never be
        # dramatically worse than plain FIFO (it strictly improves on it
        # by giving referenced pages a second chance).
        ref = make_reference_string(100, num_pages=10, seed=seed, working_set_size=4)
        for frames in (3, 4, 5):
            fifo = simulate_memory(ref, frames, "fifo", tlb_capacity=0).page_faults
            clock = simulate_memory(ref, frames, "clock", tlb_capacity=0).page_faults
            opt = simulate_memory(ref, frames, "optimal", tlb_capacity=0).page_faults
            assert opt <= clock <= fifo + 5  # generous slack; still catches real regressions
