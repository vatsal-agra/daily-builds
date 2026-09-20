import os
import re
import unittest

from folio.engine import render_file, render_html
from folio.inspector import render_inspector_html

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")


class TestFullPipeline(unittest.TestCase):
    def test_all_example_pages_render_without_crashing(self):
        for name in sorted(os.listdir(EXAMPLES_DIR)):
            if not name.endswith(".html"):
                continue
            with self.subTest(example=name):
                page = render_file(os.path.join(EXAMPLES_DIR, name), viewport_width=500)
                png = page.to_png_bytes()
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertGreater(page.height, 0)

    def test_basic_example_is_a_valid_png_per_system_file_utility(self):
        import shutil
        import subprocess
        import tempfile

        if shutil.which("file") is None:
            self.skipTest("system 'file' utility not available")
        page = render_file(os.path.join(EXAMPLES_DIR, "basic.html"), viewport_width=500)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            page.save_png(f.name)
            path = f.name
        try:
            result = subprocess.run(["file", path], capture_output=True, text=True)
            self.assertIn("PNG image data", result.stdout)
        finally:
            os.unlink(path)

    def test_inspector_generates_valid_json_and_matching_dimensions(self):
        import json

        page = render_file(os.path.join(EXAMPLES_DIR, "basic.html"), viewport_width=500)
        html = render_inspector_html(page)
        m = re.search(r"const DATA = (.*?);\n\nconst canvas", html, re.DOTALL)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertEqual(data["width"], 500)
        self.assertEqual(data["height"], max(1, page.height))
        self.assertGreater(len(data["regions"]), 0)
        self.assertGreater(len(data["paint"]), 0)


class TestHostileInputSurvives(unittest.TestCase):
    """A grab-bag of hostile/unusual inputs that must render without
    raising and without hanging -- each one was a real bug caught during
    Phases 2-4 (see REVIEW.md) or a plausible variant of one."""

    CASES = [
        ("empty p", "<html><body><p></p><p>   </p><p>after</p></body></html>"),
        ("table (no real grid layout, must not crash)",
         "<html><body><table><tr><td>A</td><td>B</td></tr></table></body></html>"),
        ("deep nesting", "<html><body>" + "<div>" * 150 + "deep" + "</div>" * 150 + "</body></html>"),
        ("only text, no tags", "just some raw text, no tags at all"),
        ("malformed css", "<html><head><style>div{color:red;</style></head><body><div>x</div></body></html>"),
        ("weird attrs", "<div class=card id='x' disabled data-x=1>hi</div>"),
        ("huge width", '<div style="width: 99999999999999999999px">x</div>'),
        ("negative margin", '<div style="margin: -9999px">x</div>'),
        ("bad color values", '<div style="color: not-a-color; background-color: rgb(999,999,999)">x</div>'),
        ("nested lists", "<ul><li>a<ul><li>b</li></ul></li></ul>"),
        ("self closing div", "<div/>after"),
        ("malformed tag", "<div>hi <3d> there</div>"),
        ("inline image placeholder", '<p>before <img src="x.png" alt="pic"> after</p>'),
        ("unclosed everything", "<p>unclosed <b>bold <i>italic forever"),
    ]

    def test_hostile_inputs_render_cleanly(self):
        for name, html in self.CASES:
            with self.subTest(case=name):
                page = render_html(html, viewport_width=300)
                png = page.to_png_bytes()
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
