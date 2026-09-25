import os
import shutil
import subprocess
import unittest

from casement import oracle


def _playwright_available():
    if shutil.which("node") is None:
        return False
    try:
        env = oracle._node_env()
        proc = subprocess.run(
            ["node", "-e", "require('playwright')"],
            capture_output=True, timeout=15, env=env,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_HAVE_ORACLE = _playwright_available()


@unittest.skipUnless(_HAVE_ORACLE, "node + playwright not available in this environment")
class TestChromiumOracle(unittest.TestCase):
    def test_explicit_box_model_matches_real_chromium_exactly(self):
        html = """
        <html><body>
        <div style="width:200px;height:100px;margin:10px;padding:5px;border:2px solid black;">x</div>
        </body></html>
        """
        diffs = oracle.compare(html, viewport_width=400)
        self.assertGreater(len(diffs), 0)
        for d in diffs:
            self.assertLessEqual(abs(d.dx), 0.5, f"cid {d.cid} dx={d.dx}")
            self.assertLessEqual(abs(d.dy), 0.5, f"cid {d.cid} dy={d.dy}")
            self.assertLessEqual(abs(d.dw), 0.5, f"cid {d.cid} dw={d.dw}")
            self.assertLessEqual(abs(d.dh), 0.5, f"cid {d.cid} dh={d.dh}")

    def test_flexbox_geometry_matches_real_chromium(self):
        html = """
        <html><body>
        <div style="display:flex;width:300px;">
          <div style="flex:1;height:40px;">a</div>
          <div style="flex:2;height:40px;">b</div>
        </div>
        </body></html>
        """
        diffs = oracle.compare(html, viewport_width=400)
        for d in diffs:
            self.assertLessEqual(d.max_abs_diff, 0.5, f"cid {d.cid} <{d.tag}> diff too large: "
                                  f"casement={d.casement_rect} browser={d.browser_rect}")

    def test_oracle_test_example_page_within_documented_tolerance(self):
        # examples/oracle_test.html is deliberately all-explicit-sizing;
        # the only expected disagreement is the ~3px inline-block baseline
        # strut documented in PLAN.md (a font-metric quirk, not a bug).
        path = os.path.join(os.path.dirname(__file__), "..", "examples", "oracle_test.html")
        with open(path) as f:
            html = f.read()
        diffs = oracle.compare(html, viewport_width=800)
        self.assertGreater(len(diffs), 10)
        worst = max(d.max_abs_diff for d in diffs)
        self.assertLessEqual(worst, 4.0, "a regression should show up as a much larger diff than the documented ~3px inline-block strut")
        exact = [d for d in diffs if d.max_abs_diff < 0.5]
        self.assertGreaterEqual(len(exact), len(diffs) - 3)


if __name__ == "__main__":
    unittest.main()
