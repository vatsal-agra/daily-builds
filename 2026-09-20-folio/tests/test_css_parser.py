import unittest

from folio.css_parser import parse_css, parse_inline_style
from folio.dom import Element
from folio.html_parser import parse_html


def _el(html):
    doc = parse_html(html)
    from folio.dom import iter_descendants
    return next(iter_descendants(doc))


class TestSelectorMatching(unittest.TestCase):
    def test_type_selector(self):
        sheet = parse_css("div { color: red; }")
        el = _el("<div></div>")
        self.assertTrue(sheet.rules[0].selectors[0].matches(el))
        el2 = _el("<span></span>")
        self.assertFalse(sheet.rules[0].selectors[0].matches(el2))

    def test_class_and_id_selector(self):
        sheet = parse_css(".card#main { color: red; }")
        sel = sheet.rules[0].selectors[0]
        self.assertTrue(sel.matches(_el('<div class="card" id="main"></div>')))
        self.assertFalse(sel.matches(_el('<div class="card"></div>')))
        self.assertFalse(sel.matches(_el('<div id="main"></div>')))

    def test_universal_selector(self):
        sheet = parse_css("* { color: red; }")
        sel = sheet.rules[0].selectors[0]
        self.assertTrue(sel.matches(_el("<anything></anything>")))

    def test_descendant_combinator(self):
        doc = parse_html("<div><p><span>x</span></p></div>")
        from folio.dom import find_first
        span = find_first(doc, "span")
        sheet = parse_css("div span { color: red; }")
        self.assertTrue(sheet.rules[0].selectors[0].matches(span))
        sheet2 = parse_css("section span { color: red; }")
        self.assertFalse(sheet2.rules[0].selectors[0].matches(span))

    def test_child_combinator(self):
        doc = parse_html("<div><p><span>x</span></p></div>")
        from folio.dom import find_first
        span = find_first(doc, "span")
        # span's parent is <p>, not <div> -- child combinator must fail here.
        sheet = parse_css("div > span { color: red; }")
        self.assertFalse(sheet.rules[0].selectors[0].matches(span))
        sheet2 = parse_css("p > span { color: red; }")
        self.assertTrue(sheet2.rules[0].selectors[0].matches(span))

    def test_adjacent_sibling_combinator(self):
        doc = parse_html("<div><h1>t</h1><p>x</p></div>")
        from folio.dom import find_first
        p = find_first(doc, "p")
        sheet = parse_css("h1 + p { color: red; }")
        self.assertTrue(sheet.rules[0].selectors[0].matches(p))
        doc2 = parse_html("<div><h1>t</h1><span></span><p>x</p></div>")
        p2 = find_first(doc2, "p")
        self.assertFalse(sheet.rules[0].selectors[0].matches(p2))

    def test_comma_selector_list(self):
        sheet = parse_css("div, p { color: red; }")
        self.assertEqual(len(sheet.rules[0].selectors), 2)
        self.assertTrue(sheet.rules[0].selectors[0].matches(_el("<div></div>")))
        self.assertTrue(sheet.rules[0].selectors[1].matches(_el("<p></p>")))


class TestSpecificity(unittest.TestCase):
    def test_id_beats_class_beats_type(self):
        id_sel = parse_css("#x{}").rules
        # empty declarations are dropped by the parser, so build via matches directly
        from folio.css_parser import _parse_selector
        id_spec = _parse_selector("#x").specificity()
        class_spec = _parse_selector(".x").specificity()
        type_spec = _parse_selector("div").specificity()
        self.assertGreater(id_spec, class_spec)
        self.assertGreater(class_spec, type_spec)

    def test_compound_selector_specificity_adds_up(self):
        from folio.css_parser import _parse_selector
        spec = _parse_selector("div.card#main").specificity()
        self.assertEqual(spec, (1, 1, 1))

    def test_descendant_specificity_sums_both_sides(self):
        from folio.css_parser import _parse_selector
        spec = _parse_selector(".a .b").specificity()
        self.assertEqual(spec, (0, 2, 0))


class TestDeclarationParsing(unittest.TestCase):
    def test_basic_declarations(self):
        sheet = parse_css("div { color: red; margin: 10px; }")
        decls = {d.prop: d.value for d in sheet.rules[0].declarations}
        self.assertEqual(decls["color"], "red")
        self.assertEqual(decls["margin"], "10px")

    def test_important_flag(self):
        sheet = parse_css("div { color: red !important; }")
        d = sheet.rules[0].declarations[0]
        self.assertTrue(d.important)
        self.assertEqual(d.value, "red")

    def test_comments_stripped(self):
        sheet = parse_css("/* hi */ div { color: red; } /* bye */")
        self.assertEqual(len(sheet.rules), 1)

    def test_unclosed_rule_does_not_crash(self):
        sheet = parse_css("div { color: red;")
        self.assertEqual(len(sheet.rules), 1)

    def test_empty_rule_dropped(self):
        sheet = parse_css("div {}")
        self.assertEqual(len(sheet.rules), 0)

    def test_inline_style_parsing(self):
        decls = parse_inline_style("color: blue; margin: 5px")
        self.assertEqual({d.prop: d.value for d in decls}, {"color": "blue", "margin": "5px"})


if __name__ == "__main__":
    unittest.main()
