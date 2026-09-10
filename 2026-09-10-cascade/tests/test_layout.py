import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cascade import Cascade
from dom import Element, find_all, find_first
from html_parser import parse_html
from layout import build_root


def layout(html, css, width=800):
    doc = parse_html(html)
    Cascade(css).compute_styles(doc)
    html_el = doc.children[0]
    return build_root(html_el, width)


def box_for(root, tag, nth=0):
    matches = [b for b in root.iter_boxes() if isinstance(b.node, Element) and b.node.tag == tag]
    return matches[nth]


class BoxModelTests(unittest.TestCase):
    def test_explicit_width_and_height(self):
        root = layout("<div style='width:200px;height:100px'></div>", "", width=800)
        div = box_for(root, "div")
        self.assertEqual(div.width, 200.0)
        self.assertEqual(div.height, 100.0)

    def test_auto_width_fills_containing_block(self):
        root = layout("<div></div>", "body{margin:0}", width=800)
        div = box_for(root, "div")
        self.assertEqual(div.width, 800.0)

    def test_padding_and_border_included_in_border_box(self):
        root = layout("<div style='width:100px;padding:10px;border:5px solid black'></div>",
                       "body{margin:0}", width=800)
        div = box_for(root, "div")
        # border-box width = content(100) + padding(10*2) + border(5*2)
        self.assertEqual(div.width, 100 + 20 + 10)
        self.assertEqual(div.content_width, 100.0)

    def test_margin_auto_centers_block(self):
        root = layout("<div style='width:200px;margin-left:auto;margin-right:auto'></div>",
                       "body{margin:0}", width=800)
        div = box_for(root, "div")
        self.assertAlmostEqual(div.x, (800 - 200) / 2.0)

    def test_percentage_width_resolves_against_containing_block(self):
        root = layout("<div style='width:50%'></div>", "body{margin:0}", width=800)
        div = box_for(root, "div")
        self.assertEqual(div.width, 400.0)

    def test_border_none_style_zeroes_width_even_if_width_set(self):
        root = layout("<div style='border-top-width:5px;border-top-style:none'></div>", "")
        div = box_for(root, "div")
        self.assertEqual(div.border.top, 0.0)

    def test_nested_block_positions_stack_vertically(self):
        root = layout("<div style='height:40px'></div><div style='height:60px'></div>",
                       "body{margin:0} div{margin:0}", width=400)
        divs = [b for b in root.iter_boxes() if isinstance(b.node, Element) and b.node.tag == "div"]
        self.assertEqual(divs[0].y, 0.0)
        self.assertEqual(divs[1].y, 40.0)


class MarginCollapseTests(unittest.TestCase):
    def test_adjoining_margins_collapse_to_max(self):
        root = layout(
            "<div style='margin-bottom:30px'></div><div style='margin-top:10px'></div>",
            "body{margin:0} div{height:20px}", width=400)
        divs = [b for b in root.iter_boxes() if isinstance(b.node, Element) and b.node.tag == "div"]
        # second div's top = first div's bottom edge (20) + max(30,10)=30
        self.assertEqual(divs[1].y, 50.0)

    def test_no_collapse_would_have_given_larger_gap(self):
        root = layout(
            "<div style='margin-bottom:30px'></div><div style='margin-top:10px'></div>",
            "body{margin:0} div{height:20px}", width=400)
        divs = [b for b in root.iter_boxes() if isinstance(b.node, Element) and b.node.tag == "div"]
        self.assertNotEqual(divs[1].y, 20 + 30 + 10)


class InlineLayoutTests(unittest.TestCase):
    def test_text_wraps_to_multiple_lines_when_narrow(self):
        root = layout("<p>one two three four five six seven eight nine ten</p>",
                       "body{margin:0}", width=100)
        p = box_for(root, "p")
        lines = [b for b in p.iter_boxes() if b.box_type == "line"]
        self.assertGreater(len(lines), 1)

    def test_text_fits_one_line_when_wide_enough(self):
        root = layout("<p>hi</p>", "body{margin:0}", width=800)
        p = box_for(root, "p")
        lines = [b for b in p.iter_boxes() if b.box_type == "line"]
        self.assertEqual(len(lines), 1)

    def test_br_forces_a_line_break(self):
        root = layout("<p>one<br>two</p>", "body{margin:0}", width=800)
        p = box_for(root, "p")
        lines = [b for b in p.iter_boxes() if b.box_type == "line"]
        self.assertEqual(len(lines), 2)

    def test_text_align_center(self):
        root = layout("<p style='text-align:center'>hi</p>", "body{margin:0}", width=400)
        p = box_for(root, "p")
        text_boxes = [b for b in p.iter_boxes() if b.box_type == "text"]
        # centered text shouldn't start flush at the left edge
        self.assertGreater(text_boxes[0].x, p.content_width * 0.3)

    def test_inline_bold_inherits_container_color(self):
        root = layout("<p style='color:blue'>hi <b>there</b></p>", "", width=800)
        p = box_for(root, "p")
        text_boxes = [b for b in p.iter_boxes() if b.box_type == "text"]
        self.assertTrue(all(t.color == (0, 0, 255, 255) for t in text_boxes))

    def test_list_item_gets_a_bullet_marker(self):
        root = layout("<ul><li>alpha</li></ul>", "", width=800)
        li = box_for(root, "li")
        text_boxes = [b for b in li.iter_boxes() if b.box_type == "text"]
        self.assertTrue(any("•" in (t.text or "") for t in text_boxes))


class InlineBlockTests(unittest.TestCase):
    def test_inline_block_sits_on_the_text_line(self):
        root = layout(
            "<p>a <span style='display:inline-block;width:20px;height:20px'></span> b</p>",
            "body{margin:0}", width=800)
        span = box_for(root, "span")
        self.assertEqual(span.width, 20.0)
        self.assertEqual(span.height, 20.0)
        self.assertGreater(span.x, 0.0)


class DisplayNoneTests(unittest.TestCase):
    def test_display_none_produces_no_box(self):
        root = layout("<div style='display:none'></div><p>x</p>", "", width=800)
        divs = [b for b in root.iter_boxes() if isinstance(b.node, Element) and b.node.tag == "div"]
        self.assertEqual(len(divs), 0)


class RegressionTests(unittest.TestCase):
    """One test per bug found and fixed during Phase 3 adversarial review
    (see REVIEW.md) -- pinned down so it can never silently come back."""

    def test_percentage_height_resolves_against_definite_containing_block(self):
        # was: always resolved against a hardcoded base of 0 (always 0px)
        root = layout(
            "<div style='width:200px;height:300px'>"
            "<div class='inner' style='height:50%'></div></div>",
            "body{margin:0}", width=400)
        inner = box_for(root, "div", nth=1)
        self.assertEqual(inner.height, 150.0)

    def test_percentage_height_falls_back_to_auto_against_indefinite_container(self):
        # against an auto-height parent, % height must NOT collapse to 0 --
        # it behaves as if 'height' were 'auto' and content determines it.
        root = layout(
            "<div><div class='inner' style='height:50%'><p>hi</p></div></div>",
            "body{margin:0}", width=400)
        inner = box_for(root, "div", nth=1)
        self.assertGreater(inner.height, 0.0)

    def test_inline_block_auto_width_shrinks_to_fit_text_content(self):
        # was: auto-width inline-block filled the ENTIRE line width instead
        # of hugging its (short) text content.
        root = layout(
            "<div style='width:400px'><span style='display:inline-block'>hi</span></div>",
            "body{margin:0}", width=400)
        span = box_for(root, "span")
        self.assertLess(span.width, 100.0)

    def test_border_defaults_to_currentcolor_not_black(self):
        # was: border-*-color's initial value was hardcoded to #000000
        # instead of the real CSS initial value, currentcolor.
        root = layout(
            "<div style='color:blue;border:2px solid;width:20px;height:20px'></div>",
            "body{margin:0}", width=400)
        div = box_for(root, "div")
        self.assertEqual(div.border_color.top, (0, 0, 255, 255))

    def test_explicit_border_color_still_overrides_currentcolor(self):
        root = layout(
            "<div style='color:blue;border:2px solid red;width:20px;height:20px'></div>",
            "body{margin:0}", width=400)
        div = box_for(root, "div")
        self.assertEqual(div.border_color.top, (255, 0, 0, 255))

    def test_negative_height_clamps_to_zero(self):
        # was: a negative height propagated as a negative content height
        # through every ancestor's box, instead of clamping like a real
        # browser (a negative specified length is invalid).
        root = layout("<div style='width:100px;height:-50px'></div>",
                       "body{margin:0}", width=400)
        div = box_for(root, "div")
        self.assertEqual(div.height, 0.0)
        self.assertGreaterEqual(root.height, 0.0)

    def test_negative_width_clamps_to_zero(self):
        root = layout("<div style='width:-30px;height:20px'></div>",
                       "body{margin:0}", width=400)
        div = box_for(root, "div")
        self.assertEqual(div.content_width, 0.0)

    def test_deeply_nested_document_does_not_crash(self):
        depth = 1200
        html = "<div>" * depth + "x" + "</div>" * depth
        import sys as _sys
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(10000)
        try:
            root = layout(html, "", width=400)
        finally:
            _sys.setrecursionlimit(old_limit)
        self.assertGreater(root.height, 0.0)


if __name__ == "__main__":
    unittest.main()
