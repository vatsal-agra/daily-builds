"""Phase 4: gallery + empty / invalid input behaviour of the CLI (no tracebacks, exit code 1)."""
import io
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tangle import cli, catalog
from tangle.gallery import build_gallery


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestGallery(unittest.TestCase):
    def test_gallery(self):
        html = build_gallery()
        drawable = [n for n in catalog.names() if catalog.get(n).braid and catalog.get(n).braid[1]]
        self.assertEqual(html.count("<article"), len(drawable))
        self.assertEqual(html.count("<svg"), 2 * len(drawable))              # light + dark drawing each
        self.assertNotRegex(html, r"https?://(?!www\.w3\.org)")             # self-contained, no CDN
        for svg in re.findall(r"<svg.*?</svg>", html, re.S):
            ET.fromstring(svg)
        for name in drawable:
            self.assertIn(name, html)
        self.assertIn("prefers-color-scheme:dark", html)

    def test_cli_gallery(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.html")
            code, out, _ = run("gallery", "-o", p)
            self.assertEqual(code, 0)
            self.assertGreater(os.path.getsize(p), 50_000)
        code, _, err = run("gallery", "-o", "/nonexistent/dir/g.html")
        self.assertEqual(code, 1)
        self.assertIn("error", err)


class TestInvalidInput(unittest.TestCase):
    CASES = [
        (["analyze", "--braid", "1 x"], "cannot parse"),
        (["analyze", "--torus", "3"], "two integers"),
        (["analyze", "--torus", "a,b"], "two integers"),
        (["analyze", "--torus", "1,3"], "p >= 2"),
        (["analyze", "--name", ""], "unknown knot"),
        (["analyze", "--braid", "1 1 1", "--strands", "1"], "needs at least"),
        (["analyze", "--pd", ""], "unexpected|empty"),
        (["analyze", "--pd", "X[1,2,3,4]"], "exactly twice"),
        (["analyze", "--pd", "X[1,5,2,4] X[3,6,4,1] X[5,2,6,3]"], "not a planar"),
        (["draw", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]", "-o", "x.svg"], "braid representation"),
        (["draw", "--name", "3_1", "-o", "/nonexistent/dir/x.svg"], "No such file"),
        (["simplify", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]"], "needs a braid"),
        (["analyze", "--braid", "1 1", "--name", "3_1"], "exactly one"),
        (["analyze"], "exactly one"),
    ]

    def test_all_fail_cleanly(self):
        for argv, msg in self.CASES:
            code, out, err = run(*argv)
            self.assertEqual(code, 1, argv)
            self.assertRegex(err, msg, argv)
            self.assertNotIn("Traceback", err)

    def test_empty_inputs_are_meaningful(self):
        code, out, _ = run("analyze", "--braid", "")
        self.assertEqual(code, 0)
        self.assertIn("0_1", out)                                           # empty braid = unknot
        code, out, _ = run("simplify", "--braid", "", "--strands", "1")
        self.assertIn("PROVED", out)
        code, out, _ = run("analyze", "--pd", "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]", "--loops", "1")
        self.assertIn("2 component", out)


if __name__ == "__main__":
    unittest.main()
