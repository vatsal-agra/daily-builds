import pytest

from quantum.compare import brute_force_min_faults, compare_memory, compare_schedulers
from quantum.workload import make_belady_anomaly_string, make_processes


class TestCompareSchedulers:
    def test_default_matrix_covers_all_six_algorithms(self):
        procs = make_processes(6, seed=2)
        result = compare_schedulers(procs)
        assert set(result.results.keys()) == {
            "FCFS", "SJF", "SRTF", "RoundRobin(q=4)", "PriorityAging", "MLFQ"
        }
        for r in result.results.values():
            assert r["avg_waiting"] >= 0

    def test_custom_scenarios_respected(self):
        procs = make_processes(4, seed=1)
        result = compare_schedulers(procs, scenarios={"RR2": {"algorithm": "rr", "quantum": 2}})
        assert list(result.results.keys()) == ["RR2"]


class TestCompareMemory:
    def test_detects_belady_anomaly_on_the_classic_string(self):
        result = compare_memory(make_belady_anomaly_string(), [3, 4])
        assert result.belady_anomaly["fifo"] is True
        assert result.belady_anomaly["optimal"] is False
        assert result.optimal_is_minimal is True

    def test_optimal_minimality_holds_on_random_workloads(self):
        from quantum.workload import make_reference_string
        for seed in range(5):
            ref = make_reference_string(50, seed=seed)
            result = compare_memory(ref, [2, 3, 4, 5])
            assert result.optimal_is_minimal


class TestBruteForceOracleGuardrails:
    def test_rejects_inputs_too_large_to_brute_force(self):
        big_ref = list(range(20)) * 5  # 20 distinct pages -- exponential blowup
        with pytest.raises(ValueError):
            brute_force_min_faults(big_ref, 3)

    def test_accepts_small_inputs(self):
        assert brute_force_min_faults([1, 2, 3, 1, 2, 3], 2) >= 0
