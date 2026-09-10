"""Headless-Chromium UI smoke test for the interactive box inspector
(`cascade viz`, src/viz.py): generates a real inspector page from an
example, drives it in real headless Chromium via
tools/oracle/inspector_check.js, and asserts zero console errors and that
clicking a box actually populates the detail panel -- not just "the HTML
didn't crash to write."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

HERE = os.path.dirname(os.path.abspath(__file__))
CASCADE_ROOT = os.path.dirname(HERE)
CHECK_JS = os.path.join(CASCADE_ROOT, "tools", "oracle", "inspector_check.js")
ORACLE_NODE_MODULES = os.path.join(CASCADE_ROOT, "tools", "oracle", "node_modules")
EXAMPLES_DIR = os.path.join(CASCADE_ROOT, "examples")


def _oracle_available():
    return (shutil.which("node") is not None
            and os.path.isdir(ORACLE_NODE_MODULES)
            and os.path.isfile(CHECK_JS))


@unittest.skipUnless(_oracle_available(), "Node/Playwright oracle not set up in this environment")
class InspectorUITests(unittest.TestCase):
    def _generate_and_check(self, html_path, width=900):
        from cascade import Cascade
        from dom import find_all
        from html_parser import parse_html
        from layout import build_root
        from viz import generate_inspector_html

        with open(html_path, encoding="utf-8") as f:
            html_text = f.read()
        doc = parse_html(html_text)
        css_text = "".join(el.text_content() for el in find_all(doc, tag="style"))
        Cascade(css_text).compute_styles(doc)
        root = build_root(doc.children[0], width)
        out_html = generate_inspector_html(root, width)

        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
            f.write(out_html)
            out_path = f.name
        try:
            result = subprocess.run(["node", CHECK_JS, out_path], capture_output=True,
                                     text=True, cwd=CASCADE_ROOT, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        finally:
            os.unlink(out_path)

    def test_cards_example_zero_console_errors(self):
        info = self._generate_and_check(os.path.join(EXAMPLES_DIR, "cards.html"))
        self.assertEqual(info["consoleErrors"], [])

    def test_cards_example_click_populates_detail_panel(self):
        info = self._generate_and_check(os.path.join(EXAMPLES_DIR, "cards.html"))
        self.assertTrue(info["detailPopulated"])
        self.assertTrue(info["hasBoxModelDiagram"])
        self.assertGreater(info["boxCount"], 0)

    def test_article_example_zero_console_errors(self):
        info = self._generate_and_check(os.path.join(EXAMPLES_DIR, "article.html"))
        self.assertEqual(info["consoleErrors"], [])

    def test_boxmodel_example_zero_console_errors(self):
        info = self._generate_and_check(os.path.join(EXAMPLES_DIR, "boxmodel.html"))
        self.assertEqual(info["consoleErrors"], [])


if __name__ == "__main__":
    unittest.main()
