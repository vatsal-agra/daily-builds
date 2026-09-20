"""Differential testing against real headless Chromium: an independent,
off-the-shelf CSS layout implementation to check Folio's box-model math
against, the same role gcc/objdump played for Ember, sqlite3 played for
PicoSQL, and Node's own WebAssembly runtime played for Kiln.

Scope, stated up front: only elements whose box geometry does NOT depend
on text/glyph metrics are asserted on (explicit width/height/margin/
padding/border, float placement, clear). Folio measures text on a
fixed-pitch grid (PLAN.md's documented scope decision) rather than real
font metrics, so a real browser's proportional (or even a different
monospace stack's) glyph widths are expected to disagree with Folio's on
anything text-driven -- that is a deliberate scope boundary, not something
this oracle should be fighting to hide. The CSS box model itself (what
this test actually checks) has no such excuse: it's pure arithmetic spec'd
byte-for-byte the same everywhere, so Folio's numbers must match a real
browser's exactly (to rounding).
"""

import unittest

from folio.engine import render_html
from folio.layout import Box

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

CHROMIUM_PATH = "/opt/pw-browsers/chromium"


def _find_by_id(box, node_id):
    if isinstance(box, Box) and box.node is not None and box.node.get("id") == node_id:
        return box
    for c in box.children:
        if isinstance(c, Box):
            r = _find_by_id(c, node_id)
            if r is not None:
                return r
    return None


def _chromium_rects(html, ids):
    """Render `html` in real headless Chromium and return {id: (x,y,w,h)}
    from getBoundingClientRect(), rounded to the nearest int."""
    import os

    executable = CHROMIUM_PATH if os.path.exists(CHROMIUM_PATH) else None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable) if executable else p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 800})
        page.set_content(html)
        rects = {}
        for node_id in ids:
            rect = page.evaluate(
                """(id) => {
                    const el = document.getElementById(id);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }""",
                node_id,
            )
            if rect is not None:
                rects[node_id] = (
                    round(rect["x"]), round(rect["y"]),
                    round(rect["width"]), round(rect["height"]),
                )
        browser.close()
        return rects


@unittest.skipUnless(sync_playwright is not None, "playwright not installed")
class TestChromiumOracle(unittest.TestCase):
    def _assert_matches_chromium(self, html, ids, tolerance=1):
        page = render_html(html, viewport_width=800)
        chromium_rects = _chromium_rects(html, ids)
        for node_id in ids:
            with self.subTest(id=node_id):
                self.assertIn(node_id, chromium_rects, f"Chromium found no #{node_id}")
                box = _find_by_id(page.root_box, node_id)
                self.assertIsNotNone(box, f"Folio found no #{node_id}")
                cx, cy, cw, ch = chromium_rects[node_id]
                for label, folio_val, chrome_val in (
                    ("x", box.x, cx), ("y", box.y, cy),
                    ("width", box.width, cw), ("height", box.height, ch),
                ):
                    self.assertLessEqual(
                        abs(folio_val - chrome_val), tolerance,
                        f"#{node_id} {label}: folio={folio_val} chromium={chrome_val}",
                    )

    def test_box_model_dimensions(self):
        html = """
        <html><body style="margin:0">
          <div id="a" style="width:200px; height:100px; margin:10px;
               padding:15px; border:5px solid black; box-sizing:content-box;">
          </div>
        </body></html>
        """
        # content-box: border-box width = 200 + 2*15 + 2*5 = 240
        self._assert_matches_chromium(html, ["a"])

    def test_border_box_sizing(self):
        html = """
        <html><body style="margin:0">
          <div id="a" style="width:200px; height:100px; box-sizing:border-box;
               padding:15px; border:5px solid black;"></div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["a"])

    def test_percentage_width(self):
        html = """
        <html><body style="margin:0">
          <div id="outer" style="width:400px;">
            <div id="a" style="width:50%; height:30px;"></div>
          </div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["outer", "a"])

    def test_auto_margin_centering(self):
        html = """
        <html><body style="margin:0">
          <div id="a" style="width:100px; height:50px; margin:0 auto;"></div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["a"])

    def test_margin_left_offset(self):
        html = """
        <html><body style="margin:0">
          <div id="a" style="width:100px; height:50px; margin-left:73px;"></div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["a"])

    def test_sibling_margin_collapsing(self):
        html = """
        <html><body style="margin:0">
          <div id="a" style="height:40px; margin-bottom:30px;"></div>
          <div id="b" style="height:40px; margin-top:20px;"></div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["a", "b"])

    def test_over_constrained_margins(self):
        # `outer` has a 1px border specifically so its own top/bottom edge
        # is not touching its child's -- this suppresses real CSS's
        # parent-child margin collapsing (CSS2.1 8.3.1), which Folio does
        # not implement (a documented scope boundary, PLAN.md), so this
        # test isolates the thing it actually means to check: `a`'s
        # over-constrained left/right margin resolution.
        html = """
        <html><body style="margin:0">
          <div id="outer" style="width:380px; border:1px solid black;">
            <div id="a" style="width:200px; border:2px solid black;
                 padding:5px; margin:8px;"></div>
          </div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["outer", "a"])

    def test_float_placement_and_clear(self):
        html = """
        <html><body style="margin:0">
          <div id="left" style="float:left; width:80px; height:60px;"></div>
          <div id="right" style="float:right; width:80px; height:60px;"></div>
          <div id="cleared" style="clear:both; height:10px;"></div>
        </body></html>
        """
        self._assert_matches_chromium(html, ["left", "right", "cleared"])


if __name__ == "__main__":
    unittest.main()
