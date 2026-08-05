"""Tests for cli.py: the simulate/sweep/scenario commands and the
argument-validation hardening from REVIEW.md #6, driven through main()
directly (fast, in-process) rather than spawning subprocesses."""

import contextlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


class TestSimulateCommand(unittest.TestCase):
    def test_simulate_converges_and_exits_zero(self):
        code, out = run_cli(["simulate", "--seed", "1", "--sites", "3", "--ops", "20"])
        self.assertEqual(code, 0)
        self.assertIn("CONVERGED", out)

    def test_simulate_verbose_prints_history(self):
        code, out = run_cli(["simulate", "--seed", "2", "--sites", "2", "--ops", "10", "-v"])
        self.assertEqual(code, 0)
        self.assertIn("insert", out.lower())

    def test_zero_ops_still_converges_trivially(self):
        code, out = run_cli(["simulate", "--ops", "0", "--sites", "3"])
        self.assertEqual(code, 0)
        self.assertIn("CONVERGED", out)


class TestSweepCommand(unittest.TestCase):
    def test_sweep_reports_full_convergence(self):
        code, out = run_cli(["sweep", "--count", "20", "--sites", "3", "--ops", "15"])
        self.assertEqual(code, 0)
        self.assertIn("20/20", out)
        self.assertIn("Strong Eventual Consistency", out)


class TestScenarioCommand(unittest.TestCase):
    def test_scenario_converges(self):
        code, out = run_cli(["scenario"])
        self.assertEqual(code, 0)
        self.assertIn("CONVERGED", out)
        self.assertIn("offline", out.lower())


class TestArgumentValidation(unittest.TestCase):
    """REVIEW.md #6: invalid args must fail cleanly (argparse exit 2 with
    a message), never with a raw traceback from deep inside the engine."""

    def _expect_argparse_error(self, argv):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                cli.main(argv)
        self.assertEqual(ctx.exception.code, 2)
        return stderr.getvalue()

    def test_sites_zero_rejected(self):
        err = self._expect_argparse_error(["simulate", "--sites", "0"])
        self.assertIn("--sites", err)

    def test_sites_one_rejected(self):
        err = self._expect_argparse_error(["simulate", "--sites", "1"])
        self.assertIn("--sites", err)

    def test_sweep_sites_one_rejected(self):
        self._expect_argparse_error(["sweep", "--sites", "1"])

    def test_negative_ops_rejected(self):
        self._expect_argparse_error(["simulate", "--ops", "-5"])

    def test_no_subcommand_shows_usage_not_a_crash(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cli.main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
