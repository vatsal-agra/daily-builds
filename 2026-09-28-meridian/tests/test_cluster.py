"""Integration tests against a real multi-process Meridian cluster: real
OS processes, real TCP sockets, real SIGKILLs. Slower and less
deterministic than test_node_unit.py's in-memory suite by nature (real
timing, real scheduling), so tests poll for convergence with a generous
timeout rather than sleeping a fixed guess."""

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian import client, node as node_mod  # noqa: E402
from meridian.node import RPCError  # noqa: E402
from tests.helpers import Cluster  # noqa: E402


class TestRingConvergence(unittest.TestCase):
    def test_ring_converges_to_exact_sorted_cycle(self):
        cluster = Cluster(n=12)
        try:
            self.assertTrue(cluster.wait_for_convergence(timeout=10),
                             "ring did not converge to the correct sorted successor/predecessor cycle")
        finally:
            cluster.shutdown()


class TestPutGetAndHopBound(unittest.TestCase):
    def test_put_get_correct_and_hops_are_logarithmic(self):
        n = 20
        cluster = Cluster(n=n)
        try:
            cluster.wait_for_convergence(timeout=10)
            start = cluster.refs[0]
            expected = {}
            rng = random.Random(42)
            for i in range(40):
                key, value = f"key{i}", f"value-{rng.randint(0, 10**9)}"
                expected[key] = value
                node_mod.put(key, value, start, client.call, m_bits=cluster.m_bits)

            max_hops_seen = 0
            for key, value in expected.items():
                got, hops = node_mod.get(key, start, client.call, m_bits=cluster.m_bits)
                self.assertEqual(got, value)
                max_hops_seen = max(max_hops_seen, len(hops))

            # O(log N) means "grows like log2(n)", not "is exactly log2(n)":
            # allow a generous constant-factor margin so this isn't flaky,
            # while still failing hard if lookups were secretly linear scans
            # (which would need up to n hops here).
            bound = math.ceil(math.log2(n)) * 3 + 3
            self.assertLessEqual(max_hops_seen, bound,
                                  f"hop count {max_hops_seen} looks linear, not O(log N), for N={n} (bound={bound})")
            self.assertLess(max_hops_seen, n,
                             "hop count reached N -- routing degenerated to a full ring scan")
        finally:
            cluster.shutdown()


class TestFaultTolerance(unittest.TestCase):
    def test_data_survives_a_real_sigkill_of_its_primary_owner(self):
        n = 15
        cluster = Cluster(n=n, r=4)
        try:
            cluster.wait_for_convergence(timeout=10)
            start = cluster.refs[0]
            expected = {f"item{i}": f"payload{i}" for i in range(30)}
            for k, v in expected.items():
                node_mod.put(k, v, start, client.call, m_bits=cluster.m_bits)

            # Kill whichever real node process is holding the most primary
            # keys, to maximize how much this test actually exercises the
            # replication path.
            best_idx, best_count = None, -1
            for idx, ref in enumerate(cluster.refs):
                snap = client.call(ref, "snapshot", {})
                if snap["num_primary_keys"] > best_count:
                    best_idx, best_count = idx, snap["num_primary_keys"]
            self.assertGreater(best_count, 0, "test setup issue: no node ended up holding any primary keys")

            cluster.kill(best_idx)

            alive_start = next(r for i, r in enumerate(cluster.refs) if i != best_idx)
            failures = []
            for k, v in expected.items():
                try:
                    got, _ = node_mod.get(k, alive_start, client.call, m_bits=cluster.m_bits)
                    if got != v:
                        failures.append(f"{k}: expected {v!r}, got {got!r}")
                except Exception as e:  # noqa: BLE001
                    failures.append(f"{k}: raised {e}")
            self.assertEqual(failures, [], f"{len(failures)}/{len(expected)} keys lost immediately after SIGKILL")
        finally:
            cluster.shutdown()

    def test_ring_self_heals_after_a_kill(self):
        cluster = Cluster(n=12, r=4)
        try:
            cluster.wait_for_convergence(timeout=10)
            cluster.kill(3)
            self.assertTrue(cluster.wait_for_convergence(timeout=10),
                             "ring did not repair itself into a correct cycle over the remaining live nodes")
        finally:
            cluster.shutdown()


class TestJoinMigratesExistingData(unittest.TestCase):
    def test_keys_survive_new_nodes_joining_an_established_ring(self):
        cluster = Cluster(n=6)
        try:
            cluster.wait_for_convergence(timeout=10)
            start = cluster.refs[0]
            expected = {f"mk{i}": f"mv{i}" for i in range(40)}
            for k, v in expected.items():
                node_mod.put(k, v, start, client.call, m_bits=cluster.m_bits)

            from tests.helpers import free_port
            import subprocess
            new_procs = []
            boot = f"{cluster.host}:{cluster.refs[0].port}"
            for _ in range(5):
                port = free_port()
                proc = subprocess.Popen(
                    [sys.executable, "-m", "meridian.node_process", "--host", cluster.host,
                     "--port", str(port), "--join", boot, "--m-bits", str(cluster.m_bits),
                     "--r", str(cluster.r), "--fast"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    cwd=str(Path(__file__).resolve().parent.parent),
                )
                new_procs.append(proc)
                import time as _time
                from meridian import hashing
                from meridian.node import NodeRef
                ref = NodeRef(id=hashing.node_id_for_addr(cluster.host, port, cluster.m_bits),
                               host=cluster.host, port=port)
                cluster._wait_ready(proc, ref)
                cluster.procs.append(proc)
                cluster.refs.append(ref)
                _time.sleep(0.05)

            cluster.wait_for_convergence(timeout=10)

            failures = []
            for k, v in expected.items():
                try:
                    got, _ = node_mod.get(k, start, client.call, m_bits=cluster.m_bits)
                    if got != v:
                        failures.append(k)
                except RPCError as e:
                    failures.append(f"{k}: {e}")
            self.assertEqual(failures, [], f"lost keys after 5 nodes joined: {failures}")
        finally:
            cluster.shutdown()


if __name__ == "__main__":
    unittest.main()
