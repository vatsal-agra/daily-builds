import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio.html_parser import parse_html
from folio.cascade import compute_style_tree
from folio.dom import find_element


def styles_for(html, css=""):
    doc = parse_html("<html><body>%s</body></html>" % html)
    return doc, compute_style_tree(doc, [css])


class TestCascade(unittest.TestCase):
    def test_specificity_wins_over_source_order(self):
        doc, styles = styles_for(
            '<div id="x" class="a">t</div>',
            "#x { color: red; } .a { color: blue; }",
        )
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["color"][:3], (255, 0, 0))

    def test_later_source_order_wins_at_equal_specificity(self):
        doc, styles = styles_for("<div class='a'>t</div>", ".a { color: red; } .a { color: blue; }")
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["color"][:3], (0, 0, 255))

    def test_important_beats_specificity(self):
        doc, styles = styles_for(
            '<div id="x" class="a">t</div>',
            "#x { color: red; } .a { color: blue !important; }",
        )
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["color"][:3], (0, 0, 255))

    def test_inline_style_beats_id_selector(self):
        doc, styles = styles_for(
            '<div id="x" style="color: green;">t</div>', "#x { color: red; }"
        )
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["color"][:3], (0, 128, 0))

    def test_important_stylesheet_beats_inline(self):
        doc, styles = styles_for(
            '<div id="x" style="color: green;">t</div>', "#x { color: red !important; }"
        )
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["color"][:3], (255, 0, 0))

    def test_color_inherits(self):
        doc, styles = styles_for("<div style='color:blue'><p>t</p></div>")
        p = find_element(doc, "p")
        self.assertEqual(styles[p]["color"][:3], (0, 0, 255))

    def test_margin_does_not_inherit(self):
        doc, styles = styles_for("<div style='margin-top:20px'><p>t</p></div>")
        p = find_element(doc, "p")
        self.assertNotEqual(p, None)
        # p's own UA-stylesheet margin-top (1em == 16px here), NOT the
        # div's 20px and NOT 0 -- margin properties are not inherited.
        self.assertEqual(styles[p]["margin-top"].value, 16.0)

    def test_em_resolves_against_parent_font_size(self):
        doc, styles = styles_for(
            "<div style='font-size:20px'><p style='font-size:2em'>t</p></div>"
        )
        p = find_element(doc, "p")
        self.assertAlmostEqual(styles[p]["font-size"], 40.0)

    def test_descendant_selector_matches_grandchild(self):
        doc, styles = styles_for("<div><p><span>t</span></p></div>", "div span { color: red; }")
        span = find_element(doc, "span")
        self.assertEqual(styles[span]["color"][:3], (255, 0, 0))

    def test_child_combinator_does_not_match_grandchild(self):
        doc, styles = styles_for("<div><p><span>t</span></p></div>", "div > span { color: red; }")
        span = find_element(doc, "span")
        self.assertNotEqual(styles[span]["color"][:3], (255, 0, 0))

    def test_shorthand_margin_four_values(self):
        doc, styles = styles_for("<div style='margin: 1px 2px 3px 4px'>t</div>")
        div = find_element(doc, "div")
        st = styles[div]
        self.assertEqual(
            (st["margin-top"].value, st["margin-right"].value, st["margin-bottom"].value, st["margin-left"].value),
            (1.0, 2.0, 3.0, 4.0),
        )

    def test_shorthand_margin_two_values(self):
        doc, styles = styles_for("<div style='margin: 5px 10px'>t</div>")
        st = styles[find_element(doc, "div")]
        self.assertEqual(
            (st["margin-top"].value, st["margin-right"].value, st["margin-bottom"].value, st["margin-left"].value),
            (5.0, 10.0, 5.0, 10.0),
        )

    def test_border_shorthand(self):
        doc, styles = styles_for("<div style='border: 3px solid red'>t</div>")
        st = styles[find_element(doc, "div")]
        self.assertEqual(st["border-top-width"].value, 3.0)
        self.assertEqual(st["border-top-style"], "solid")
        self.assertEqual(st["border-top-color"][:3], (255, 0, 0))

    def test_border_style_none_computed_value_keeps_specified_width(self):
        # Per CSS2.1, the *computed* value of border-width is the specified
        # length regardless of border-style -- it's the *used* value (i.e.
        # what layout.py actually reserves space for) that zeroes out when
        # border-style is 'none'. See test_layout_block.py for that half.
        doc, styles = styles_for("<div style='border-top-width: 5px'>t</div>")
        st = styles[find_element(doc, "div")]
        self.assertEqual(st["border-top-width"].value, 5.0)
        self.assertEqual(st["border-top-style"], "none")

    def test_ua_stylesheet_defaults(self):
        doc, styles = styles_for("<div><h1>Hi</h1><span>x</span></div>")
        h1 = find_element(doc, "h1")
        span = find_element(doc, "span")
        div = find_element(doc, "div")
        self.assertEqual(styles[div]["display"], "block")
        self.assertEqual(styles[span]["display"], "inline")
        self.assertEqual(styles[h1]["font-weight"], "bold")
        self.assertAlmostEqual(styles[h1]["font-size"], 32.0)

    def test_percentage_width_kept_as_percent(self):
        doc, styles = styles_for("<div style='width: 50%'>t</div>")
        st = styles[find_element(doc, "div")]
        self.assertTrue(st["width"].is_percent)
        self.assertEqual(st["width"].value, 50.0)

    def test_attribute_equals_selector(self):
        doc, styles = styles_for('<input type="checkbox">', 'input[type=checkbox] { color: red; }')
        el = find_element(doc, "input")
        self.assertEqual(styles[el]["color"][:3], (255, 0, 0))

    def test_first_last_child_pseudo(self):
        doc, styles = styles_for(
            "<ul><li>a</li><li>b</li><li>c</li></ul>",
            "li:first-child { color: red; } li:last-child { color: blue; }",
        )
        lis = [n for n in doc.iter_element_descendants() if n.tag == "li"]
        self.assertEqual(styles[lis[0]]["color"][:3], (255, 0, 0))
        self.assertEqual(styles[lis[2]]["color"][:3], (0, 0, 255))
        self.assertEqual(styles[lis[1]]["color"][:3], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
