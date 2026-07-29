"""End-to-end tests through the real CLI entry point (subprocess), not
just the library API -- catches argument-parsing bugs, exit codes, and
raw-traceback regressions the library-level tests can't see."""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "ember.cli", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


class TestCli(unittest.TestCase):
    def test_run(self):
        p = run_cli("run", os.path.join(EXAMPLES, "fib.em"), "fib", "10")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "55")

    def test_interp(self):
        p = run_cli("interp", os.path.join(EXAMPLES, "fib.em"), "fib", "10")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "55")

    def test_compare_match(self):
        p = run_cli("compare", os.path.join(EXAMPLES, "gcd.em"), "gcd", "1071", "462")
        self.assertEqual(p.returncode, 0)
        self.assertIn("MATCH", p.stdout)
        self.assertNotIn("MISMATCH", p.stdout)

    def test_compare_with_opt_flag(self):
        p = run_cli("compare", os.path.join(EXAMPLES, "fib.em"), "fib", "12", "--opt")
        self.assertEqual(p.returncode, 0)
        self.assertIn("MATCH", p.stdout)

    def test_ast(self):
        p = run_cli("ast", os.path.join(EXAMPLES, "gcd.em"))
        self.assertEqual(p.returncode, 0)
        self.assertIn("fn gcd", p.stdout)
        self.assertIn("While", p.stdout)

    def test_disasm(self):
        p = run_cli("disasm", os.path.join(EXAMPLES, "gcd.em"), "--fn", "gcd")
        self.assertEqual(p.returncode, 0)
        self.assertIn("push", p.stdout)
        self.assertIn("ret", p.stdout)

    def test_bench(self):
        p = run_cli("bench", os.path.join(EXAMPLES, "fib.em"), "fib", "18")
        self.assertEqual(p.returncode, 0)
        self.assertIn("speedup:", p.stdout)

    def test_demo(self):
        p = run_cli("demo")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("DEMO PASSED", p.stdout)

    # --- clean error handling: no raw Python tracebacks for ordinary user mistakes ---

    def test_missing_file_clean_error(self):
        p = run_cli("run", os.path.join(EXAMPLES, "does_not_exist.em"), "f", "1")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(p.stderr.startswith("error:"))
        self.assertNotIn("Traceback", p.stderr)

    def test_unknown_function_clean_error(self):
        p = run_cli("ast", os.path.join(EXAMPLES, "fib.em"), "--fn", "nope")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(p.stderr.startswith("error:"))
        self.assertNotIn("Traceback", p.stderr)

    def test_non_integer_argument_clean_error(self):
        p = run_cli("run", os.path.join(EXAMPLES, "fib.em"), "fib", "not_a_number")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not an integer", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_wrong_arg_count_clean_error(self):
        p = run_cli("run", os.path.join(EXAMPLES, "fib.em"), "fib", "1", "2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("expects 1 argument", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_division_by_zero_clean_error(self):
        div_file = os.path.join(ROOT, "tests", "_tmp_div.em")
        with open(div_file, "w") as f:
            f.write("fn d(a, b) { return a / b; }\n")
        try:
            p = run_cli("run", div_file, "d", "10", "0")
            self.assertEqual(p.returncode, 1)
            self.assertIn("division by zero", p.stderr)
            self.assertNotIn("Traceback", p.stderr)
        finally:
            os.remove(div_file)

    def test_viz_writes_html(self):
        out_path = os.path.join(ROOT, "tests", "_tmp_report.html")
        try:
            p = run_cli("viz", os.path.join(EXAMPLES, "fib.em"), "--out", out_path,
                        "--bench-fn", "fib", "--bench-args", "10")
            self.assertEqual(p.returncode, 0)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                content = f.read()
            self.assertIn("<html", content)
            self.assertIn("faster", content)
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)


if __name__ == "__main__":
    unittest.main()
