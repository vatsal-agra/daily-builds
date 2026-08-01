import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.css_parser import parse_stylesheet, specificity


class TestSelectors(unittest.TestCase):
    def test_type_class_id_compound(self):
        sheet = parse_stylesheet('div.card#main { color: red; }')
        steps = sheet.rules[0].selectors[0]
        combinator, compound = steps[0]
        self.assertIsNone(combinator)
        self.assertEqual(compound.type_name, 'div')
        self.assertEqual(compound.id, 'main')
        self.assertEqual(compound.classes, {'card'})

    def test_comma_separated_group_produces_multiple_selectors(self):
        sheet = parse_stylesheet('h1, h2, .x { color: red; }')
        self.assertEqual(len(sheet.rules[0].selectors), 3)

    def test_descendant_and_child_combinators_parsed(self):
        sheet = parse_stylesheet('div p { color: red; } div > span { color: blue; }')
        desc_steps = sheet.rules[0].selectors[0]
        child_steps = sheet.rules[1].selectors[0]
        self.assertEqual(desc_steps[1][0], ' ')
        self.assertEqual(child_steps[1][0], '>')

    def test_specificity_ordering(self):
        sheet = parse_stylesheet('a{} .a{} #a{} div.a{}')
        specs = [specificity(r.selectors[0]) for r in sheet.rules]
        self.assertEqual(specs, [(0, 0, 1), (0, 1, 0), (1, 0, 0), (0, 1, 1)])


class TestDeclarations(unittest.TestCase):
    def test_basic_declaration_parsing(self):
        sheet = parse_stylesheet('p { color: red; font-size: 12px; }')
        self.assertEqual(sheet.rules[0].declarations['color'], ('red', False))
        self.assertEqual(sheet.rules[0].declarations['font-size'], ('12px', False))

    def test_important_flag_detected_and_stripped(self):
        sheet = parse_stylesheet('p { color: red !important; }')
        self.assertEqual(sheet.rules[0].declarations['color'], ('red', True))

    def test_later_declaration_of_same_prop_wins_within_rule(self):
        sheet = parse_stylesheet('p { color: red; color: blue; }')
        self.assertEqual(sheet.rules[0].declarations['color'], ('blue', False))

    def test_source_order_recorded_per_rule(self):
        sheet = parse_stylesheet('a{} b{} c{}')
        self.assertEqual([r.order for r in sheet.rules], [0, 1, 2])


class TestRobustness(unittest.TestCase):
    def test_at_rule_block_is_skipped_without_crashing(self):
        sheet = parse_stylesheet('@media (max-width: 600px) { p { color: red; } } p { color: blue; }')
        # only the top-level `p` rule outside the @media block is kept
        self.assertEqual(len(sheet.rules), 1)
        self.assertEqual(sheet.rules[0].declarations['color'], ('blue', False))

    def test_at_rule_without_block_is_skipped(self):
        sheet = parse_stylesheet("@import 'x.css'; p { color: red; }")
        self.assertEqual(len(sheet.rules), 1)

    def test_comments_are_stripped(self):
        sheet = parse_stylesheet('/* comment */ p { color: red; /* inline */ }')
        self.assertEqual(sheet.rules[0].declarations['color'], ('red', False))

    def test_missing_closing_brace_does_not_crash(self):
        sheet = parse_stylesheet('p { color: red')
        self.assertEqual(len(sheet.rules), 1)

    def test_empty_stylesheet(self):
        sheet = parse_stylesheet('')
        self.assertEqual(sheet.rules, [])


if __name__ == '__main__':
    unittest.main()
