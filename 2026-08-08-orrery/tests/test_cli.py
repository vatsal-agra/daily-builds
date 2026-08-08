"""Subprocess-driven CLI smoke tests: exercises the actual `orrery` entry
point (argument parsing, error paths, exit codes) rather than calling
Python functions directly.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, cwd=None):
    result = subprocess.run(
        [sys.executable, "-m", "orrery.cli", *args],
        cwd=cwd or PROJECT_ROOT,
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


class TestCli(unittest.TestCase):
    def test_info_lists_all_scenarios(self):
        code, out, err = run_cli("info")
        self.assertEqual(code, 0)
        for name in ("solar_system", "binary_star", "figure_eight", "plummer_cluster", "galaxy_collision"):
            self.assertIn(name, out)

    def test_run_basic_scenario(self):
        code, out, err = run_cli("run", "--scenario", "binary_star", "--steps", "50")
        self.assertEqual(code, 0)
        self.assertIn("energy:", out)

    def test_run_writes_checkpoint_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            ckpt = os.path.join(d, "c.json")
            rep = os.path.join(d, "r.html")
            code, out, err = run_cli(
                "run", "--scenario", "binary_star", "--steps", "30",
                "--out", ckpt, "--report", rep,
            )
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(ckpt))
            self.assertTrue(os.path.exists(rep))
            with open(ckpt) as f:
                data = json.load(f)
            self.assertIn("bodies", data)

    def test_run_unknown_scenario_exits_nonzero_with_usage(self):
        code, out, err = run_cli("run", "--scenario", "not_a_scenario")
        self.assertNotEqual(code, 0)
        self.assertIn("invalid choice", err)

    def test_run_negative_dt_clean_error_no_traceback(self):
        code, out, err = run_cli("run", "--scenario", "binary_star", "--dt", "-1", "--steps", "5")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_run_zero_or_negative_n_clean_error(self):
        code, out, err = run_cli("run", "--scenario", "plummer_cluster", "--n", "0", "--steps", "5")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

        code, out, err = run_cli("run", "--scenario", "plummer_cluster", "--n", "-4", "--steps", "5")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_resume_missing_checkpoint_clean_error(self):
        code, out, err = run_cli("resume", "/nonexistent/checkpoint.json", "--steps", "5")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_resume_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            ckpt = os.path.join(d, "c.json")
            code, out, err = run_cli("run", "--scenario", "binary_star", "--steps", "50", "--out", ckpt)
            self.assertEqual(code, 0)
            code, out, err = run_cli("resume", ckpt, "--steps", "50", "--dt", "0.001")
            self.assertEqual(code, 0)
            self.assertIn("Resuming", out)

    def test_bench_runs_and_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            out_path = os.path.join(d, "bench.html")
            code, out, err = run_cli("bench", "--ns", "5,10", "--thetas", "0.0,0.5", "--out", out_path)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_path))

    def test_bench_bad_ns_clean_error(self):
        code, out, err = run_cli("bench", "--ns", "not,numbers")
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)

    def test_n_flag_warns_on_fixed_body_count_scenario(self):
        code, out, err = run_cli("run", "--scenario", "solar_system", "--n", "5", "--steps", "5")
        self.assertEqual(code, 0)
        self.assertIn("note:", err)

    def test_no_args_shows_usage_and_nonzero_exit(self):
        code, out, err = run_cli()
        self.assertNotEqual(code, 0)

    def test_collisions_flag_end_to_end(self):
        code, out, err = run_cli(
            "run", "--scenario", "plummer_cluster", "--n", "15", "--seed", "3",
            "--steps", "200", "--collisions",
        )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
