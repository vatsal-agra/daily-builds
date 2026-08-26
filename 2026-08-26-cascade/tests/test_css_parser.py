import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cascade.html_parser import parse as parse_html
from cascade.css_parser import parse_stylesheet


class TestCssParser(unittest.TestCase):
    def test_basic_rule(self):
        sheet = parse_stylesheet("div { color: red; font-size: 12px }")
        self.assertEqual(len(sheet.rules), 1)
        decls = {d.prop: d.value for d in sheet.rules[0].declarations}
        self.assertEqual(decls, {"color": "red", "font-size": "12px"})

    def test_important(self):
        sheet = parse_stylesheet("div { color: red !important; }")
        d = sheet.rules[0].declarations[0]
        self.assertTrue(d.important)
        self.assertEqual(d.value, "red")

    def test_comma_selector_list_shares_declarations(self):
        sheet = parse_stylesheet("h1, h2, h3 { color: red }")
        self.assertEqual(len(sheet.rules), 3)
        for r in sheet.rules:
            self.assertEqual(r.declarations[0].value, "red")

    def test_specificity_ordering(self):
        sheet = parse_stylesheet("* { a: 1 } div { a: 2 } .c { a: 3 } #i { a: 4 }")
        specs = [r.selector.specificity() for r in sheet.rules]
        self.assertEqual(specs, sorted(specs))  # each strictly more specific than the last

    def test_child_vs_descendant_combinator(self):
        sheet = parse_stylesheet("div > p { a: 1 } div p { a: 2 }")
        child_sel, desc_sel = sheet.rules[0].selector, sheet.rules[1].selector
        self.assertEqual(child_sel.combinators, [">"])
        self.assertEqual(desc_sel.combinators, [" "])

    def test_child_combinator_matches_direct_child_only(self):
        doc = parse_html("<div><section><p id='a'>x</p></section><p id='b'>y</p></div>")
        sheet = parse_stylesheet("div > p { color: red }")
        sel = sheet.rules[0].selector
        pa = doc.find("section").find("p")
        pb = [p for p in doc.find_all("p") if p.id() == "b"][0]
        self.assertFalse(sel.matches(pa))
        self.assertTrue(sel.matches(pb))

    def test_malformed_css_never_raises(self):
        bad_inputs = [
            "div { color: red",
            "div {",
            "div {}",
            "div, p, { color: red }",
            "} p { color: blue }",
            "@media (max-width: 1px) { div { color: red } } p { color: blue }",
            "@import url(x.css); p { color: green }",
        ]
        for css in bad_inputs:
            parse_stylesheet(css)  # must not raise

    def test_at_rule_is_skipped_entirely(self):
        sheet = parse_stylesheet("@media (max-width: 1px) { div { color: red } } p { color: blue }")
        self.assertEqual(len(sheet.rules), 1)
        self.assertEqual(sheet.rules[0].declarations[0].value, "blue")

    def test_type_selector_is_case_insensitive(self):
        doc = parse_html("<html><body><DIV>x</DIV></body></html>")
        div = doc.find("div")
        sheet = parse_stylesheet("DIV { color: red }")
        self.assertTrue(sheet.rules[0].selector.matches(div))

    def test_class_selector_is_case_sensitive(self):
        doc = parse_html('<div class="Foo">x</div>')
        div = doc.find("div")
        sheet = parse_stylesheet(".Foo { color: red } .foo { color: blue }")
        self.assertTrue(sheet.rules[0].selector.matches(div))
        self.assertFalse(sheet.rules[1].selector.matches(div))

    def test_attribute_selectors(self):
        doc = parse_html('<input type="text" required>')
        el = doc.find("input")
        sheet = parse_stylesheet("[required] { a: 1 } input[type=text] { a: 2 } input[type=checkbox] { a: 3 }")
        self.assertTrue(sheet.rules[0].selector.matches(el))
        self.assertTrue(sheet.rules[1].selector.matches(el))
        self.assertFalse(sheet.rules[2].selector.matches(el))

    def test_nth_child_odd_even(self):
        doc = parse_html("<ul><li>1</li><li>2</li><li>3</li><li>4</li></ul>")
        lis = doc.find_all("li")
        odd = parse_stylesheet("li:nth-child(odd) { a: 1 }").rules[0].selector
        even = parse_stylesheet("li:nth-child(even) { a: 1 }").rules[0].selector
        self.assertEqual([odd.matches(li) for li in lis], [True, False, True, False])
        self.assertEqual([even.matches(li) for li in lis], [False, True, False, True])

    def test_sibling_combinator_selector_matches_nothing(self):
        # Explicitly unsupported (see css_parser.py docstring) -> the rule
        # must be dropped, not silently mismatch something else.
        sheet = parse_stylesheet("div + p { color: red }")
        self.assertEqual(len(sheet.rules), 0)


if __name__ == "__main__":
    unittest.main()
