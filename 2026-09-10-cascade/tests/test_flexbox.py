import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cascade import Cascade
from dom import Element
from html_parser import parse_html
from layout import build_root


def layout(html, css, width=600):
    doc = parse_html(html)
    Cascade(css).compute_styles(doc)
    html_el = doc.children[0]
    return build_root(html_el, width)


def flex_items(root):
    for b in root.iter_boxes():
        if b.box_type == "flex":
            return b.children
    return []


class FlexBasicTests(unittest.TestCase):
    def test_row_items_flow_left_to_right(self):
        root = layout(
            "<div class='f'><div style='width:50px'></div><div style='width:80px'></div></div>",
            "body{margin:0} .f{display:flex}", width=600)
        items = flex_items(root)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].x, 0.0)
        self.assertEqual(items[1].x, 50.0)

    def test_column_items_stack_top_to_bottom(self):
        root = layout(
            "<div class='f'><div style='height:20px'></div><div style='height:30px'></div></div>",
            "body{margin:0} .f{display:flex;flex-direction:column}", width=600)
        items = flex_items(root)
        self.assertEqual(items[0].y, 0.0)
        self.assertEqual(items[1].y, 20.0)

    def test_flex_grow_distributes_free_space(self):
        root = layout(
            "<div class='f'><div style='width:100px'></div>"
            "<div class='g' style='width:100px'></div></div>",
            "body{margin:0} .f{display:flex;width:500px} .g{flex-grow:1}", width=600)
        items = flex_items(root)
        # 500 total - 100 (fixed) = 400 leftover, all going to the flex-grow item
        self.assertEqual(items[0].width, 100.0)
        self.assertEqual(items[1].width, 400.0)

    def test_flex_grow_proportional_between_two_growers(self):
        root = layout(
            "<div class='f'><div class='g1'></div><div class='g2'></div></div>",
            "body{margin:0} .f{display:flex;width:300px} .g1{flex-grow:1} .g2{flex-grow:2}",
            width=600)
        items = flex_items(root)
        self.assertAlmostEqual(items[0].width, 100.0, delta=1.0)
        self.assertAlmostEqual(items[1].width, 200.0, delta=1.0)

    def test_flex_shrink_reduces_oversized_items(self):
        root = layout(
            "<div class='f'><div style='width:400px'></div><div style='width:400px'></div></div>",
            "body{margin:0} .f{display:flex;width:300px}", width=600)
        items = flex_items(root)
        self.assertLess(items[0].width + items[1].width, 800)
        self.assertAlmostEqual(items[0].width, items[1].width, delta=0.01)

    def test_justify_content_center(self):
        root = layout(
            "<div class='f'><div style='width:100px'></div></div>",
            "body{margin:0} .f{display:flex;width:400px;justify-content:center}", width=600)
        items = flex_items(root)
        self.assertAlmostEqual(items[0].x, 150.0)

    def test_justify_content_space_between(self):
        root = layout(
            "<div class='f'><div style='width:50px'></div><div style='width:50px'></div></div>",
            "body{margin:0} .f{display:flex;width:300px;justify-content:space-between}",
            width=600)
        items = flex_items(root)
        self.assertEqual(items[0].x, 0.0)
        self.assertEqual(items[1].x, 250.0)

    def test_align_items_stretch_is_default(self):
        root = layout(
            "<div class='f'><div style='width:50px'></div></div>",
            "body{margin:0} .f{display:flex;height:200px}", width=600)
        items = flex_items(root)
        self.assertEqual(items[0].height, 200.0)

    def test_align_items_center(self):
        root = layout(
            "<div class='f'><div style='width:50px;height:20px'></div></div>",
            "body{margin:0} .f{display:flex;height:200px;align-items:center}", width=600)
        items = flex_items(root)
        self.assertAlmostEqual(items[0].y, 90.0)

    def test_margin_adds_gap_between_flex_items(self):
        root = layout(
            "<div class='f'><div style='width:50px'></div>"
            "<div style='width:50px;margin-left:20px'></div></div>",
            "body{margin:0} .f{display:flex}", width=600)
        items = flex_items(root)
        self.assertEqual(items[1].x, 50.0 + 20.0)


if __name__ == "__main__":
    unittest.main()
