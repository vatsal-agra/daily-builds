"""The Chromium differential oracle (PLAN.md stretch feature #6): renders a
battery of fixed-dimension HTML/CSS pages (no text-metric-dependent sizing,
so the comparison is fair -- Cascade's bitmap font doesn't claim to match
any real font's glyph metrics) through BOTH Cascade's own layout engine and
real headless Chromium (via tools/oracle/measure.js + Playwright), then
asserts every probed element's box geometry is pixel-identical between the
two -- the strongest correctness check available anywhere in this build,
using the actual reference implementation of the thing being rebuilt.

Skips itself cleanly (rather than failing) if Node/the Playwright package
isn't set up in this environment, so the rest of the suite is unaffected.
"""

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
ORACLE_JS = os.path.join(CASCADE_ROOT, "tools", "oracle", "measure.js")
ORACLE_NODE_MODULES = os.path.join(CASCADE_ROOT, "tools", "oracle", "node_modules")

RESET = "* { margin:0; padding:0; box-sizing: content-box; border-width: 0; border-style: none; }\n"


def _oracle_available():
    return (shutil.which("node") is not None
            and os.path.isdir(ORACLE_NODE_MODULES)
            and os.path.isfile(ORACLE_JS))


def chromium_boxes(html, width):
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as f:
        f.write(html)
        path = f.name
    try:
        result = subprocess.run(["node", ORACLE_JS, path, str(width)],
                                 capture_output=True, text=True, cwd=CASCADE_ROOT, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"oracle failed: {result.stderr}")
        return {b["id"]: b for b in json.loads(result.stdout)}
    finally:
        os.unlink(path)


def cascade_boxes(html, width):
    from cascade import Cascade
    from dom import Element, find_all
    from html_parser import parse_html
    from layout import build_root

    doc = parse_html(html)
    css_text = "".join(el.text_content() for el in find_all(doc, tag="style"))
    Cascade(css_text).compute_styles(doc)
    root = build_root(doc.children[0], width)
    out = {}

    def walk(box):
        if isinstance(box.node, Element) and box.node.id and "data-probe" in box.node.attrs:
            out[box.node.id] = {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
        for c in box.children:
            walk(c)

    walk(root)
    return out


@unittest.skipUnless(_oracle_available(), "Node/Playwright oracle not set up in this environment")
class ChromiumDiffOracleTests(unittest.TestCase):
    def assert_matches_chromium(self, html, width=900, tol=0.5):
        html = f"<!DOCTYPE html><html><head><style>{RESET}</style>{html}"
        cascade_result = cascade_boxes(html, width)
        chromium_result = chromium_boxes(html, width)
        probed_ids = set(cascade_result) | set(chromium_result)
        self.assertTrue(probed_ids, "no [data-probe] elements found in fixture")
        for pid in sorted(probed_ids):
            self.assertIn(pid, cascade_result, f"#{pid}: Cascade produced no box for it")
            self.assertIn(pid, chromium_result, f"#{pid}: Chromium produced no box for it")
            c, r = cascade_result[pid], chromium_result[pid]
            for field in ("x", "y", "width", "height"):
                self.assertAlmostEqual(
                    c[field], r[field], delta=tol,
                    msg=f"#{pid}.{field}: cascade={c[field]} chromium={r[field]}\n"
                        f"cascade={c}\nchromium={r}")

    def test_basic_box_model_with_padding_and_border(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div id="a" data-probe style="width:300px;height:200px;
        padding:20px;border:5px solid black;background:#eee"></div></body>
        """)

    def test_auto_margin_centering(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="width:500px">
          <div id="a" data-probe style="width:100px;height:50px;margin-left:auto;margin-right:auto"></div>
        </div></body>
        """)

    def test_nested_padding_border_percentage_width(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="width:400px;padding:10px;border:2px solid black">
          <div id="a" data-probe style="width:50%;height:80px"></div>
        </div></body>
        """)

    def test_margin_collapsing_between_siblings(self):
        self.assert_matches_chromium("""
        <body style="margin:0">
          <div style="height:20px;margin-bottom:30px"></div>
          <div id="a" data-probe style="height:10px;margin-top:10px"></div>
        </body>
        """)

    def test_percentage_height_against_definite_container(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="width:200px;height:400px">
          <div id="a" data-probe style="width:100%;height:25%"></div>
        </div></body>
        """)

    def test_flex_row_basic_distribution(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;width:600px">
          <div id="a" data-probe style="width:100px;height:40px"></div>
          <div id="b" data-probe style="width:150px;height:60px"></div>
        </div></body>
        """)

    def test_flex_grow(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;width:500px">
          <div id="a" data-probe style="width:100px;height:30px"></div>
          <div id="b" data-probe style="width:100px;height:30px;flex-grow:1"></div>
        </div></body>
        """)

    def test_flex_justify_content_space_between(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;width:400px;justify-content:space-between">
          <div id="a" data-probe style="width:50px;height:20px"></div>
          <div id="b" data-probe style="width:50px;height:20px"></div>
        </div></body>
        """)

    def test_flex_align_items_center(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;height:200px;align-items:center">
          <div id="a" data-probe style="width:50px;height:40px"></div>
        </div></body>
        """)

    def test_flex_column_direction(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;flex-direction:column;width:300px">
          <div id="a" data-probe style="height:30px"></div>
          <div id="b" data-probe style="height:50px;margin-top:10px"></div>
        </div></body>
        """)

    def test_flex_item_margin_spacing(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div style="display:flex;width:600px">
          <div id="a" data-probe style="width:50px;height:20px"></div>
          <div id="b" data-probe style="width:50px;height:20px;margin-left:25px"></div>
        </div></body>
        """)

    def test_border_currentcolor_default(self):
        self.assert_matches_chromium("""
        <body style="margin:0"><div id="a" data-probe style="color:blue;width:80px;height:80px;
        border-width:4px;border-style:solid"></div></body>
        """)


if __name__ == "__main__":
    unittest.main()
