import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "axiom.cli", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)


class TestCLIHappyPaths(unittest.TestCase):
    def test_simplify(self):
        r = run_cli("simplify", "2*x+3*x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "5*x")

    def test_diff(self):
        r = run_cli("diff", "x^2", "--var", "x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "2*x")

    def test_diff_with_steps(self):
        r = run_cli("diff", "x^2*sin(x)", "--steps")
        self.assertEqual(r.returncode, 0)
        self.assertIn("power rule", r.stdout)
        self.assertIn("product rule", r.stdout)

    def test_solve(self):
        r = run_cli("solve", "x^2 - 4")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(set(r.stdout.split()), {"2", "-2"})

    def test_factor(self):
        r = run_cli("factor", "x^2-1")
        self.assertEqual(r.returncode, 0)
        self.assertIn("x - 1", r.stdout)
        self.assertIn("x + 1", r.stdout)

    def test_expand(self):
        r = run_cli("expand", "(x+1)^2")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "x^2 + 2*x + 1")

    def test_integrate(self):
        r = run_cli("integrate", "x^2")
        self.assertEqual(r.returncode, 0)
        self.assertIn("+ C", r.stdout)

    def test_eval(self):
        r = run_cli("eval", "x^2+1", "--bind", "x=3")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "10.0")

    def test_latex(self):
        r = run_cli("latex", "x^2")
        self.assertEqual(r.returncode, 0)
        self.assertIn("^", r.stdout)

    def test_demo_runs_clean(self):
        r = run_cli("demo")
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("Demo complete", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


class TestCLIErrorPaths(unittest.TestCase):
    def _assert_clean_error(self, *args):
        r = run_cli(*args)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stdout + r.stderr,
                          msg=f"raw traceback leaked for {args}: {r.stderr}")
        self.assertIn("error", (r.stdout + r.stderr).lower())

    def test_malformed_expression(self):
        self._assert_clean_error("simplify", "x+")

    def test_unknown_function(self):
        self._assert_clean_error("diff", "foo(x)")

    def test_ambiguous_variable(self):
        self._assert_clean_error("factor", "x*y")

    def test_bind_non_numeric(self):
        self._assert_clean_error("eval", "x+1", "--bind", "x=notanumber")

    def test_bind_missing_equals(self):
        self._assert_clean_error("eval", "x+1", "--bind", "xyz")

    def test_unsupported_integral(self):
        self._assert_clean_error("integrate", "exp(x^2)")

    def test_deep_nesting(self):
        self._assert_clean_error("simplify", "(" * 500 + "x" + ")" * 500)

    def test_no_command_shows_usage_not_crash(self):
        r = run_cli()
        self.assertNotIn("Traceback", r.stdout + r.stderr)


class TestREPL(unittest.TestCase):
    def test_repl_basic_session(self):
        script = "diff x^2 wrt x\nsolve x^2-4=0 for x\nbadinput(((\nquit\n"
        r = subprocess.run(
            [sys.executable, "-m", "axiom.cli", "repl"],
            cwd=REPO_ROOT, input=script, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("2*x", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
