"""The end-to-end adversarial fuzz suite: hundreds of seeded, varied-size,
varied-network-condition transfers, each checked for byte-exact SHA-256
correctness. This is what actually gives confidence in the protocol as a
whole rather than any one hand-picked scenario.
"""
import os
import unittest

from causeway.simdriver import run_transfer


class TestFuzzTransfer(unittest.TestCase):
    def test_matrix_of_sizes_and_network_conditions(self):
        sizes = [0, 1, 17, 535, 536, 537, 4096, 60_000]
        conditions = [
            dict(loss=0.0, dup=0.0, reorder=0.0),
            dict(loss=0.05, dup=0.0, reorder=0.0),
            dict(loss=0.15, dup=0.05, reorder=0.1),
            dict(loss=0.0, dup=0.2, reorder=0.0),
            dict(loss=0.0, dup=0.0, reorder=0.4),
            dict(loss=0.25, dup=0.1, reorder=0.25),
        ]
        failures = []
        for size in sizes:
            for i, cond in enumerate(conditions):
                seed = size * 1000 + i
                data = os.urandom(size)
                try:
                    r = run_transfer(data, mss=128, seed=seed, base_delay=0.01, jitter=0.005,
                                      max_virtual_time=600, **cond)
                except Exception as e:  # noqa: BLE001 - we want to collect every failure
                    failures.append((size, cond, repr(e)))
                    continue
                if not r["success"]:
                    failures.append((size, cond, "byte mismatch"))
        if failures:
            self.fail(f"{len(failures)} of {len(sizes) * len(conditions)} scenarios failed:\n" +
                      "\n".join(str(f) for f in failures))

    def test_many_random_seeds_at_moderate_loss(self):
        failures = []
        for seed in range(60):
            data = os.urandom(3000 + seed * 37)
            r = run_transfer(data, mss=200, loss=0.12, dup=0.05, reorder=0.1,
                              seed=seed, base_delay=0.015, jitter=0.01, max_virtual_time=600)
            if not r["success"]:
                failures.append(seed)
        self.assertEqual(failures, [], f"seeds that failed: {failures}")

    def test_extreme_loss_still_eventually_succeeds(self):
        # 40% one-way loss is brutal (~64% round-trip failure rate) but the
        # protocol must still make forward progress via RTO retransmission,
        # never deadlock, and never corrupt data.
        data = os.urandom(8000)
        r = run_transfer(data, mss=256, loss=0.4, seed=11, base_delay=0.01, jitter=0.005,
                          max_virtual_time=1200, max_iterations=500_000)
        self.assertTrue(r["success"])

    def test_asymmetric_tiny_and_huge_mss(self):
        data = os.urandom(20_000)
        for mss in (32, 1400):
            r = run_transfer(data, mss=mss, loss=0.05, dup=0.02, reorder=0.05, seed=mss,
                              base_delay=0.01, jitter=0.005, max_virtual_time=300)
            self.assertTrue(r["success"], f"failed at mss={mss}")

    def test_time_wait_survives_sustained_extreme_loss(self):
        # Regression test for a real orphaned-connection bug found by Phase
        # 5 verification: this exact (size, loss, seed) combination used to
        # blow through a 6000-simulated-second budget because a fixed
        # 1-second TIME_WAIT let the client go fully unresponsive before
        # the server's own retried FIN ever got another chance to be
        # acknowledged. See REVIEW.md finding #9.
        data = os.urandom(20_000)
        r = run_transfer(data, mss=536, loss=0.4, seed=4, base_delay=0.02, jitter=0.01,
                          max_virtual_time=1500, max_iterations=1_000_000)
        self.assertTrue(r["success"])

    def test_tiny_receiver_buffer_under_loss(self):
        # Forces flow control AND congestion control AND loss recovery to
        # all be exercised simultaneously.
        data = os.urandom(15_000)
        r = run_transfer(data, mss=128, loss=0.08, seed=3,
                          client_recv_capacity=4096, server_recv_capacity=512,
                          base_delay=0.01, jitter=0.005, max_virtual_time=600)
        self.assertTrue(r["success"])


if __name__ == "__main__":
    unittest.main()
