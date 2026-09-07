import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "leibniz_cli")


def run(*args, input_text=None):
    return subprocess.run(
        [sys.executable, CLI, *args],
        cwd=ROOT, capture_output=True, text=True, input=input_text, timeout=20,
    )


class TestCliHappyPath(unittest.TestCase):
    def test_simplify(self):
        r = run("simplify", "2*x + 3*x - 1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "5*x - 1")

    def test_expand(self):
        r = run("expand", "(x+1)*(x-2)")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "x^2 - x - 2")

    def test_factor(self):
        r = run("factor", "x^2 - 5*x + 6")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "(x - 2)*(x - 3)")

    def test_diff(self):
        r = run("diff", "x^2*sin(x)", "--var", "x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "cos(x)*x^2 + 2*x*sin(x)")

    def test_diff_infers_the_only_variable(self):
        r = run("diff", "x^2")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "2*x")

    def test_integrate(self):
        r = run("integrate", "x^3", "--var", "x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "1/4*x^4 + C")

    def test_solve(self):
        r = run("solve", "x^2 - 5*x + 6 = 0", "--var", "x")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(set(r.stdout.split("\n")) - {""}, {"x = 3", "x = 2"})

    def test_solve_system(self):
        r = run("solve-system", "2*x+y=5", "x-y=1", "--vars", "x,y")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip().splitlines(), ["x = 2", "y = 1"])

    def test_eval(self):
        r = run("eval", "x^2+1", "--at", "x=3")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "10.0")

    def test_ratsimp(self):
        r = run("ratsimp", "(x^2-1)/(x-1)")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "x + 1")

    def test_viz_writes_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.html")
            r = run("diff", "x^3", "--var", "x", "--viz", out)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(out))
            with open(out) as f:
                html = f.read()
            self.assertIn("<title>", html)
            self.assertIn("STEPS", html)


class TestCliErrorPaths(unittest.TestCase):
    """No traceback, no crash, non-zero exit, a clean 'error: ...' line."""

    def _assert_clean_error(self, r):
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_malformed_expression(self):
        self._assert_clean_error(run("simplify", "2+*3"))

    def test_empty_expression(self):
        self._assert_clean_error(run("simplify", ""))

    def test_multivariate_factor(self):
        self._assert_clean_error(run("factor", "x*y+1"))

    def test_non_polynomial_solve(self):
        self._assert_clean_error(run("solve", "sin(x)=0", "--var", "x"))

    def test_unsupported_integral(self):
        self._assert_clean_error(run("integrate", "exp(x^2)", "--var", "x"))

    def test_ambiguous_variable(self):
        self._assert_clean_error(run("diff", "x+y"))

    def test_eval_missing_binding(self):
        self._assert_clean_error(run("eval", "x+1"))

    def test_division_by_zero(self):
        self._assert_clean_error(run("simplify", "1/0"))


class TestRepl(unittest.TestCase):
    def test_basic_session(self):
        r = run("repl", input_text="3*x + x\ndiff x^3, x\nsolve x^2-4, x\nquit\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("4*x", r.stdout)
        self.assertIn("3*x^2", r.stdout)
        self.assertIn("x = 2", r.stdout)

    def test_repl_recovers_from_bad_input(self):
        r = run("repl", input_text="2+*3\n5*x\nquit\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("error:", r.stdout)
        self.assertIn("5*x", r.stdout)


if __name__ == "__main__":
    unittest.main()
