import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cascade import Cascade, expand_shorthand
from dom import find_all, find_first
from html_parser import parse_html


def compute(html, css):
    doc = parse_html(html)
    Cascade(css).compute_styles(doc)
    return doc


class ShorthandTests(unittest.TestCase):
    def test_margin_one_value(self):
        self.assertEqual(expand_shorthand("margin", "10px"),
                          {"margin-top": "10px", "margin-right": "10px",
                           "margin-bottom": "10px", "margin-left": "10px"})

    def test_margin_two_values(self):
        self.assertEqual(expand_shorthand("margin", "10px 20px"),
                          {"margin-top": "10px", "margin-right": "20px",
                           "margin-bottom": "10px", "margin-left": "20px"})

    def test_margin_four_values(self):
        self.assertEqual(expand_shorthand("margin", "1px 2px 3px 4px"),
                          {"margin-top": "1px", "margin-right": "2px",
                           "margin-bottom": "3px", "margin-left": "4px"})

    def test_border_shorthand(self):
        out = expand_shorthand("border", "2px solid red")
        self.assertEqual(out["border-top-width"], "2px")
        self.assertEqual(out["border-top-style"], "solid")
        self.assertEqual(out["border-top-color"], "red")
        self.assertEqual(out["border-left-color"], "red")

    def test_background_shorthand_takes_color(self):
        self.assertEqual(expand_shorthand("background", "#ff0000"),
                          {"background-color": "#ff0000"})

    def test_flex_single_number(self):
        self.assertEqual(expand_shorthand("flex", "2"),
                          {"flex-grow": "2", "flex-shrink": "1", "flex-basis": "0%"})

    def test_flex_none(self):
        self.assertEqual(expand_shorthand("flex", "none"),
                          {"flex-grow": "0", "flex-shrink": "0", "flex-basis": "auto"})

    def test_font_shorthand(self):
        out = expand_shorthand("font", "bold 14px Arial")
        self.assertEqual(out["font-weight"], "bold")
        self.assertEqual(out["font-size"], "14px")
        self.assertEqual(out["font-family"], "Arial")


class CascadeTests(unittest.TestCase):
    def test_type_selector_applies(self):
        doc = compute("<p>x</p>", "p { color: red; }")
        p = find_first(doc, "p")
        self.assertEqual(p.computed_style["color"], "red")

    def test_specificity_id_wins_over_class(self):
        doc = compute('<div id="a" class="b">x</div>',
                       "#a { color: red; } .b { color: blue; }")
        div = find_first(doc, "div")
        self.assertEqual(div.computed_style["color"], "red")

    def test_source_order_tiebreak(self):
        doc = compute("<p>x</p>", "p { color: red; } p { color: blue; }")
        p = find_first(doc, "p")
        self.assertEqual(p.computed_style["color"], "blue")

    def test_important_beats_specificity(self):
        doc = compute('<p id="x">x</p>', "#x { color: red; } p { color: blue !important; }")
        p = find_first(doc, "p")
        self.assertEqual(p.computed_style["color"], "blue")

    def test_inline_style_beats_author_rule(self):
        doc = compute('<p style="color: green;">x</p>', "p { color: red; }")
        p = find_first(doc, "p")
        self.assertEqual(p.computed_style["color"], "green")

    def test_color_inherits(self):
        doc = compute("<div><span>x</span></div>", "div { color: purple; }")
        span = find_first(doc, "span")
        self.assertEqual(span.computed_style["color"], "purple")

    def test_margin_does_not_inherit(self):
        doc = compute("<div><p>x</p></div>", "div { margin-top: 40px; }")
        p = find_first(doc, "p")
        self.assertNotEqual(p.computed_style.get("margin-top"), "40px")

    def test_child_overrides_inherited_value(self):
        doc = compute("<div><span>x</span></div>",
                       "div { color: purple; } span { color: orange; }")
        span = find_first(doc, "span")
        self.assertEqual(span.computed_style["color"], "orange")

    def test_ua_stylesheet_gives_bold_headings(self):
        doc = compute("<h1>Title</h1>", "")
        h1 = find_first(doc, "h1")
        self.assertEqual(h1.computed_style["font-weight"], "bold")

    def test_author_overrides_ua(self):
        doc = compute("<h1>Title</h1>", "h1 { font-weight: normal; }")
        h1 = find_first(doc, "h1")
        self.assertEqual(h1.computed_style["font-weight"], "normal")

    def test_display_none_element_still_gets_a_style(self):
        doc = compute('<div style="display:none">x</div>', "")
        div = find_first(doc, "div")
        self.assertEqual(div.computed_style["display"], "none")

    def test_descendant_selector_does_not_match_non_descendant(self):
        doc = compute("<div><p>x</p></div><p>y</p>", "div p { color: red; }")
        # the second <p> lives outside <div>, so it must stay the default color
        ps = find_all(doc, "p")
        self.assertEqual(ps[0].computed_style["color"], "red")
        self.assertNotEqual(ps[1].computed_style["color"], "red")

    def test_multiple_selectors_comma_separated(self):
        doc = compute("<h1>a</h1><h2>b</h2>", "h1, h2 { color: teal; }")
        h1 = find_first(doc, "h1")
        h2 = find_first(doc, "h2")
        self.assertEqual(h1.computed_style["color"], "teal")
        self.assertEqual(h2.computed_style["color"], "teal")


if __name__ == "__main__":
    unittest.main()
