import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cascade.engine import render_html
from cascade.dom import Element


def box_for(root_box, el_id):
    for b in root_box.walk():
        if isinstance(b.node, Element) and b.node.id() == el_id:
            return b
    return None


class TestLayout(unittest.TestCase):
    def test_block_stacking_and_margin_collapsing(self):
        html = """<div style="border:1px solid black">
            <div id="a" style="height:40px;margin:16px 0;background:red"></div>
            <div id="b" style="height:40px;margin:16px 0;background:blue"></div>
        </div>"""
        r = render_html(html, viewport_width=800)
        a = box_for(r.box, "a")
        b = box_for(r.box, "b")
        gap = b.dims.border_box().y - a.dims.border_box().y - a.dims.border_box().height
        self.assertAlmostEqual(gap, 16.0, places=1)  # collapsed, not 32

    def test_mixed_sign_margin_collapsing(self):
        html = """<div style="border:1px solid black">
            <div id="a" style="height:40px;margin-bottom:16px;background:red"></div>
            <div id="b" style="height:40px;margin-top:-10px;background:blue"></div>
        </div>"""
        r = render_html(html, viewport_width=800)
        a = box_for(r.box, "a")
        b = box_for(r.box, "b")
        gap = b.dims.border_box().y - a.dims.border_box().y - a.dims.border_box().height
        self.assertAlmostEqual(gap, 6.0, places=1)  # max(16,0) + min(-10,0) = 6

    def test_box_sizing_border_box_width_and_height(self):
        html = '<div id="x" style="width:200px;height:100px;box-sizing:border-box;' \
               'padding:10px;border:5px solid black"></div>'
        r = render_html(html, viewport_width=800)
        x = box_for(r.box, "x")
        bb = x.dims.border_box()
        self.assertAlmostEqual(bb.width, 200.0, places=1)
        self.assertAlmostEqual(bb.height, 100.0, places=1)
        self.assertAlmostEqual(x.dims.content.width, 200 - 20 - 10, places=1)
        self.assertAlmostEqual(x.dims.content.height, 100 - 20 - 10, places=1)

    def test_auto_margin_centering(self):
        html = '<div style="width:600px"><div id="c" style="width:200px;height:10px;' \
               'margin:0 auto"></div></div>'
        r = render_html(html, viewport_width=600)
        c = box_for(r.box, "c")
        self.assertAlmostEqual(c.dims.margin.left, 200.0, places=1)
        self.assertAlmostEqual(c.dims.margin.right, 200.0, places=1)

    def test_percentage_width(self):
        html = '<div style="width:400px"><div id="p" style="width:50%;height:10px"></div></div>'
        r = render_html(html, viewport_width=800)
        p = box_for(r.box, "p")
        self.assertAlmostEqual(p.dims.content.width, 200.0, places=1)

    def test_text_wraps_within_container(self):
        html = ('<div id="w" style="width:200px;font-family:monospace">'
                + "word " * 40 + "</div>")
        r = render_html(html, viewport_width=800)
        w = box_for(r.box, "w")
        anon = [c for c in w.children if c.box_type == "anon-inline"][0]
        self.assertGreater(len(anon.lines), 1)
        for line in anon.lines:
            right_edge = max(wd.x + wd.width for wd in line.words)
            self.assertLessEqual(right_edge, w.dims.content.x + w.dims.content.width + 1)

    def test_text_align_variants(self):
        for align, checker in [
            ("left", lambda x0, x1, avail: x0 < 5),
            ("right", lambda x0, x1, avail: (avail - x1) < 5),
            ("center", lambda x0, x1, avail: abs(x0 - (avail - x1)) < 5),
        ]:
            html = (f'<div id="w" style="width:300px;text-align:{align};font-family:monospace">'
                    f"short line</div>")
            r = render_html(html, viewport_width=800)
            w = box_for(r.box, "w")
            anon = [c for c in w.children if c.box_type == "anon-inline"][0]
            line = anon.lines[0]
            x0 = line.words[0].x - w.dims.content.x
            x1 = (line.words[-1].x + line.words[-1].width) - w.dims.content.x
            self.assertTrue(checker(x0, x1, w.dims.content.width), f"{align}: x0={x0} x1={x1}")

    def test_float_narrows_line_boxes(self):
        html = ('<div style="width:400px">'
                '<div style="width:100px;height:50px;float:left;background:red"></div>'
                '<p id="t" style="font-family:monospace">' + "x " * 60 + "</p></div>")
        r = render_html(html, viewport_width=800)
        p = box_for(r.box, "t")
        anon = [c for c in p.children if c.box_type == "anon-inline"][0]
        first_line_x = anon.lines[0].words[0].x
        later_line_x = anon.lines[-1].words[0].x
        self.assertGreater(first_line_x, later_line_x)

    def test_clear_pushes_below_floats(self):
        html = ('<div style="width:200px">'
                '<div style="width:100px;height:80px;float:left"></div>'
                '<div id="c" style="clear:both;height:5px"></div></div>')
        r = render_html(html, viewport_width=800)
        c = box_for(r.box, "c")
        self.assertGreaterEqual(c.dims.content.y, 80.0)

    def test_container_with_only_floats_collapses_height(self):
        # Real (no-clearfix) CSS behavior: an auto-height block does NOT
        # grow to contain a floated child.
        html = ('<div id="wrap" style="width:200px">'
                '<div style="width:50px;height:80px;float:left"></div></div>')
        r = render_html(html, viewport_width=800)
        wrap = box_for(r.box, "wrap")
        self.assertAlmostEqual(wrap.dims.content.height, 0.0, places=1)

    def test_inline_block_shrink_to_fit(self):
        html = ('<div style="font-family:monospace">'
                '<span id="short" style="display:inline-block">hi</span>'
                '<span id="long" style="display:inline-block">a much longer label here</span>'
                '</div>')
        r = render_html(html, viewport_width=800)
        short = box_for(r.box, "short")
        long_ = box_for(r.box, "long")
        self.assertLess(short.dims.margin_box().width, long_.dims.margin_box().width)

    def test_pre_preserves_whitespace_and_newlines(self):
        html = "<pre id='p'>a   b\nc</pre>"
        r = render_html(html, viewport_width=800)
        p = box_for(r.box, "p")
        anon = [c for c in p.children if c.box_type == "anon-inline"][0]
        self.assertEqual(len(anon.lines), 2)
        self.assertEqual(anon.lines[0].words[0].text, "a   b")
        self.assertEqual(anon.lines[1].words[0].text, "c")

    def test_no_crash_on_extreme_inputs(self):
        cases = [
            "",
            "hello world",
            '<div style="width:20px;padding:30px">x</div>',
            '<div style="width:0;height:0"></div>',
            '<div style="clear:both"></div>',
            '<div style="color:#zzz;background:#12345">bad colors</div>',
            "<div>" * 200 + "x" + "</div>" * 200,
        ]
        for html in cases:
            r = render_html(html, viewport_width=800)
            self.assertTrue(r.svg.startswith("<svg"))


class TestPaint(unittest.TestCase):
    def test_svg_is_well_formed_prefix_suffix(self):
        r = render_html('<div style="background:red;width:10px;height:10px"></div>')
        self.assertTrue(r.svg.strip().startswith("<svg"))
        self.assertTrue(r.svg.strip().endswith("</svg>"))

    def test_text_is_escaped(self):
        # Rendered per-word, so check the escaped pieces individually
        # rather than as one joined string.
        r = render_html("<p>a &lt; b &amp; c &gt; d</p>")
        self.assertIn(">&lt;<", r.svg)
        self.assertIn(">&amp;<", r.svg)
        self.assertIn(">&gt;<", r.svg)

    def test_transparent_background_paints_no_rect_for_that_color(self):
        r = render_html('<div style="width:10px;height:10px"></div>')
        # No crash and background-color: transparent should not emit a
        # visible fill for that element specifically (opacity 0 filtered).
        self.assertNotIn('fill-opacity="0.000"', r.svg)


if __name__ == "__main__":
    unittest.main()
