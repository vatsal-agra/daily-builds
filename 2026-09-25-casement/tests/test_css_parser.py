import unittest

from casement.css_parser import parse_selector, parse_stylesheet
from casement.dom import Element
from casement.html_parser import parse as parse_html


class TestSelectorParsing(unittest.TestCase):
    def test_type_selector_specificity(self):
        sel = parse_selector("div")
        self.assertEqual(sel.specificity(), (0, 0, 1))

    def test_id_and_class_specificity(self):
        sel = parse_selector("div.card#hero")
        self.assertEqual(sel.specificity(), (1, 1, 1))

    def test_descendant_and_child_combinators(self):
        doc = parse_html("<div><section><p id='x'>hi</p></section></div>")
        p = doc.iter().__next__()  # placeholder, replaced below
        from casement.dom import find_first
        p = find_first(doc, "p")
        section = find_first(doc, "section")
        div = find_first(doc, "div")

        descendant = parse_selector("div p")
        self.assertTrue(descendant.matches(p))

        child = parse_selector("div > p")
        self.assertFalse(child.matches(p))  # p is a grandchild of div, not a direct child

        direct_child = parse_selector("section > p")
        self.assertTrue(direct_child.matches(p))
        self.assertFalse(direct_child.matches(section))

    def test_pseudo_first_last_child(self):
        doc = parse_html("<ul><li>a</li><li>b</li><li>c</li></ul>")
        from casement.dom import find_all
        lis = find_all(doc, "li")
        first_sel = parse_selector("li:first-child")
        last_sel = parse_selector("li:last-child")
        self.assertTrue(first_sel.matches(lis[0]))
        self.assertFalse(first_sel.matches(lis[1]))
        self.assertTrue(last_sel.matches(lis[2]))
        self.assertFalse(last_sel.matches(lis[1]))


class TestStylesheetParsing(unittest.TestCase):
    def test_basic_rule_and_declarations(self):
        sheet = parse_stylesheet("div.card { color: red; padding: 4px; }")
        self.assertEqual(len(sheet.rules), 1)
        rule = sheet.rules[0]
        self.assertEqual(len(rule.selectors), 1)
        props = {d.prop: d.value for d in rule.declarations}
        self.assertEqual(props["color"], "red")
        self.assertEqual(props["padding"], "4px")

    def test_comma_selector_group(self):
        sheet = parse_stylesheet("h1, h2, .title { font-weight: bold; }")
        self.assertEqual(len(sheet.rules[0].selectors), 3)

    def test_important(self):
        sheet = parse_stylesheet("p { color: red !important; }")
        decl = sheet.rules[0].declarations[0]
        self.assertTrue(decl.important)
        self.assertEqual(decl.value, "red")

    def test_comments_stripped(self):
        sheet = parse_stylesheet("/* comment */ div { color: red; } /* trailing */")
        self.assertEqual(len(sheet.rules), 1)

    def test_at_rule_skipped_without_crashing(self):
        css = "@media (max-width: 600px) { div { color: blue; } } p { color: green; }"
        sheet = parse_stylesheet(css)
        # The @media body is opaque to this engine; only the trailing rule applies.
        self.assertEqual(len(sheet.rules), 1)
        self.assertEqual(sheet.rules[0].declarations[0].value, "green")

    def test_font_face_at_rule_with_semicolons_skipped(self):
        css = "@font-face { font-family: 'X'; src: url(a.woff); } p { color: green; }"
        sheet = parse_stylesheet(css)
        self.assertEqual(len(sheet.rules), 1)


if __name__ == "__main__":
    unittest.main()
