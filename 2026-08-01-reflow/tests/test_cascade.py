import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.cascade import compute_styles, to_px
from reflow.html_parser import parse


def styled(html, css=''):
    doc = parse(html)
    styles, sheet = compute_styles(doc, css)
    return doc, styles, sheet


class TestSpecificityAndOrder(unittest.TestCase):
    def test_id_beats_class_beats_type(self):
        doc, styles, _ = styled(
            '<p id="x" class="y">t</p>',
            'p{color:red;} .y{color:green;} #x{color:blue;}',
        )
        p = doc.find_all('p')[0]
        self.assertEqual(styles[p].get('color'), 'blue')

    def test_later_source_order_wins_at_equal_specificity(self):
        doc, styles, _ = styled('<p>t</p>', 'p{color:red;} p{color:blue;}')
        p = doc.find_all('p')[0]
        self.assertEqual(styles[p].get('color'), 'blue')

    def test_important_beats_higher_specificity(self):
        doc, styles, _ = styled(
            '<p id="x">t</p>',
            'p{color:blue !important;} #x{color:red;}',
        )
        p = doc.find_all('p')[0]
        self.assertEqual(styles[p].get('color'), 'blue')

    def test_child_combinator_only_matches_direct_child(self):
        doc, styles, _ = styled(
            '<div><p>direct</p><section><p>nested</p></section></div>',
            'div > p { color: red; }',
        )
        ps = doc.find_all('p')
        self.assertEqual(styles[ps[0]].get('color'), 'red')
        self.assertEqual(styles[ps[1]].get('color'), 'black')

    def test_inline_style_beats_stylesheet_rule(self):
        doc, styles, _ = styled('<p id="x" style="color:blue">t</p>', '#x{color:red;}')
        p = doc.find_all('p')[0]
        self.assertEqual(styles[p].get('color'), 'blue')


class TestInheritance(unittest.TestCase):
    def test_color_inherits_to_children(self):
        doc, styles, _ = styled('<div><b>x</b></div>', 'div{color:green;}')
        b = doc.find_all('b')[0]
        self.assertEqual(styles[b].get('color'), 'green')

    def test_explicit_declaration_on_element_wins_over_inheritance(self):
        doc, styles, _ = styled('<div><b>x</b></div>', 'div{color:green;} b{color:red;}')
        b = doc.find_all('b')[0]
        self.assertEqual(styles[b].get('color'), 'red')

    def test_margin_does_not_inherit(self):
        # <div> has no default margin in the UA stylesheet (unlike <p>), so
        # this isolates inheritance behavior from UA-stylesheet defaults.
        doc, styles, _ = styled('<div id="outer"><div id="inner">x</div></div>', '#outer{margin-top:20px;}')
        inner = doc.find_all('div')[1]
        self.assertEqual(to_px(styles[inner].get('margin-top')), 0.0)

    def test_text_node_reuses_parent_computed_style(self):
        doc, styles, _ = styled('<p>hello</p>', 'p{color:red;}')
        p = doc.find_all('p')[0]
        text_node = p.children[0]
        self.assertEqual(styles[text_node].get('color'), 'red')


class TestFontSizeCompounding(unittest.TestCase):
    def test_em_resolves_against_parent_absolute_size(self):
        doc, styles, _ = styled(
            '<div id="d"><span id="s">x</span></div>',
            '#d{font-size:20px;} #s{font-size:0.5em;}',
        )
        span = doc.find_all('span')[0]
        self.assertAlmostEqual(styles[span].get('font-size'), 10.0)

    def test_nested_em_compounds(self):
        doc, styles, _ = styled(
            '<div id="d"><span id="a"><span id="b">x</span></span></div>',
            '#d{font-size:20px;} #a{font-size:0.5em;} #b{font-size:0.5em;}',
        )
        b = doc.find_all('span')[1]
        self.assertAlmostEqual(styles[b].get('font-size'), 5.0)

    def test_default_root_font_size_is_16(self):
        doc, styles, _ = styled('<p>x</p>')
        p = doc.find_all('p')[0]
        self.assertAlmostEqual(styles[p].get('font-size'), 16.0)


class TestUAStylesheetDefaults(unittest.TestCase):
    def test_h1_bigger_than_body_text_with_zero_author_css(self):
        doc, styles, _ = styled('<h1>Big</h1><p>small</p>')
        h1 = doc.find_all('h1')[0]
        p = doc.find_all('p')[0]
        self.assertGreater(styles[h1].get('font-size'), styles[p].get('font-size'))

    def test_author_rule_overrides_ua_default_at_equal_specificity(self):
        doc, styles, _ = styled('<h1>x</h1>', 'h1 { font-size: 10px; }')
        h1 = doc.find_all('h1')[0]
        self.assertAlmostEqual(styles[h1].get('font-size'), 10.0)

    def test_head_subtree_is_display_none(self):
        doc, styles, _ = styled('<html><head><title>t</title></head><body>b</body></html>')
        head = doc.find_all('head')[0]
        self.assertEqual(styles[head].get('display'), 'none')


class TestShorthands(unittest.TestCase):
    def test_margin_shorthand_expands_to_four_sides(self):
        doc, styles, _ = styled('<p>x</p>', 'p{margin: 1px 2px 3px 4px;}')
        p = doc.find_all('p')[0]
        st = styles[p]
        self.assertEqual(
            (st.get('margin-top'), st.get('margin-right'), st.get('margin-bottom'), st.get('margin-left')),
            ('1px', '2px', '3px', '4px'),
        )

    def test_border_shorthand_with_rgb_color_not_shredded(self):
        doc, styles, _ = styled('<p>x</p>', 'p{border: 1px solid rgb(0, 0, 0);}')
        p = doc.find_all('p')[0]
        self.assertEqual(styles[p].get('border-top-color'), 'rgb(0, 0, 0)')


if __name__ == '__main__':
    unittest.main()
