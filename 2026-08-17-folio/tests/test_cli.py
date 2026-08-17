"""CLI-level robustness tests -- every one of these is something the
adversarial review (Phase 3) found crashing with a raw traceback; each must
now fail cleanly (or succeed sensibly) instead."""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "cli.py")


def run_cli(*args):
    result = subprocess.run(
        [sys.executable, CLI] + list(args), capture_output=True, text=True, timeout=30
    )
    return result.returncode, result.stdout, result.stderr


class TestCLIRobustness(unittest.TestCase):
    def test_missing_file_clean_error(self):
        code, out, err = run_cli("render", "/tmp/definitely_missing_folio_test.html")
        self.assertNotEqual(code, 0)
        self.assertIn("no such file", err)
        self.assertNotIn("Traceback", err)

    def test_empty_document_clean_error(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            code, out, err = run_cli("render", path)
            self.assertNotEqual(code, 0)
            self.assertNotIn("Traceback", err)
        finally:
            os.unlink(path)

    def test_whitespace_only_document_renders_something(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write("<html><body>   \n\t  </body></html>")
            path = f.name
        try:
            with tempfile.TemporaryDirectory() as outdir:
                out_svg = os.path.join(outdir, "out.svg")
                code, out, err = run_cli("render", path, "-o", out_svg)
                self.assertEqual(code, 0, err)
                self.assertTrue(os.path.exists(out_svg))
        finally:
            os.unlink(path)

    def test_negative_dimensions_do_not_crash(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write(
                '<html><body><div style="width:-50px;height:-20px">x</div></body></html>'
            )
            path = f.name
        try:
            code, out, err = run_cli("layout", path)
            self.assertEqual(code, 0, err)
            self.assertNotIn("-", out.split("w=")[1].split()[0])  # width resolved, not negative
        finally:
            os.unlink(path)

    def test_deeply_nested_document_does_not_crash(self):
        html = "<html><body>" + "<div>" * 2000 + "x" + "</div>" * 2000 + "</body></html>"
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write(html)
            path = f.name
        try:
            code, out, err = run_cli("layout", path)
            self.assertEqual(code, 0, err)
        finally:
            os.unlink(path)

    def test_malformed_css_does_not_crash(self):
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write(
                "<html><head><style>div { color: ; width: 10px</style></head>"
                "<body><div>hi</div></body></html>"
            )
            path = f.name
        try:
            with tempfile.TemporaryDirectory() as outdir:
                out_svg = os.path.join(outdir, "out.svg")
                code, out, err = run_cli("render", path, "-o", out_svg)
                self.assertEqual(code, 0, err)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
