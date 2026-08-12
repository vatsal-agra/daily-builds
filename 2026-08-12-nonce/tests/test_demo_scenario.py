"""Runs the exact same scripted scenario `nonce demo` shows a human, and
asserts on every phase's outcome — this is the single test that proves
all 4 required features (and both stretch features) work together,
end-to-end, not just in isolation."""

import unittest

from nonce.demo_scenario import run_demo


class TestDemoScenario(unittest.TestCase):
    def test_full_scenario_passes_all_phases(self):
        stats, nodes = run_demo(verbose=False, seed=1)
        self.assertTrue(stats["converged_after_mining"])
        self.assertTrue(stats["payment_confirmed"])
        self.assertTrue(stats["double_spend_rejected"])
        self.assertTrue(stats["tamper_rejected"])
        self.assertTrue(stats["forged_signature_rejected"])
        self.assertTrue(stats["reorg_converged"])
        self.assertTrue(stats["retarget_observed"])
        self.assertTrue(stats["all_nodes_converged"])
        self.assertGreater(stats["final_height"], 20)
        self.assertGreater(stats["total_supply"], 0)

    def test_scenario_is_reproducible_with_a_different_seed(self):
        stats, _nodes = run_demo(verbose=False, seed=99)
        self.assertTrue(stats["all_nodes_converged"])


if __name__ == "__main__":
    unittest.main()
