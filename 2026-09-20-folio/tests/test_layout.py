import unittest

from folio.engine import render_html
from folio.layout import Box, TextRun, char_width, line_height_px, parse_length


def _find(box, tag):
    if isinstance(box, Box) and box.node is not None and getattr(box.node, "tag", None) == tag:
        return box
    for c in box.children:
        if isinstance(c, Box):
            r = _find(c, tag)
            if r is not None:
                return r
    return None


def _find_all(box, tag, out=None):
    if out is None:
        out = []
    if isinstance(box, Box) and box.node is not None and getattr(box.node, "tag", None) == tag:
        out.append(box)
    for c in box.children:
        if isinstance(c, Box):
            _find_all(c, tag, out)
    return out


def _all_text_runs(box, out=None):
    if out is None:
        out = []
    if isinstance(box, Box):
        for c in box.children:
            if isinstance(c, TextRun):
                out.append(c)
            elif isinstance(c, Box):
                _all_text_runs(c, out)
    return out


class TestLengthParsing(unittest.TestCase):
    def test_px(self):
        self.assertEqual(parse_length("10px", 100), 10)

    def test_auto(self):
        self.assertEqual(parse_length("auto", 100), "auto")

    def test_percent_with_base(self):
        self.assertEqual(parse_length("50%", 200), 100)

    def test_percent_with_no_base_is_auto(self):
        """Regression for REVIEW.md finding #3: a percentage against an
        indefinite containing block must behave like 'auto', not 0."""
        self.assertEqual(parse_length("50%", None), "auto")

    def test_char_width_and_line_height_scale_with_font_size(self):
        self.assertEqual(char_width(16), round(16 * 0.6))
        self.assertEqual(line_height_px(16), round(16 * 1.2))


class TestBoxModel(unittest.TestCase):
    def test_border_box_sizing(self):
        html = (
            '<html><body style="margin:0">'
            '<div style="width:50%; box-sizing:border-box; border:10px solid black; '
            'padding:20px;">x</div></body></html>'
        )
        page = render_html(html, viewport_width=400)
        div = _find(page.root_box, "div")
        self.assertEqual(div.width, 200)  # 50% of 400
        self.assertEqual(div.content_width, 200 - 20 - 40)  # minus border+padding

    def test_content_box_sizing_is_default(self):
        html = '<html><body style="margin:0"><div style="width:100px; padding:10px;">x</div></body></html>'
        page = render_html(html, viewport_width=400)
        div = _find(page.root_box, "div")
        self.assertEqual(div.content_width, 100)
        self.assertEqual(div.width, 100 + 20)

    def test_margin_left_positions_the_box(self):
        """Regression for REVIEW.md finding #8: margin-left must shift a
        block box's x position, not just be recorded as a number."""
        html = (
            '<html><body style="margin:0">'
            '<div style="margin-left:50px; width:100px;">x</div></body></html>'
        )
        page = render_html(html, viewport_width=300)
        div = _find(page.root_box, "div")
        self.assertEqual(div.x, 50)

    def test_margin_auto_centers_a_block(self):
        html = (
            '<html><body style="margin:0">'
            '<div style="margin:0 auto; width:100px;">x</div></body></html>'
        )
        page = render_html(html, viewport_width=300)
        div = _find(page.root_box, "div")
        self.assertEqual(div.x, 100)  # (300 - 100) / 2

    def test_over_constrained_margin_solves_for_margin_right(self):
        """Regression for REVIEW.md finding #4."""
        html = (
            '<html><body style="margin:0">'
            '<div style="width:200px; border:2px solid black; padding:5px; '
            'margin:8px;">x</div></body></html>'
        )
        page = render_html(html, viewport_width=380)
        div = _find(page.root_box, "div")
        self.assertEqual(div.margin["left"], 8)
        self.assertEqual(div.margin["right"], 158)
        total = (
            div.margin["left"] + div.width + div.margin["right"]
        )
        self.assertEqual(total, 380)

    def test_sibling_margin_collapsing(self):
        html = (
            '<html><body style="margin:0">'
            '<div style="margin-bottom:30px;">A</div>'
            '<div style="margin-top:20px;">B</div>'
            "</body></html>"
        )
        page = render_html(html, viewport_width=200)
        divs = _find_all(page.root_box, "div")
        a, b = divs
        self.assertEqual(b.y, a.y + a.height + 30)  # max(30, 20), not 30+20

    def test_percentage_height_falls_back_to_content(self):
        """Regression for REVIEW.md finding #3 at the integration level:
        a percentage height must not clip content off the page."""
        html = '<html><body><div style="height:50%">line one two three</div></body></html>'
        page = render_html(html, viewport_width=300)
        self.assertGreater(page.height, 16)
        texts = [r.text for r in _all_text_runs(page.root_box)]
        self.assertIn("line", texts)
        self.assertIn("three", texts)


class TestTextWrapping(unittest.TestCase):
    def test_spaces_between_words_in_one_text_node(self):
        """Regression: spaces within a single text node must not be
        dropped (found and fixed during initial development)."""
        page = render_html("<html><body><h1>Folio Test Page</h1></body></html>", viewport_width=500)
        runs = _all_text_runs(page.root_box)
        words = [r.text for r in runs]
        self.assertEqual(words, ["Folio", "Test", "Page"])
        self.assertLess(runs[0].x + runs[0].width, runs[1].x)  # real gap exists

    def test_space_preserved_across_inline_element_boundary(self):
        page = render_html("<p>Hello <b>world</b></p>", viewport_width=300)
        runs = _all_text_runs(page.root_box)
        texts = [r.text for r in runs]
        self.assertEqual(texts, ["Hello", "world"])

    def test_no_space_without_boundary_whitespace(self):
        page = render_html("<p>Hello<b>world</b></p>", viewport_width=300)
        runs = _all_text_runs(page.root_box)
        # Adjacent with no whitespace between source nodes: still two runs,
        # but placed with no gap.
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].x + runs[0].width, runs[1].x)

    def test_wraps_long_paragraph_into_multiple_lines(self):
        html = (
            '<div style="width:100px">Hello world this is a longer sentence '
            "that should wrap across multiple lines</div>"
        )
        page = render_html(html, viewport_width=300)
        div = _find(page.root_box, "div")
        lines = [c for c in div.children[0].children]
        self.assertGreater(len(lines), 1)

    def test_overlong_single_word_placed_alone_without_hanging(self):
        html = '<div style="width:20px">Supercalifragilisticexpialidocious</div>'
        page = render_html(html, viewport_width=100)
        self.assertGreater(page.height, 0)

    def test_text_align_center(self):
        html = '<div style="width:200px; text-align:center;">hi</div>'
        page = render_html(html, viewport_width=200)
        run = _all_text_runs(page.root_box)[0]
        cw = char_width(16)
        expected_x = (200 - 2 * cw) // 2
        self.assertEqual(run.x, expected_x)

    def test_text_align_right(self):
        html = '<div style="width:200px; text-align:right;">hi</div>'
        page = render_html(html, viewport_width=200)
        run = _all_text_runs(page.root_box)[0]
        cw = char_width(16)
        self.assertEqual(run.x + run.width, 200)

    def test_br_forces_new_line(self):
        html = "<p>one<br>two</p>"
        page = render_html(html, viewport_width=300)
        p = _find(page.root_box, "p")
        lines = p.children[0].children
        self.assertEqual(len(lines), 2)


class TestMultiRootAndFragments(unittest.TestCase):
    def test_multi_root_fragment_renders_all_content(self):
        """Regression for REVIEW.md finding #2."""
        page = render_html("<div>First</div><div>Second</div>", viewport_width=300)
        divs = _find_all(page.root_box, "div")
        self.assertEqual(len(divs), 2)

    def test_empty_document_does_not_crash(self):
        page = render_html("", viewport_width=300)
        self.assertEqual(page.height, 0)


class TestFloats(unittest.TestCase):
    """Regression for REVIEW.md finding #9: floats must narrow a *sibling*
    block's inline content, not just their own descendants'."""

    def test_float_narrows_sibling_paragraph_lines(self):
        html = (
            '<html><body style="margin:10px">'
            '<div style="float:left; width:80px; height:60px;">LEFT</div>'
            '<div style="float:right; width:80px; height:60px;">RIGHT</div>'
            "<p>" + ("word " * 40) + "</p>"
            "</body></html>"
        )
        page = render_html(html, viewport_width=300)
        p = _find(page.root_box, "p")
        lines = p.children[0].children
        narrowed = [l for l in lines if l.y < 70]
        full_width = [l for l in lines if l.y >= 70]
        self.assertTrue(narrowed, "expected at least one line inset by the floats")
        self.assertTrue(full_width, "expected lines below the floats at full width")
        for line in narrowed:
            self.assertLess(line.width, 280)
        for line in full_width:
            self.assertEqual(line.width, 280)

    def test_clear_both_moves_below_floats(self):
        html = (
            '<html><body style="margin:0">'
            '<div style="float:left; width:50px; height:100px;">L</div>'
            '<div style="clear:both;">cleared</div>'
            "</body></html>"
        )
        page = render_html(html, viewport_width=200)
        cleared = _find_all(page.root_box, "div")[-1]
        self.assertGreaterEqual(cleared.y, 100)

    def test_float_establishes_its_own_bfc(self):
        """A float's internal floats/content must not leak into the page's
        ambient float context (CSS2.1 9.5). The outer <p> below IS a
        sibling of the *outer* 150px float in the same top-level BFC, so it
        is correctly narrowed to 150px (300 - 150) by that outer float --
        the regression this guards against is the *inner* 50px float
        additionally leaking out and narrowing it to 100px (300-150-50)."""
        html = (
            '<html><body style="margin:0">'
            '<div style="float:left; width:150px;">'
            '<div style="float:left; width:50px; height:20px;">inner</div>'
            "<p>inner text after an inner float</p>"
            "</div>"
            "<p>outer text, must not be narrowed by the inner float</p>"
            "</body></html>"
        )
        page = render_html(html, viewport_width=300)
        paragraphs = _find_all(page.root_box, "p")
        outer_p = paragraphs[-1]
        outer_line = outer_p.children[0].children[0]
        self.assertEqual(outer_line.width, 150)


if __name__ == "__main__":
    unittest.main()
