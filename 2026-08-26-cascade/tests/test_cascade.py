import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cascade.html_parser import parse
from cascade.cascade import compute_styles, parse_color


class TestCascade(unittest.TestCase):
    def test_specificity_cascade_order(self):
        doc = parse("""<html><body>
            <div id="w1"><p id="p1">t</p></div>
            <div id="w2"><p class="hi" id="p2">c</p></div>
            <div id="w3"><p id="special" class="hi">i</p></div>
            <div id="w4"><p id="p4" class="hi override">imp</p></div>
        </body></html>""")
        css = """
            p { width: 200px; }
            .hi { width: 250px; }
            #special { width: 300px; }
            p.hi.override { width: 220px !important; }
        """
        styles = compute_styles(doc, css)
        get = lambda pid: styles[[p for p in doc.find_all("p") if p.id() == pid][0]].get("width")
        self.assertEqual(get("p1"), "200px")
        self.assertEqual(get("p2"), "250px")
        self.assertEqual(get("special"), "300px")
        self.assertEqual(get("p4"), "220px")

    def test_inheritance(self):
        doc = parse("<div style='color:purple'><p>text <b>bold</b></p></div>")
        styles = compute_styles(doc, "")
        b = doc.find("b")
        self.assertEqual(styles[b].get("color"), "purple")

    def test_non_inherited_property_does_not_leak(self):
        doc = parse("<div style='margin-top:50px'><p>text</p></div>")
        styles = compute_styles(doc, "")
        p = doc.find("p")
        self.assertNotEqual(styles[p].get("margin-top"), "50px")

    def test_inline_style_beats_id_selector(self):
        doc = parse('<p id="x" style="color:green">t</p>')
        styles = compute_styles(doc, "#x { color: red }")
        self.assertEqual(styles[doc.find("p")].get("color"), "green")

    def test_important_beats_inline_style(self):
        doc = parse('<p style="color:green">t</p>')
        styles = compute_styles(doc, "p { color: red !important }")
        self.assertEqual(styles[doc.find("p")].get("color"), "red")

    def test_margin_shorthand_expansion(self):
        doc = parse("<div style='margin: 10px 5px'>x</div>")
        styles = compute_styles(doc, "")
        s = styles[doc.find("div")]
        self.assertEqual((s.get("margin-top"), s.get("margin-right"),
                           s.get("margin-bottom"), s.get("margin-left")),
                          ("10px", "5px", "10px", "5px"))

    def test_border_shorthand_order_independent(self):
        doc = parse("<div id='a' style='border: solid 2px red'></div>"
                    "<div id='b' style='border: 2px red solid'></div>")
        styles = compute_styles(doc, "")
        for div in doc.find_all("div"):
            s = styles[div]
            self.assertEqual(s.get("border-top-width"), "2px")
            self.assertEqual(s.get("border-top-style"), "solid")
            self.assertEqual(s.get("border-top-color"), "red")

    def test_ua_defaults_applied(self):
        doc = parse("<html><body><h1>Title</h1><span>inline</span></body></html>")
        styles = compute_styles(doc, "")
        self.assertEqual(styles[doc.find("h1")].get("display"), "block")
        self.assertEqual(styles[doc.find("h1")].get("font-weight"), "bold")
        self.assertEqual(styles[doc.find("span")].get("display"), "inline")

    def test_author_beats_ua_regardless_of_specificity(self):
        doc = parse("<html><body>text</body></html>")
        styles = compute_styles(doc, "* { margin: 0 }")
        self.assertEqual(styles[doc.find("body")].get("margin-top"), "0")

    def test_display_none_element_present_but_inert(self):
        doc = parse("<div style='display:none'><p>hidden</p></div>")
        styles = compute_styles(doc, "")
        div = doc.find("div")
        self.assertEqual(styles[div].get("display"), "none")

    def test_hex_colors(self):
        self.assertEqual(parse_color("#abc"), (170, 187, 204, 1.0))
        self.assertEqual(parse_color("#aabbcc"), (170, 187, 204, 1.0))

    def test_named_and_rgba_colors(self):
        self.assertEqual(parse_color("red"), (255, 0, 0, 1.0))
        self.assertEqual(parse_color("rgba(1, 2, 3, 0.5)"), (1.0, 2.0, 3.0, 0.5))

    def test_transparent_and_currentcolor(self):
        self.assertEqual(parse_color("transparent"), (0, 0, 0, 0))
        self.assertEqual(parse_color("currentcolor", current_color=(9, 9, 9)), (9, 9, 9, 1.0))

    def test_malformed_colors_never_raise(self):
        for bad in ["#zzz", "#12345", "#gggggg", "not-a-color", "rgb(bad)", "", "  "]:
            parse_color(bad)  # must not raise


if __name__ == "__main__":
    unittest.main()
