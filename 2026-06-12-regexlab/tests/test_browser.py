"""End-to-end browser test: the JS Pike VM inside a generated page must agree
with the Python engine on verdicts, spans, and capture groups.

Needs node + playwright + headless Chromium; skips (loudly) if unavailable.
Run `bash demo.sh` or `python3 -m unittest discover -s tests` from the
project root.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

import rxlab
from rxlab.viz import write_html

HERE = os.path.dirname(os.path.abspath(__file__))
PATTERN = r"(\w+)@(\w+)\.(?:com|org)"
CASES = [
    {"text": "mail me: bob@example.com!", "mode": "search"},
    {"text": "bob@example.com", "mode": "fullmatch"},
    {"text": "bob@example.net", "mode": "fullmatch"},
    {"text": "x@y.org", "mode": "match"},
    {"text": "", "mode": "search"},
    {"text": "no at sign", "mode": "search"},
    {"text": "🎉a@b.com", "mode": "search"},
]


def node_available():
    return shutil.which("node") is not None and os.path.isdir(
        "/opt/node22/lib/node_modules/playwright")


class TestBrowserParity(unittest.TestCase):
    @unittest.skipUnless(node_available(), "node+playwright not available")
    def test_js_vm_matches_python_engine(self):
        pat = rxlab.compile(PATTERN)
        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "page.html")
            write_html(PATTERN, html)
            cases = os.path.join(d, "cases.json")
            with open(cases, "w") as f:
                json.dump(CASES, f)
            proc = subprocess.run(
                ["node", os.path.join(HERE, "dom_check.mjs"), html, cases],
                capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["pageErrors"], [])
        self.assertTrue(out["stepperWorks"])
        for r in out["results"]:
            m = getattr(pat, r["mode"])(r["text"])
            self.assertEqual(r["matched"], m is not None,
                             f"verdict differs for {r['mode']} {r['text']!r}")
            if m is not None:
                self.assertEqual(tuple(r["span"]), m.span(), r["text"])
                want = [None if m.span(i) == (-1, -1) else list(m.span(i))
                        for i in range(1, pat.ngroups + 1)]
                self.assertEqual(r["groups"], want, r["text"])
            # DFA verdict (page computes fullmatch only)
            self.assertEqual(r["dfa"],
                             pat.dfa().fullmatch(r["text"]), r["text"])
