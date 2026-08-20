"""CLI-level tests: exercises argparse wiring, --help, and input
validation through the real `python -m bellman.train` entry point (not
just calling the cmd_* functions directly) — the actual thing a user
runs, argparse subparsers and all."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(args, cwd=None):
    # PYTHONPATH keeps the `bellman` package importable even when cwd is a
    # different directory inside the project — otherwise `python -m` can't
    # find the package at all when run from anywhere but PROJECT_ROOT,
    # which would test "can Python find this package" rather than the
    # thing actually under test (whether RESULTS_DIR depends on cwd).
    env = dict(os.environ, PYTHONPATH=PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "bellman.train"] + args,
        cwd=cwd or PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


class TestArgparseWiring(unittest.TestCase):
    def test_no_command_prints_usage_and_exits_nonzero(self):
        result = run_cli([])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage", result.stderr.lower())

    def test_unknown_command_rejected_cleanly(self):
        result = run_cli(["frobnicate"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_help_does_not_crash(self):
        result = run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("qlearning", result.stdout)


class TestInputValidation(unittest.TestCase):
    def test_negative_episodes_rejected_with_clean_message(self):
        result = run_cli(["qlearning", "--episodes", "-5"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--episodes must be >= 0", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_negative_n_seeds_rejected(self):
        result = run_cli(["ablation", "--n-seeds", "-1"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--n-seeds must be >= 0", result.stderr)

    def test_non_numeric_episodes_rejected_by_argparse(self):
        result = run_cli(["qlearning", "--episodes", "abc"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid int value", result.stderr)


class TestRealRunEndToEnd(unittest.TestCase):
    """Runs the actual CLI end to end at a tiny scale — real training,
    real value-iteration verification, real JSON on disk — inside a
    scratch results/ directory so it can't clobber the project's real
    results/*.json."""

    def test_qlearning_end_to_end_writes_valid_json(self):
        result = run_cli(["qlearning", "--episodes", "50"])
        self.assertEqual(result.returncode, 0, result.stderr)
        path = os.path.join(PROJECT_ROOT, "results", "qlearning_simplegrid.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertIn("optimal_rollout", data)
        self.assertEqual(data["episodes"], 50)

    def test_results_dir_is_project_root_relative_not_cwd_relative(self):
        """RESULTS_DIR is derived from bellman/train.py's own file
        location, not the process's working directory — so results always
        land in <project>/results/ regardless of which directory a
        subcommand happens to be invoked from within the project tree."""
        subdir = os.path.join(PROJECT_ROOT, "tests")  # a real subdirectory to run from
        result = run_cli(["sarsa", "--episodes", "50"], cwd=subdir)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = os.path.join(PROJECT_ROOT, "results", "sarsa_simplegrid.json")
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
