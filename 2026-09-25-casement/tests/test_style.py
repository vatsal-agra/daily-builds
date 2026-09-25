import unittest

from casement.css_parser import parse_stylesheet
from casement.dom import find_first
from casement.html_parser import parse as parse_html
from casement.style import compute_styles


def styles_for(html, css):
    doc = parse_html(html)
    sheet = parse_stylesheet(css)
    return doc, compute_styles(doc, sheet)


class TestCascade(unittest.TestCase):
    def test_specificity_wins_over_source_order(self):
        doc, styles = styles_for(
            "<html><body><p id='x' class='y'>hi</p></body></html>",
            "#x { color: red; } .y { color: blue; }",
        )
        p = find_first(doc, "p")
        self.assertEqual(styles[p].raw("color"), "red")

    def test_source_order_wins_at_equal_specificity(self):
        doc, styles = styles_for(
            "<html><body><p class='y'>hi</p></body></html>",
            ".y { color: blue; } .y { color: green; }",
        )
        p = find_first(doc, "p")
        self.assertEqual(styles[p].raw("color"), "green")

    def test_important_overrides_specificity(self):
        doc, styles = styles_for(
            "<html><body><p id='x'>hi</p></body></html>",
            "#x { color: red; } p { color: blue !important; }",
        )
        p = find_first(doc, "p")
        self.assertEqual(styles[p].raw("color"), "blue")

    def test_inline_style_beats_id(self):
        doc, styles = styles_for(
            "<html><body><p id='x' style='color: green'>hi</p></body></html>",
            "#x { color: red; }",
        )
        p = find_first(doc, "p")
        self.assertEqual(styles[p].raw("color"), "green")

    def test_inheritance_of_color(self):
        doc, styles = styles_for(
            "<html><body><div style='color: purple'><p>hi</p></div></body></html>",
            "",
        )
        p = find_first(doc, "p")
        self.assertEqual(styles[p].raw("color"), "purple")

    def test_non_inherited_property_resets(self):
        doc, styles = styles_for(
            "<html><body><div style='padding: 20px'><p>hi</p></div></body></html>",
            "",
        )
        p = find_first(doc, "p")
        self.assertEqual(p and styles[p].raw("padding-top"), "0")

    def test_margin_shorthand_expansion(self):
        doc, styles = styles_for(
            "<html><body><div class='x'>hi</div></body></html>",
            ".x { margin: 1px 2px 3px 4px; }",
        )
        div = find_first(doc, "div")
        s = styles[div]
        self.assertEqual((s.raw("margin-top"), s.raw("margin-right"), s.raw("margin-bottom"), s.raw("margin-left")),
                         ("1px", "2px", "3px", "4px"))

    def test_margin_shorthand_two_values(self):
        doc, styles = styles_for(
            "<html><body><div class='x'>hi</div></body></html>",
            ".x { margin: 5px 10px; }",
        )
        div = find_first(doc, "div")
        s = styles[div]
        self.assertEqual((s.raw("margin-top"), s.raw("margin-right"), s.raw("margin-bottom"), s.raw("margin-left")),
                         ("5px", "10px", "5px", "10px"))

    def test_border_shorthand(self):
        doc, styles = styles_for(
            "<html><body><div class='x'>hi</div></body></html>",
            ".x { border: 2px solid red; }",
        )
        div = find_first(doc, "div")
        s = styles[div]
        self.assertEqual(s.raw("border-top-width"), "2px")
        self.assertEqual(s.raw("border-top-style"), "solid")
        self.assertEqual(s.raw("border-top-color"), "red")

    def test_ua_stylesheet_defaults(self):
        doc, styles = styles_for("<html><body><div>x</div><span>y</span></body></html>", "")
        self.assertEqual(styles[find_first(doc, "div")].keyword("display"), "block")
        self.assertEqual(styles[find_first(doc, "span")].keyword("display"), "inline")

    def test_background_shorthand_color(self):
        doc, styles = styles_for(
            "<html><body><div class='x'>x</div></body></html>",
            ".x { background: #9cf; }",
        )
        s = styles[find_first(doc, "div")]
        self.assertEqual(s.raw("background-color"), "#9cf")

    def test_flex_shorthand(self):
        doc, styles = styles_for(
            "<html><body><div class='x'>x</div></body></html>",
            ".x { flex: 2 1 100px; }",
        )
        s = styles[find_first(doc, "div")]
        self.assertEqual(s.raw("flex-grow"), "2")
        self.assertEqual(s.raw("flex-shrink"), "1")
        self.assertEqual(s.raw("flex-basis"), "100px")


if __name__ == "__main__":
    unittest.main()
