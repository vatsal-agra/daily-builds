"""End-to-end CLI smoke tests, run as real subprocesses (the way a user
would actually invoke the tool), including the error-handling paths fixed
during Phase 3's adversarial review."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "cli.py")
DEMO = os.path.join(ROOT, "demo", "fib.rn")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, CLI, *args], capture_output=True, text=True, cwd=ROOT, timeout=30
    )


class CliTests(unittest.TestCase):
    def test_run_success(self):
        r = run_cli("run", DEMO, "fib", "10")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "55")

    def test_compile_produces_wasm(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "fib.wasm")
            r = run_cli("compile", DEMO, "-o", out)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(out))
            with open(out, "rb") as f:
                self.assertEqual(f.read(4), b"\x00asm")

    def test_disasm_runs(self):
        r = run_cli("disasm", DEMO)
        self.assertEqual(r.returncode, 0)
        self.assertIn("(module", r.stdout)

    def test_trace_writes_html(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "trace.html")
            r = run_cli("trace", DEMO, "fib", "8", "-o", out)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(out))
            with open(out) as f:
                content = f.read()
            self.assertIn("<html", content)
            self.assertIn("TRACE", content)

    # --- error paths fixed in Phase 3: clean messages, no tracebacks ---

    def test_bad_int_arg_is_clean(self):
        r = run_cli("run", DEMO, "fib", "notanumber")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("error:", r.stderr)

    def test_wrong_arity_is_clean(self):
        r = run_cli("run", DEMO, "fib", "1", "2")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_unknown_function_is_clean(self):
        r = run_cli("run", DEMO, "nosuchfunction", "1")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_file_is_clean(self):
        r = run_cli("run", os.path.join(ROOT, "demo", "does_not_exist.rn"), "f", "1")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_compile_error_is_clean(self):
        with tempfile.NamedTemporaryFile(suffix=".rn", mode="w", delete=False) as f:
            f.write("fn broken( { return 1; }")
            path = f.name
        try:
            r = run_cli("run", path, "broken", "1")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("Traceback", r.stderr)
            self.assertIn("compile error", r.stderr)
        finally:
            os.unlink(path)

    def test_trap_is_clean(self):
        divmod_src = os.path.join(ROOT, "demo", "divmod_edge.rn")
        r = run_cli("run", divmod_src, "div", "5", "0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("trap", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
