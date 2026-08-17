import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio.css_parser import parse_stylesheet, parse_selector, parse_declarations


class TestSelectorParsing(unittest.TestCase):
    def test_type_class_id(self):
        s = parse_selector("div.foo.bar#baz")
        c = s.compounds[0]
        self.assertEqual(c.tag, "div")
        self.assertEqual(sorted(c.classes), ["bar", "foo"])
        self.assertEqual(c.id, "baz")

    def test_universal(self):
        s = parse_selector("*")
        self.assertIsNone(s.compounds[0].tag)

    def test_descendant_and_child_combinators(self):
        s = parse_selector("ul li > a")
        self.assertEqual([c.tag for c in s.compounds], ["ul", "li", "a"])
        self.assertEqual(s.combinators, [" ", ">"])

    def test_attribute_selectors(self):
        s = parse_selector('a[href][target=_blank][data-x="a b"]')
        c = s.compounds[0]
        self.assertEqual(c.attrs[0], ("href", "", None))
        self.assertEqual(c.attrs[1], ("target", "=", "_blank"))
        self.assertEqual(c.attrs[2], ("data-x", "=", "a b"))

    def test_pseudo_class(self):
        s = parse_selector("li:first-child")
        self.assertEqual(s.compounds[0].pseudo, ["first-child"])

    def test_specificity_ordering(self):
        # id > multiple classes > type
        id_sel = parse_selector("#x")
        class_sel = parse_selector(".a.b.c")
        type_sel = parse_selector("div")
        self.assertGreater(id_sel.specificity(), class_sel.specificity())
        self.assertGreater(class_sel.specificity(), type_sel.specificity())

    def test_comma_separated_and_quoted_content_not_split(self):
        ss = parse_stylesheet('a, b { content: "x, y {not a rule}"; color: red; }')
        self.assertEqual(len(ss.rules), 1)
        self.assertEqual(len(ss.rules[0].selectors), 2)
        decls = {d.prop: d.value for d in ss.rules[0].declarations}
        self.assertEqual(decls["content"], '"x, y {not a rule}"')
        self.assertEqual(decls["color"], "red")


class TestDeclarationParsing(unittest.TestCase):
    def test_basic(self):
        decls = parse_declarations("color: red; width : 10px ;")
        self.assertEqual([(d.prop, d.value) for d in decls], [("color", "red"), ("width", "10px")])

    def test_important(self):
        decls = parse_declarations("color: red !important; width: 10px")
        self.assertTrue(decls[0].important)
        self.assertFalse(decls[1].important)

    def test_missing_trailing_semicolon(self):
        decls = parse_declarations("color: red")
        self.assertEqual(len(decls), 1)

    def test_rgb_with_commas_not_split_as_declarations(self):
        decls = parse_declarations("color: rgb(1, 2, 3); background: blue")
        self.assertEqual(decls[0].value, "rgb(1, 2, 3)")


class TestStylesheetParsing(unittest.TestCase):
    def test_multiple_rules(self):
        ss = parse_stylesheet("div { color: red; } p { color: blue; }")
        self.assertEqual(len(ss.rules), 2)

    def test_comments_stripped(self):
        ss = parse_stylesheet("/* x */ div /* y */ { color: red; /* z */ }")
        self.assertEqual(len(ss.rules), 1)
        self.assertEqual(ss.rules[0].declarations[0].value, "red")

    def test_media_query_skipped_gracefully(self):
        ss = parse_stylesheet("@media screen { p { color: red; } } div { color: blue; }")
        self.assertEqual(len(ss.rules), 1)
        self.assertEqual(ss.rules[0].selectors[0].compounds[0].tag, "div")

    def test_source_order_recorded(self):
        ss = parse_stylesheet("a{color:red} b{color:blue} c{color:green}")
        self.assertEqual([r.source_order for r in ss.rules], [0, 1, 2])

    def test_malformed_rule_no_crash(self):
        ss = parse_stylesheet("div { color: red")  # no closing brace
        self.assertEqual(len(ss.rules), 1)

    def test_empty_stylesheet(self):
        ss = parse_stylesheet("")
        self.assertEqual(ss.rules, [])


if __name__ == "__main__":
    unittest.main()
