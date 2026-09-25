import unittest

from casement.render import render
from tests.helpers import find_box


class TestBlockLayout(unittest.TestCase):
    def test_auto_width_fills_container(self):
        r = render("<html><body><div class='x'>hi</div></body></html>", viewport_width=800)
        box = find_box(r.root_box, cls="x")
        # body has an 8px default margin on each side (UA stylesheet)
        self.assertAlmostEqual(box.dims.width, 800 - 16, places=3)

    def test_explicit_width_and_box_sizing_content_box(self):
        css = ".x { width: 200px; padding: 10px; border: 5px solid black; }"
        r = render("<html><body><div class='x'>hi</div></body></html>", extra_css=css, viewport_width=800)
        box = find_box(r.root_box, cls="x")
        self.assertAlmostEqual(box.dims.width, 200, places=3)
        bx, by, bw, bh = box.dims.border_box()
        self.assertAlmostEqual(bw, 200 + 20 + 10, places=3)  # content + padding*2 + border*2

    def test_box_sizing_border_box(self):
        css = ".x { width: 200px; padding: 10px; border: 5px solid black; box-sizing: border-box; }"
        r = render("<html><body><div class='x'>hi</div></body></html>", extra_css=css, viewport_width=800)
        box = find_box(r.root_box, cls="x")
        bx, by, bw, bh = box.dims.border_box()
        self.assertAlmostEqual(bw, 200, places=3)

    def test_margin_auto_centers_block(self):
        css = ".x { width: 100px; margin-left: auto; margin-right: auto; }"
        r = render("<html><body><div class='x'>hi</div></body></html>", extra_css=css, viewport_width=800)
        box = find_box(r.root_box, cls="x")
        body = find_box(r.root_box, tag="body")
        available = body.dims.width - 100
        self.assertAlmostEqual(box.dims.margin.left, available / 2.0, places=3)
        self.assertAlmostEqual(box.dims.margin.right, available / 2.0, places=3)
        # Regression: the box's *position* (not just its reported margin
        # value) must reflect the centering -- it was computed before the
        # auto margin was resolved and never corrected.
        self.assertAlmostEqual(box.dims.x, body.dims.x + available / 2.0, places=3)

    def test_margin_left_affects_position_not_just_reported_value(self):
        # Regression: _resolve_edges only *returns* left/right margin;
        # layout_children_in_flow discarded that return value and computed
        # the child's x using the still-zero Dimensions() default, so
        # dims.margin.left ended up correct while dims.x quietly wasn't.
        css = ".x { margin-left: 50px; }"
        r = render("<html><body><div class='x'>hi</div></body></html>", extra_css=css, viewport_width=400)
        box = find_box(r.root_box, cls="x")
        body = find_box(r.root_box, tag="body")
        self.assertAlmostEqual(box.dims.x, body.dims.x + 50, places=3)

    def test_box_sizing_border_box_applies_to_height_too(self):
        # Regression: box-sizing: border-box subtracted padding/border from
        # an explicit width but not from an explicit height.
        css = ".x { height: 30px; padding: 5px; border: 3px solid black; box-sizing: border-box; }"
        r = render("<html><body><div class='x'>x</div></body></html>", extra_css=css, viewport_width=400)
        box = find_box(r.root_box, cls="x")
        _, _, _, border_box_h = box.dims.border_box()
        self.assertAlmostEqual(border_box_h, 30, places=3)
        self.assertAlmostEqual(box.dims.height, 30 - 2 * 5 - 2 * 3, places=3)

    def test_adjacent_sibling_margin_collapsing(self):
        css = ".a { margin-bottom: 30px; } .b { margin-top: 10px; }"
        html = "<html><body><div class='a'>a</div><div class='b'>b</div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        a = find_box(r.root_box, cls="a")
        b = find_box(r.root_box, cls="b")
        gap = b.dims.y - (a.dims.y + a.dims.height)
        self.assertAlmostEqual(gap, 30, places=3)  # max(30, 10), not 40

    def test_root_level_margin_collapsing_shows_up_as_top_of_page_space(self):
        # A first child's margin-top collapsing through a border/padding-
        # free <body> has nowhere left to escape to -- real browsers still
        # render it as blank space above the very first pixel of the page,
        # rather than discarding it, once body's own margin is reset to 0
        # (the extremely common `body { margin: 0 }` reset pattern).
        css = "body { margin: 0; } .child { margin-top: 20px; }"
        html = "<html><body><div class='child'>x</div></body></html>"
        r = render(html, extra_css=css, viewport_width=400)
        child = find_box(r.root_box, cls="child")
        body = find_box(r.root_box, tag="body")
        self.assertAlmostEqual(body.dims.y, 20, places=3)
        self.assertAlmostEqual(child.dims.y, 20, places=3)

    def test_parent_first_child_margin_collapsing(self):
        css = ".parent { background: yellow; } .child { margin-top: 40px; }"
        html = "<html><body><div class='parent'><div class='child'>x</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        parent = find_box(r.root_box, cls="parent")
        child = find_box(r.root_box, cls="child")
        # The child's margin collapses through the borderless/paddingless
        # parent, so the child's border-box top equals the parent's content top.
        self.assertAlmostEqual(child.dims.y, parent.dims.y, places=3)

    def test_no_collapsing_when_parent_has_padding(self):
        css = ".parent { padding-top: 5px; } .child { margin-top: 40px; }"
        html = "<html><body><div class='parent'><div class='child'>x</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        parent = find_box(r.root_box, cls="parent")
        child = find_box(r.root_box, cls="child")
        self.assertAlmostEqual(child.dims.y - parent.dims.y, 40, places=3)

    def test_percentage_width(self):
        css = ".outer { width: 400px; } .inner { width: 50%; }"
        html = "<html><body><div class='outer'><div class='inner'>x</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        inner = find_box(r.root_box, cls="inner")
        self.assertAlmostEqual(inner.dims.width, 200, places=3)

    def test_min_max_width_clamped(self):
        css = ".x { width: 50px; min-width: 100px; }"
        html = "<html><body><div class='x'>x</div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        box = find_box(r.root_box, cls="x")
        self.assertAlmostEqual(box.dims.width, 100, places=3)

    def test_text_wraps_at_container_width(self):
        html = "<html><body><p>" + " ".join(["word"] * 40) + "</p></body></html>"
        r = render(html, viewport_width=200)
        p = find_box(r.root_box, tag="p")
        anon = p.children[0]
        self.assertGreater(len(anon.lines), 1)
        for line in anon.lines:
            if line.items:
                last = line.items[-1]
                self.assertLessEqual(last[0] + last[4], anon.dims.width + 1.0)

    def test_ordered_list_numbering(self):
        html = "<html><body><ol><li>a</li><li>b</li><li>c</li></ol></body></html>"
        r = render(html, viewport_width=400)
        from tests.helpers import find_all_boxes
        lis = find_all_boxes(r.root_box, tag="li")
        markers = [li.children[0].ifc_items[0][1] for li in lis]
        self.assertEqual(markers, ["1.", "2.", "3."])

    def test_text_align_center(self):
        html = "<html><body><p style='text-align:center'>hi</p></body></html>"
        r = render(html, viewport_width=400)
        p = find_box(r.root_box, tag="p")
        anon = p.children[0]
        line = anon.lines[0]
        x, kind, text, style, w, h = line.items[0]
        self.assertGreater(x, 0)


if __name__ == "__main__":
    unittest.main()
