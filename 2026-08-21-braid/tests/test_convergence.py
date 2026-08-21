import unittest

from verify.convergence import run_lossy_scenario, run_sec_scenario


class TestSECScenarios(unittest.TestCase):
    """The hard correctness gate: reorder + duplication + partition/heal
    (zero permanent loss) must ALWAYS converge. Fewer trials than
    verify/convergence.py's own 150-trial report (run separately by
    demo.sh) to keep the general test suite fast; this still runs 60
    real seeded scenarios through the real chaos network."""

    def test_sec_holds_under_chaos(self):
        failures = [r for r in (run_sec_scenario(seed) for seed in range(60)) if not r["converged"]]
        self.assertEqual(failures, [], f"{len(failures)} SEC scenarios diverged")


class TestAntiEntropyTiers(unittest.TestCase):
    def test_pure_loss_without_repair_can_diverge(self):
        results = [run_lossy_scenario(seed, use_anti_entropy=False) for seed in range(20)]
        diverged = sum(1 for r in results if not r["converged"])
        self.assertGreater(diverged, 0, "the demonstration isn't adversarial if nothing ever diverges")

    def test_anti_entropy_restores_convergence(self):
        results = [run_lossy_scenario(seed, use_anti_entropy=True) for seed in range(20)]
        diverged = [r for r in results if not r["converged"]]
        self.assertEqual(diverged, [], f"{len(diverged)} scenarios still diverged with anti-entropy on")


if __name__ == "__main__":
    unittest.main()
