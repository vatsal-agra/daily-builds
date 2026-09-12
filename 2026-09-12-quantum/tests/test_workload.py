import pytest

from quantum.workload import make_belady_anomaly_string, make_processes, make_reference_string


class TestMakeProcesses:
    def test_deterministic_for_same_seed(self):
        a = make_processes(10, seed=5)
        b = make_processes(10, seed=5)
        assert [(p.pid, p.arrival_time, [(bb.kind, bb.length) for bb in p.bursts]) for p in a] == \
               [(p.pid, p.arrival_time, [(bb.kind, bb.length) for bb in p.bursts]) for p in b]

    def test_different_seeds_differ(self):
        a = make_processes(10, seed=1)
        b = make_processes(10, seed=2)
        assert [p.arrival_time for p in a] != [p.arrival_time for p in b]

    def test_produces_a_mix_of_cpu_and_io_bound_processes(self):
        procs = make_processes(30, seed=3)
        num_bursts = [len(p.bursts) for p in procs]
        assert min(num_bursts) != max(num_bursts), "workload should not be all-identical processes"

    def test_rejects_non_positive_n(self):
        with pytest.raises(ValueError):
            make_processes(0)


class TestReferenceString:
    def test_deterministic_for_same_seed(self):
        a = make_reference_string(50, seed=9)
        b = make_reference_string(50, seed=9)
        assert a == b

    def test_exhibits_locality_not_uniform_noise(self):
        # A working set of 4 pages should dominate short windows; a
        # uniform-random generator over num_pages=12 would not do this.
        ref = make_reference_string(200, num_pages=12, seed=1, working_set_size=4, jump_probability=0.02)
        window = ref[:20]
        assert len(set(window)) <= 6, f"expected a small working set, got {set(window)}"

    def test_rejects_working_set_larger_than_num_pages(self):
        with pytest.raises(ValueError):
            make_reference_string(10, num_pages=4, working_set_size=5)

    def test_rejects_non_positive_num_pages_or_working_set(self):
        with pytest.raises(ValueError):
            make_reference_string(10, num_pages=0)
        with pytest.raises(ValueError):
            make_reference_string(10, num_pages=4, working_set_size=0)


class TestBeladyString:
    def test_is_the_documented_classic_string(self):
        assert make_belady_anomaly_string() == [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
