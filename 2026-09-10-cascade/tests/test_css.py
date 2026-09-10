import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from css_parser import parse_declarations, parse_selector, parse_stylesheet
from css_tokenizer import tokenize_css
from css_values import parse_color, parse_length
from dom import Element
from html_parser import parse_html
from selector import _match_nth


def child(parent, tag, **attrs):
    el = Element(tag, dict(attrs))
    parent.append_child(el)
    return el


class TokenizerTests(unittest.TestCase):
    def test_basic_tokens(self):
        toks = tokenize_css("div { color: red; }")
        kinds = [t.kind for t in toks]
        self.assertIn("IDENT", kinds)
        self.assertIn("PUNCT", kinds)

    def test_dimension_and_number(self):
        toks = tokenize_css("width: 12px; opacity: 0.5;")
        dims = [t for t in toks if t.kind == "DIMENSION"]
        self.assertEqual(dims[0].value, (12.0, "px"))
        nums = [t for t in toks if t.kind == "NUMBER"]
        self.assertAlmostEqual(nums[0].value, 0.5)

    def test_comments_stripped_in_stylesheet_parse(self):
        rules = parse_stylesheet("/* comment */ div { color: red; /* x */ }")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].declarations[0].value, "red")


class SelectorParseTests(unittest.TestCase):
    def test_type_selector(self):
        sel = parse_selector("div")
        self.assertEqual(sel.compounds[0].type, "div")

    def test_class_and_id(self):
        sel = parse_selector("div.foo#bar")
        c = sel.compounds[0]
        self.assertEqual(c.type, "div")
        self.assertEqual(c.classes, ["foo"])
        self.assertEqual(c.id, "bar")

    def test_descendant_combinator(self):
        sel = parse_selector("div p")
        self.assertEqual(len(sel.compounds), 2)
        self.assertEqual(sel.combinators, ["descendant"])

    def test_child_combinator(self):
        sel = parse_selector("ul > li")
        self.assertEqual(sel.combinators, ["child"])

    def test_adjacent_sibling(self):
        sel = parse_selector("h1 + p")
        self.assertEqual(sel.combinators, ["adjacent"])

    def test_attribute_selector(self):
        sel = parse_selector('a[href^="https"]')
        name, op, val = sel.compounds[0].attrs[0]
        self.assertEqual((name, op, val), ("href", "^=", "https"))

    def test_pseudo_class(self):
        sel = parse_selector("li:first-child")
        self.assertEqual(sel.compounds[0].pseudos, [("first-child", None)])

    def test_nth_child_arg(self):
        sel = parse_selector("li:nth-child(2n+1)")
        self.assertEqual(sel.compounds[0].pseudos[0][1], "2n+1")


class SpecificityTests(unittest.TestCase):
    def test_id_beats_classes(self):
        a = parse_selector("#foo").specificity()
        b = parse_selector(".a.b.c.d").specificity()
        self.assertGreater(a, b)

    def test_class_beats_type(self):
        a = parse_selector(".foo").specificity()
        b = parse_selector("div").specificity()
        self.assertGreater(a, b)

    def test_compound_sums(self):
        self.assertEqual(parse_selector("div.a#b").specificity(), (1, 1, 1))

    def test_universal_contributes_nothing(self):
        self.assertEqual(parse_selector("*").specificity(), (0, 0, 0))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        html = """
        <div id="wrap" class="outer">
          <ul class="list">
            <li class="item">one</li>
            <li class="item special">two</li>
            <li class="item">three</li>
          </ul>
          <p>text</p>
        </div>
        """
        self.doc = parse_html(html)
        from dom import find_all
        self.items = find_all(self.doc, "li")
        self.ul = find_all(self.doc, "ul")[0]
        self.p = find_all(self.doc, "p")[0]

    def test_class_match(self):
        sel = parse_selector(".special")
        matches = [li for li in self.items if sel.matches(li)]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text_content(), "two")

    def test_descendant_match(self):
        sel = parse_selector("div li")
        self.assertTrue(all(sel.matches(li) for li in self.items))

    def test_child_match_true_for_direct_parent(self):
        sel = parse_selector("ul > li")
        self.assertTrue(all(sel.matches(li) for li in self.items))

    def test_child_match_false_for_grandparent(self):
        sel = parse_selector("div > li")
        self.assertFalse(any(sel.matches(li) for li in self.items))

    def test_first_child_pseudo(self):
        sel = parse_selector("li:first-child")
        self.assertTrue(sel.matches(self.items[0]))
        self.assertFalse(sel.matches(self.items[1]))

    def test_last_child_pseudo(self):
        sel = parse_selector("li:last-child")
        self.assertTrue(sel.matches(self.items[-1]))
        self.assertFalse(sel.matches(self.items[0]))

    def test_adjacent_sibling_match(self):
        sel = parse_selector("ul + p")
        self.assertTrue(sel.matches(self.p))

    def test_nth_child_odd(self):
        sel = parse_selector("li:nth-child(odd)")
        matched = [li.text_content() for li in self.items if sel.matches(li)]
        self.assertEqual(matched, ["one", "three"])

    def test_multiple_class_selector_requires_all(self):
        sel = parse_selector(".item.special")
        matched = [li for li in self.items if sel.matches(li)]
        self.assertEqual(len(matched), 1)

    def test_not_pseudo_class(self):
        # regression: :not() used to be an unrecognized pseudo-class that
        # silently matched nothing at all, dropping the whole rule.
        sel = parse_selector(".item:not(.special)")
        matched = [li.text_content() for li in self.items if sel.matches(li)]
        self.assertEqual(matched, ["one", "three"])

    def test_not_pseudo_with_nth_child_arg(self):
        sel = parse_selector("li:not(:first-child)")
        matched = [li.text_content() for li in self.items if sel.matches(li)]
        self.assertEqual(matched, ["two", "three"])


class NthChildMathTests(unittest.TestCase):
    def test_odd_even(self):
        self.assertTrue(_match_nth("odd", 1))
        self.assertFalse(_match_nth("odd", 2))
        self.assertTrue(_match_nth("even", 4))

    def test_an_plus_b(self):
        # 2n+1 -> 1,3,5,...
        self.assertTrue(_match_nth("2n+1", 5))
        self.assertFalse(_match_nth("2n+1", 4))

    def test_bare_integer(self):
        self.assertTrue(_match_nth("3", 3))
        self.assertFalse(_match_nth("3", 4))


class DeclarationParseTests(unittest.TestCase):
    def test_basic_declarations(self):
        decls = parse_declarations("color: red; margin: 1px 2px;")
        self.assertEqual(decls[0].prop, "color")
        self.assertEqual(decls[0].value, "red")
        self.assertEqual(decls[1].value, "1px 2px")

    def test_important_flag(self):
        decls = parse_declarations("color: red !important;")
        self.assertTrue(decls[0].important)
        self.assertEqual(decls[0].value, "red")

    def test_value_with_parens_not_split_on_inner_comma(self):
        decls = parse_declarations("background: rgba(1,2,3,0.5);")
        self.assertEqual(decls[0].value, "rgba(1,2,3,0.5)")


class ValueParseTests(unittest.TestCase):
    def test_length_px(self):
        self.assertEqual(parse_length("10px", 16).px, 10.0)

    def test_length_em(self):
        self.assertEqual(parse_length("2em", 16).px, 32.0)

    def test_length_percent(self):
        self.assertEqual(parse_length("50%", 16).percent, 50.0)

    def test_length_auto(self):
        self.assertTrue(parse_length("auto", 16).auto)

    def test_length_resolve_percent(self):
        self.assertEqual(parse_length("50%", 16).resolve(200), 100.0)

    def test_color_named(self):
        self.assertEqual(parse_color("red"), (255, 0, 0, 255))

    def test_color_hex6(self):
        self.assertEqual(parse_color("#336699"), (0x33, 0x66, 0x99, 255))

    def test_color_hex3(self):
        self.assertEqual(parse_color("#fff"), (255, 255, 255, 255))

    def test_color_rgba(self):
        self.assertEqual(parse_color("rgba(10, 20, 30, 0.5)"), (10, 20, 30, 127))


if __name__ == "__main__":
    unittest.main()
