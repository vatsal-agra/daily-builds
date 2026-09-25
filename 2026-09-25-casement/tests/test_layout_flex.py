import unittest

from casement.render import render
from tests.helpers import find_all_boxes, find_box


class TestFlexLayout(unittest.TestCase):
    def test_equal_flex_grow_splits_space_evenly(self):
        css = ".row { display: flex; } .item { flex: 1; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        self.assertEqual(len(items), 2)
        self.assertAlmostEqual(items[0].dims.width, items[1].dims.width, places=2)
        row = find_box(r.root_box, cls="row")
        total = sum(i.dims.width for i in items)
        self.assertAlmostEqual(total, row.dims.width, places=2)

    def test_proportional_flex_grow(self):
        # flex-basis: 0 (what the `flex: N` shorthand sets) makes the grow
        # ratio exact; leaving flex-basis: auto instead grows on top of
        # each item's own content width, which is correct CSS behavior but
        # would make this assertion about the *ratio* flaky by content size.
        css = ".row { display: flex; } .a { flex-grow: 1; flex-basis: 0; } .b { flex-grow: 3; flex-basis: 0; }"
        html = "<html><body><div class='row'><div class='a'>a</div><div class='b'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        a = find_box(r.root_box, cls="a")
        b = find_box(r.root_box, cls="b")
        self.assertAlmostEqual(b.dims.width, a.dims.width * 3, delta=1.0)

    def test_flex_shrink_when_overflowing(self):
        css = ".row { display: flex; width: 200px; } .item { width: 150px; flex-shrink: 1; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        total = sum(i.dims.width for i in items)
        self.assertAlmostEqual(total, 200, places=2)

    def test_no_shrink_when_flex_shrink_zero(self):
        css = ".row { display: flex; width: 100px; } .item { width: 80px; flex-shrink: 0; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        for it in items:
            self.assertAlmostEqual(it.dims.width, 80, places=2)

    def test_justify_content_space_between(self):
        css = ".row { display: flex; width: 300px; justify-content: space-between; } .item { width: 50px; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        row = find_box(r.root_box, cls="row")
        self.assertAlmostEqual(items[0].dims.x, row.dims.x, places=2)
        self.assertAlmostEqual(items[1].dims.x + items[1].dims.width, row.dims.x + row.dims.width, places=2)

    def test_justify_content_center(self):
        css = ".row { display: flex; width: 300px; justify-content: center; } .item { width: 50px; }"
        html = "<html><body><div class='row'><div class='item'>a</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        item = find_box(r.root_box, cls="item")
        row = find_box(r.root_box, cls="row")
        expected_x = row.dims.x + (300 - 50) / 2.0
        self.assertAlmostEqual(item.dims.x, expected_x, places=2)

    def test_align_items_stretch_default(self):
        css = ".row { display: flex; height: 100px; } .item { width: 20px; }"
        html = "<html><body><div class='row'><div class='item'>a</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        item = find_box(r.root_box, cls="item")
        self.assertAlmostEqual(item.dims.height, 100, places=2)

    def test_align_items_center(self):
        css = ".row { display: flex; height: 100px; align-items: center; } .item { width: 20px; height: 20px; }"
        html = "<html><body><div class='row'><div class='item'>a</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        item = find_box(r.root_box, cls="item")
        row = find_box(r.root_box, cls="row")
        self.assertAlmostEqual(item.dims.y, row.dims.y + 40, places=2)

    def test_flex_wrap(self):
        css = ".row { display: flex; flex-wrap: wrap; width: 100px; } .item { width: 60px; height: 10px; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        # 60 + 60 > 100, must wrap to 2 lines -> second item's y is below the first
        self.assertGreater(items[1].dims.y, items[0].dims.y)

    def test_flex_direction_column(self):
        css = ".col { display: flex; flex-direction: column; } .item { height: 30px; }"
        html = "<html><body><div class='col'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        self.assertAlmostEqual(items[1].dims.y - items[0].dims.y, 30, places=2)

    def test_flex_wrap_accounts_for_border_and_padding(self):
        # Regression: the wrap/justify math once measured only each item's
        # margin, not its border+padding too, so bordered/padded items
        # could overflow the container instead of wrapping.
        css = (
            ".row { display: flex; flex-wrap: wrap; width: 300px; } "
            ".item { flex: 1 1 100px; margin: 5px; padding: 10px; border: 2px solid black; }"
        )
        html = ("<html><body><div class='row'>"
                "<div class='item'>a</div><div class='item'>b</div><div class='item'>c</div>"
                "</div></body></html>")
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        row = find_box(r.root_box, cls="row")
        for it in items:
            bx, by, bw, bh = it.dims.border_box()
            mx, my, mw, mh = it.dims.margin_box()
            self.assertLessEqual(mx + mw, row.dims.x + row.dims.width + 0.5)

    def test_flex_horizontal_margin_included_in_main_axis_math(self):
        # Regression: item.dims.margin.left/right were left at 0 during the
        # basis/wrap pass (only assigned later), so a row of margined items
        # could overflow because the container thought there was more free
        # space than there really was.
        css = ".row { display: flex; width: 220px; } .item { width: 100px; margin: 0 10px; }"
        html = "<html><body><div class='row'><div class='item'>a</div><div class='item'>b</div></div></body></html>"
        r = render(html, extra_css=css, viewport_width=800)
        items = find_all_boxes(r.root_box, cls="item")
        row = find_box(r.root_box, cls="row")
        mx0, my0, mw0, mh0 = items[0].dims.margin_box()
        mx1, my1, mw1, mh1 = items[1].dims.margin_box()
        self.assertAlmostEqual(mx0, row.dims.x, places=1)
        self.assertLessEqual(mx1 + mw1, row.dims.x + row.dims.width + 0.5)

    def test_nested_content_inside_flex_item_positions_correctly(self):
        css = ".row { display: flex; } .item { padding: 10px; } #deep { margin: 0; }"
        html = ("<html><body><div class='row'>"
                "<div class='item'><p id='deep'>hello</p></div>"
                "</div></body></html>")
        r = render(html, extra_css=css, viewport_width=800)
        item = find_box(r.root_box, cls="item")
        deep = find_box(r.root_box, tag="p")
        row = find_box(r.root_box, cls="row")
        # item.dims.x/y are already item's *content* origin (padding
        # already applied relative to the row); 'deep' has no margin or
        # padding of its own, so it sits flush with item's content box,
        # which itself must be offset from the row by item's 10px padding.
        self.assertAlmostEqual(item.dims.x, row.dims.x + 10, places=2)
        self.assertAlmostEqual(item.dims.y, row.dims.y + 10, places=2)
        self.assertAlmostEqual(deep.dims.x, item.dims.x, places=2)
        self.assertAlmostEqual(deep.dims.y, item.dims.y, places=2)


if __name__ == "__main__":
    unittest.main()
