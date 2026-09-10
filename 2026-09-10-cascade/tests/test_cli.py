"""CLI-level tests: invokes cascade/src/cli.py as a real subprocess, the
same way a user would, so error handling is checked end-to-end rather than
by calling internal functions directly."""

import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
CLI = os.path.join(SRC, "cli.py")


def run_cli(*args):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True)


class CLIErrorHandlingTests(unittest.TestCase):
    def test_missing_html_file_reports_clean_error(self):
        result = run_cli("render", "/no/such/file.html", "--out", "/tmp/cascade_test_out.png")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no such file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_negative_width_reports_clean_error(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write("<p>hi</p>")
            path = f.name
        try:
            result = run_cli("render", path, "--width", "-10", "--out", "/tmp/cascade_test_out.png")
            self.assertEqual(result.returncode, 1)
            self.assertIn("--width", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        finally:
            os.unlink(path)

    def test_zero_width_reports_clean_error(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write("<p>hi</p>")
            path = f.name
        try:
            result = run_cli("layout", path, "--width", "0")
            self.assertEqual(result.returncode, 1)
        finally:
            os.unlink(path)

    def test_pathological_deep_nesting_reports_clean_error(self):
        depth = 50000
        html = "<div>" * depth + "x" + "</div>" * depth
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write(html)
            path = f.name
        try:
            result = run_cli("render", path, "--out", "/tmp/cascade_test_out.png")
            self.assertEqual(result.returncode, 1)
            self.assertIn("nesting", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        finally:
            os.unlink(path)

    def test_successful_render_writes_a_real_png(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write("<html><body style='margin:0'><div style='width:50px;height:50px;"
                     "background-color:red'></div></body></html>")
            path = f.name
        out_path = tempfile.mktemp(suffix=".png")
        try:
            result = run_cli("render", path, "--out", out_path)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(os.path.exists(out_path))
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_invalid_utf8_reports_clean_error_not_traceback(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="wb", delete=False) as f:
            f.write(b"<p>\xff\xfe not valid utf-8</p>")
            path = f.name
        try:
            result = run_cli("render", path, "--out", "/tmp/cascade_test_out.png")
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
