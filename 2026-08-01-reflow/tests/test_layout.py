import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.browser import render_page


def flatten(box, out=None):
    out = out if out is not None else []
    out.append(box)
    for child in box.children:
        flatten(child, out)
    return out


def find_boxes(root, tag):
    return [b for b in flatten(root) if b.node and getattr(b.node, 'name', None) == tag]


def all_text(root):
    words = []
    for b in flatten(root):
        if b.box_type == 'line':
            words.extend(f['text'] for f in b.fragments)
    return words


class TestBoxModel(unittest.TestCase):
    def test_fixed_width_and_padding_and_border(self):
        r = render_page('<div id="d">x</div>', 'div{width:100px;padding:10px;border:2px solid black;}', viewport_width=400)
        div = find_boxes(r.layout_root, 'div')[0]
        self.assertEqual(div.content_width, 100)
        self.assertEqual(div.border_box_width(), 100 + 20 + 4)

    def test_auto_width_fills_container(self):
        r = render_page('<div id="d">x</div>', 'div{margin:10px;}', viewport_width=400)
        div = find_boxes(r.layout_root, 'div')[0]
        self.assertEqual(div.content_width, 400 - 20)

    def test_sibling_margin_collapsing(self):
        r = render_page(
            '<div id="a">a</div><div id="b">b</div>',
            '#a{margin-bottom:30px;} #b{margin-top:10px;}',
            viewport_width=300,
        )
        boxes = find_boxes(r.layout_root, 'div')
        a, b = boxes[0], boxes[1]
        gap = b.y - (a.y + a.border_box_height())
        self.assertEqual(gap, 30, 'the larger of the two adjoining margins should win, not the sum')

    def test_margin_applies_before_inline_content_after_a_block(self):
        r = render_page(
            '<p id="a">a</p>text right after',
            '#a{margin-bottom:20px;}',
            viewport_width=300,
        )
        p = find_boxes(r.layout_root, 'p')[0]
        line_boxes = [b for b in flatten(r.layout_root) if b.box_type == 'line']
        trailing_line = [b for b in line_boxes if 'right' in [f['text'] for f in b.fragments]][0]
        self.assertEqual(trailing_line.y, p.y + p.border_box_height() + 20)


class TestInlineFlow(unittest.TestCase):
    def test_text_wraps_at_available_width(self):
        r = render_page('<p>one two three four five six seven eight</p>', 'body{width:100px;}', viewport_width=100)
        lines = [b for b in flatten(r.layout_root) if b.box_type == 'line']
        self.assertGreater(len(lines), 1)

    def test_all_words_survive_wrapping(self):
        words = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight']
        r = render_page('<p>' + ' '.join(words) + '</p>', 'body{width:80px;}', viewport_width=80)
        self.assertEqual(all_text(r.layout_root), words)

    def test_br_forces_a_line_break(self):
        r = render_page('<p>one<br>two</p>', viewport_width=300)
        lines = [b for b in flatten(r.layout_root) if b.box_type == 'line']
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].fragments[0]['text'], 'one')
        self.assertEqual(lines[1].fragments[0]['text'], 'two')

    def test_double_br_leaves_a_blank_line(self):
        r = render_page('<p>one<br><br>two</p>', viewport_width=300)
        lines = [b for b in flatten(r.layout_root) if b.box_type == 'line']
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1].fragments, [])

    def test_img_alt_text_renders_as_fallback(self):
        r = render_page('<img src="missing.png" alt="a cat photo">', viewport_width=300)
        self.assertIn('[a', all_text(r.layout_root))

    def test_display_none_element_produces_no_boxes(self):
        r = render_page('<div id="d">hidden</div><p>visible</p>', '#d{display:none;}', viewport_width=300)
        self.assertNotIn('hidden', all_text(r.layout_root))
        self.assertIn('visible', all_text(r.layout_root))

    def test_text_align_center(self):
        r = render_page('<p>hi</p>', 'p{text-align:center;}', viewport_width=200)
        line = [b for b in flatten(r.layout_root) if b.box_type == 'line'][0]
        self.assertGreater(line.fragments[0]['x'], 0)


class TestFlexbox(unittest.TestCase):
    def test_row_direction_places_items_left_to_right(self):
        r = render_page(
            '<div class="row"><div id="a">a</div><div id="b">b</div></div>',
            '.row{display:flex;} .row > div{width:50px;}',
            viewport_width=300,
        )
        a = find_boxes(r.layout_root, 'div')[1]
        b = find_boxes(r.layout_root, 'div')[2]
        self.assertLess(a.x, b.x)
        self.assertEqual(a.y, b.y)

    def test_flex_grow_distributes_remaining_space(self):
        r = render_page(
            '<div class="row"><div id="a">a</div><div id="b">b</div></div>',
            '.row{display:flex;width:300px;} #a{width:50px;} #b{flex-grow:1;}',
            viewport_width=400,
        )
        b = find_boxes(r.layout_root, 'div')[2]
        self.assertAlmostEqual(b.content_width, 250)

    def test_gap_adds_space_between_items(self):
        r = render_page(
            '<div class="row"><div id="a">a</div><div id="b">b</div></div>',
            '.row{display:flex;gap:20px;} .row > div{width:10px;}',
            viewport_width=300,
        )
        a = find_boxes(r.layout_root, 'div')[1]
        b = find_boxes(r.layout_root, 'div')[2]
        self.assertAlmostEqual(b.x - (a.x + a.border_box_width()), 20)

    def test_justify_content_center(self):
        r = render_page(
            '<div class="row"><div id="a">a</div></div>',
            '.row{display:flex;justify-content:center;width:200px;} #a{width:40px;}',
            viewport_width=300,
        )
        a = find_boxes(r.layout_root, 'div')[1]
        self.assertAlmostEqual(a.x, 80)  # (200 - 40) / 2

    def test_align_items_stretch_fills_cross_axis(self):
        r = render_page(
            '<div class="row"><div id="a">a</div></div>',
            '.row{display:flex;height:100px;} #a{width:40px;}',
            viewport_width=300,
        )
        a = find_boxes(r.layout_root, 'div')[1]
        self.assertAlmostEqual(a.border_box_height(), 100)

    def test_column_direction_stacks_vertically(self):
        r = render_page(
            '<div class="col"><div id="a">a</div><div id="b">b</div></div>',
            '.col{display:flex;flex-direction:column;width:100px;} .col > div{height:20px;}',
            viewport_width=300,
        )
        a = find_boxes(r.layout_root, 'div')[1]
        b = find_boxes(r.layout_root, 'div')[2]
        self.assertEqual(a.x, b.x)
        self.assertLess(a.y, b.y)

    def test_flex_item_text_is_positioned_at_its_final_location(self):
        # regression test for the fragment-translation bug found in REVIEW.md:
        # background/border moved to the final position but text stayed put.
        r = render_page(
            '<div class="col"><div id="a">first</div><div id="b">second</div></div>',
            '.col{display:flex;flex-direction:column;width:100px;}',
            viewport_width=300,
        )
        b_box = find_boxes(r.layout_root, 'div')[2]
        line = [l for l in flatten(b_box) if l.box_type == 'line'][0]
        self.assertAlmostEqual(line.fragments[0]['y'], b_box.y, delta=1.0)


if __name__ == '__main__':
    unittest.main()
