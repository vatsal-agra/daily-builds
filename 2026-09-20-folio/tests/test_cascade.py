import unittest

from folio.cascade import collect_author_css, compute_styles
from folio.dom import find_first
from folio.html_parser import parse_html


def _styles(html):
    doc = parse_html(html)
    css = collect_author_css(doc)
    return doc, compute_styles(doc, css)


class TestCascadeBasics(unittest.TestCase):
    def test_ua_stylesheet_sets_display(self):
        doc, styles = _styles("<html><body><div>x</div><span>y</span></body></html>")
        div = find_first(doc, "div")
        span = find_first(doc, "span")
        self.assertEqual(styles[div].get("display"), "block")
        self.assertEqual(styles[span].get("display"), "inline")

    def test_head_and_script_are_display_none(self):
        doc, styles = _styles("<html><head><title>t</title></head><body>x</body></html>")
        head = find_first(doc, "head")
        self.assertEqual(styles[head].get("display"), "none")

    def test_inheritance_of_color(self):
        doc, styles = _styles(
            '<html><body style="color:green"><div><span>x</span></div></body></html>'
        )
        span = find_first(doc, "span")
        self.assertEqual(styles[span].get("color"), "green")

    def test_non_inherited_property_not_inherited(self):
        doc, styles = _styles(
            '<html><body style="background-color:yellow"><div>x</div></body></html>'
        )
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("background-color"), "transparent")

    def test_specificity_wins_over_source_order(self):
        html = (
            "<html><head><style>"
            ".x { color: red; } #y { color: blue; }"
            "</style></head><body><div id='y' class='x'>t</div></body></html>"
        )
        doc, styles = _styles(html)
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("color"), "blue")

    def test_later_rule_wins_on_tie(self):
        html = (
            "<html><head><style>.a{color:red} .a{color:blue}</style></head>"
            "<body><div class='a'>x</div></body></html>"
        )
        doc, styles = _styles(html)
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("color"), "blue")

    def test_important_beats_specificity(self):
        html = (
            "<html><head><style>"
            "#y { color: blue; } .x { color: red !important; }"
            "</style></head><body><div id='y' class='x'>t</div></body></html>"
        )
        doc, styles = _styles(html)
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("color"), "red")

    def test_inline_style_beats_author_rules(self):
        html = (
            "<html><head><style>#y { color: blue; }</style></head>"
            "<body><div id='y' style='color:green'>t</div></body></html>"
        )
        doc, styles = _styles(html)
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("color"), "green")


class TestShorthandExpansion(unittest.TestCase):
    def test_margin_shorthand_one_value(self):
        doc, styles = _styles('<html><body><div style="margin:10px">x</div></body></html>')
        div = find_first(doc, "div")
        for side in ("top", "right", "bottom", "left"):
            self.assertEqual(styles[div].get(f"margin-{side}"), "10px")

    def test_margin_shorthand_two_values(self):
        doc, styles = _styles('<html><body><div style="margin:10px 20px">x</div></body></html>')
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("margin-top"), "10px")
        self.assertEqual(styles[div].get("margin-right"), "20px")
        self.assertEqual(styles[div].get("margin-bottom"), "10px")
        self.assertEqual(styles[div].get("margin-left"), "20px")

    def test_margin_shorthand_four_values(self):
        doc, styles = _styles(
            '<html><body><div style="margin:1px 2px 3px 4px">x</div></body></html>'
        )
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("margin-top"), "1px")
        self.assertEqual(styles[div].get("margin-right"), "2px")
        self.assertEqual(styles[div].get("margin-bottom"), "3px")
        self.assertEqual(styles[div].get("margin-left"), "4px")

    def test_border_shorthand_order_independent(self):
        doc, styles = _styles(
            '<html><body><div style="border: red solid 2px">x</div></body></html>'
        )
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("border-top-width"), "2px")
        self.assertEqual(styles[div].get("border-top-style"), "solid")
        self.assertEqual(styles[div].get("border-top-color"), "red")
        # applied to all four sides
        self.assertEqual(styles[div].get("border-left-width"), "2px")

    def test_background_shorthand_plain_color(self):
        doc, styles = _styles('<html><body><div style="background: pink">x</div></body></html>')
        div = find_first(doc, "div")
        self.assertEqual(styles[div].get("background-color"), "pink")


class TestCurrentColor(unittest.TestCase):
    def test_currentcolor_case_insensitive(self):
        doc, styles = _styles(
            '<html><body style="color:green">'
            '<div style="border: 1px solid CURRENTCOLOR">x</div>'
            "</body></html>"
        )
        div = find_first(doc, "div")
        self.assertEqual(styles[div].resolved_color("border-top-color"), "green")


if __name__ == "__main__":
    unittest.main()
