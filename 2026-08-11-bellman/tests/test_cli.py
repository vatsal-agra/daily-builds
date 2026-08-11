"""Subprocess-driven CLI smoke tests -- exercises the actual `python -m
bellman.cli ...` entry point end to end, not just the underlying
functions."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
PY = sys.executable


def run_cli(*args, timeout=60):
    return subprocess.run(
        [PY, "-m", "bellman.cli", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )


class TestCLI(unittest.TestCase):
    def test_dp_command(self):
        result = run_cli("dp", "gridworld")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("V*(start)", result.stdout)

    def test_dp_rejects_unknown_env(self):
        result = run_cli("dp", "not-a-real-env")
        self.assertNotEqual(result.returncode, 0)

    def test_tabular_command(self):
        result = run_cli("tabular", "qlearning", "gridworld", "--episodes", "200")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("greedy policy matches", result.stdout)

    def test_cliff_compare_command(self):
        result = run_cli("cliff-compare", "--episodes", "300")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Q-learning", result.stdout)
        self.assertIn("SARSA", result.stdout)

    def test_dqn_command_runs_short(self):
        result = run_cli("dqn", "--episodes", "5", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("training complete", result.stdout)

    def test_reinforce_command_runs_short(self):
        result = run_cli("reinforce", "--episodes", "5", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("training complete", result.stdout)

    def test_episodes_zero_is_rejected_cleanly(self):
        # a hostile input (0 or negative episodes) must fail fast with a
        # clean argparse error, not crash deep inside statistics.mean()
        # on an empty reward list
        result = run_cli("dqn", "--episodes", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_episodes_negative_is_rejected_cleanly(self):
        result = run_cli("tabular", "qlearning", "gridworld", "--episodes", "-5")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_command_shows_usage_error(self):
        result = subprocess.run([PY, "-m", "bellman.cli"], cwd=ROOT,
                                 capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
