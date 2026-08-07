import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.process import Process
import html_report


class ReportBuildsTest(unittest.TestCase):
    def test_build_report_produces_valid_html_with_embedded_json(self):
        procs = [Process("P1", 0, 5), Process("P2", 1, 3)]
        out = Path("/tmp/dispatch_test_report.html")
        try:
            html_report.build_report(procs, 4, [1, 2, 3, 1, 2], 2, out)
            text = out.read_text()
            self.assertIn("<title>Dispatch", text)
            self.assertIn("DATA = ", text)
            # the embedded JSON payload must be extractable and parse cleanly
            start = text.index("const DATA = ") + len("const DATA = ")
            end = text.index(";\n", start)
            payload = json.loads(text[start:end])
            self.assertEqual(len(payload["cpu"]), 7)  # 7 CPU-scheduling algorithm variants
            self.assertIn("fifo", payload["vm"])
        finally:
            out.unlink(missing_ok=True)


class ScriptCloseTagEscapeTest(unittest.TestCase):
    """A pid or reference-string value containing a literal `</script>` must not
    be able to break out of the embedded JSON <script> block (the same bug
    class a previous ledger entry -- Palimpsest, 2026-07-04 -- shipped and fixed)."""

    def test_script_tag_in_pid_is_escaped_in_output(self):
        procs = [Process("</script><script>window.__pwn=1</script>", 0, 5), Process("P2", 1, 3)]
        out = Path("/tmp/dispatch_test_report_scripttag.html")
        try:
            html_report.build_report(procs, 4, [1, 2, 1], 2, out)
            text = out.read_text()
            self.assertNotIn("</script><script>window.__pwn", text)
            self.assertIn("<\\/script>", text)  # the escaped form must be present instead
        finally:
            out.unlink(missing_ok=True)


class XssEscapingRegressionTest(unittest.TestCase):
    """Regression test for the stored-XSS-shaped bug found in Phase 3 adversarial
    review: a pid interpolated raw into an innerHTML template literal. The real
    proof this stays fixed is the headless-Chromium check in demo.sh (source
    code can't tell you the browser won't execute it) -- this test checks the
    static/mechanical half: escapeHtml() exists and every pid-interpolating
    innerHTML sink in the generated JS routes through it."""

    def test_escape_helper_present_and_used_at_every_pid_sink(self):
        procs = [Process("P1", 0, 5)]
        out = Path("/tmp/dispatch_test_report_escape.html")
        try:
            html_report.build_report(procs, 4, [1, 2], 1, out)
            text = out.read_text()
            self.assertIn("function escapeHtml(", text)
            self.assertIn("escapeHtml(seg.pid)", text)
            self.assertIn("escapeHtml(r.pid)", text)
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
