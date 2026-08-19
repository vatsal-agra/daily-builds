import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

from skein import cli


def run_cli(*args):
    """Invoke the CLI in-process (fast) and capture stdout + exit code."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


class TestCliHappyPaths(unittest.TestCase):
    def test_demo_exits_zero(self):
        code, out = run_cli("demo")
        self.assertEqual(code, 0)
        self.assertIn("All demo checks passed", out)

    def test_sim_exits_zero_and_converges(self):
        code, out = run_cli("sim", "--sites", "3", "--edits", "20", "--seed", "1")
        self.assertEqual(code, 0)
        self.assertIn("CONVERGED", out)

    def test_sim_zero_edits_is_fine(self):
        code, out = run_cli("sim", "--edits", "0", "--seed", "1")
        self.assertEqual(code, 0)

    def test_chaos_exits_zero(self):
        code, out = run_cli("chaos", "--trials", "15", "--seed", "1")
        self.assertEqual(code, 0)
        self.assertIn("ALL 15 trials converged", out)

    def test_shuffle_proof_exits_zero(self):
        code, out = run_cli("shuffle-proof", "--trials", "15", "--edits", "20", "--seed", "1")
        self.assertEqual(code, 0)
        self.assertIn("converged to the identical document", out)


class TestCliInputValidation(unittest.TestCase):
    """Regression tests for REVIEW.md bug #3: invalid input used to
    crash with a raw traceback instead of a clean error."""

    def test_sites_zero_is_a_clean_error_not_a_crash(self):
        code, _ = run_cli("sim", "--sites", "0")
        self.assertEqual(code, 2)

    def test_sites_one_is_a_clean_error(self):
        code, _ = run_cli("sim", "--sites", "1")
        self.assertEqual(code, 2)

    def test_negative_edits_is_a_clean_error(self):
        code, _ = run_cli("sim", "--edits", "-1")
        self.assertEqual(code, 2)

    def test_out_of_range_drop_prob_is_a_clean_error(self):
        code, _ = run_cli("sim", "--drop", "2.5")
        self.assertEqual(code, 2)

    def test_zero_trials_is_a_clean_error(self):
        code, _ = run_cli("chaos", "--trials", "0")
        self.assertEqual(code, 2)

    def test_zero_edits_for_shuffle_proof_is_a_clean_error(self):
        code, _ = run_cli("shuffle-proof", "--edits", "0")
        self.assertEqual(code, 2)

    def test_bad_port_is_a_clean_error(self):
        code, _ = run_cli("serve", "--port", "0")
        self.assertEqual(code, 2)


class TestCliAsSubprocess(unittest.TestCase):
    """One real subprocess invocation end-to-end, to make sure `python3
    -m skein.cli` actually works from the shell (not just via the
    in-process function call the other tests use for speed)."""

    def test_module_invocation(self):
        result = subprocess.run(
            [sys.executable, "-m", "skein.cli", "chaos", "--trials", "5", "--seed", "1"],
            cwd=__file__.rsplit("/tests/", 1)[0],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALL 5 trials converged", result.stdout)


if __name__ == "__main__":
    unittest.main()
