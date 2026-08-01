import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.html_parser import parse


class TestTokenizerBasics(unittest.TestCase):
    def test_simple_element_and_text(self):
        doc = parse('<p>hello</p>')
        p = doc.find_all('p')[0]
        self.assertEqual(p.text_content(), 'hello')

    def test_attributes_quoted_and_unquoted(self):
        doc = parse('<div class="a b" id=main data-x=1>x</div>')
        div = doc.find_all('div')[0]
        self.assertEqual(div.attrs, {'class': 'a b', 'id': 'main', 'data-x': '1'})

    def test_entity_decoding_in_text_and_attrs(self):
        doc = parse('<p title="a &amp; b">1 &lt; 2 &amp;&amp; 3 &gt; 1</p>')
        p = doc.find_all('p')[0]
        self.assertEqual(p.attrs['title'], 'a & b')
        self.assertEqual(p.text_content(), '1 < 2 && 3 > 1')

    def test_comment_is_not_rendered_as_element(self):
        doc = parse('<div><!-- a comment --><p>x</p></div>')
        div = doc.find_all('div')[0]
        self.assertEqual(len(div.find_all('p')), 1)
        self.assertTrue(any(c.node_type == 'comment' for c in div.children))

    def test_void_elements_never_get_children(self):
        doc = parse('<div><img src="x.png"><p>after</p></div>')
        img = doc.find_all('img')[0]
        p = doc.find_all('p')[0]
        self.assertEqual(img.children, [])
        self.assertIs(p.parent, doc.find_all('div')[0])

    def test_self_closing_custom_tag(self):
        doc = parse('<foo/><p>sibling</p>')
        foo = doc.find_all('foo')[0]
        p = doc.find_all('p')[0]
        self.assertIs(foo.parent, p.parent)

    def test_unquoted_attr_immediately_before_self_close(self):
        doc = parse('<foo bar=baz/><p>after</p>')
        foo = doc.find_all('foo')[0]
        p = doc.find_all('p')[0]
        self.assertEqual(foo.attrs['bar'], 'baz')
        self.assertIs(foo.parent, p.parent, 'self-close must not be swallowed into the attr value')

    def test_unquoted_attr_with_url_slash_is_unaffected(self):
        doc = parse('<img src=path/to/img.png>')
        self.assertEqual(doc.find_all('img')[0].attrs['src'], 'path/to/img.png')

    def test_lone_angle_bracket_is_literal_text(self):
        doc = parse('<p>1 < 2 and 3 > 1</p>')
        self.assertEqual(doc.find_all('p')[0].text_content(), '1 < 2 and 3 > 1')

    def test_doctype_is_ignored_not_rendered(self):
        doc = parse('<!DOCTYPE html><html><body>x</body></html>')
        self.assertEqual(doc.children[0].node_type, 'element')
        self.assertEqual(doc.children[0].name, 'html')


class TestTreeConstruction(unittest.TestCase):
    def test_div_with_p_child_stays_nested(self):
        doc = parse('<div><p>x</p></div>')
        p = doc.find_all('p')[0]
        div = doc.find_all('div')[0]
        self.assertIs(p.parent, div, 'opening <p> must not close an ancestor <div>')

    def test_p_auto_closes_on_next_p(self):
        doc = parse('<body><p>first<p>second</body>')
        ps = doc.find_all('p')
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[0].text_content(), 'first')
        self.assertEqual(ps[0].parent, ps[1].parent)

    def test_p_auto_closes_when_div_opens(self):
        doc = parse('<p>text<div>block</div>after</p>')
        p = doc.find_all('p')[0]
        div = doc.find_all('div')[0]
        self.assertEqual(p.text_content(), 'text')
        self.assertIs(div.parent, doc)
        # the stray closing </p> is ignored since <p> was already auto-closed
        self.assertTrue(any(c.node_type == 'text' and 'after' in c.data for c in doc.children))

    def test_li_auto_closes_on_next_li(self):
        doc = parse('<ul><li>one<li>two<li>three</ul>')
        items = doc.find_all('li')
        self.assertEqual([li.text_content() for li in items], ['one', 'two', 'three'])
        self.assertEqual(len({id(li.parent) for li in items}), 1)

    def test_nested_list_inside_li_stays_nested(self):
        doc = parse('<ul><li>parent<ul><li>child</li></ul></li></ul>')
        outer_li = doc.find_all('li')[0]
        self.assertEqual(len(outer_li.find_all('ul')), 1, 'a nested <ul> must not be auto-closed by its own <li>')

    def test_table_row_auto_closes_previous_cell_and_row(self):
        doc = parse('<table><tr><td>1<td>2<tr><td>3</table>')
        rows = doc.find_all('tr')
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0].find_all('td')), 2)
        self.assertEqual(len(rows[1].find_all('td')), 1)
        table = doc.find_all('table')[0]
        self.assertEqual([r.parent for r in rows], [table, table])

    def test_end_tag_closes_everything_above_it(self):
        doc = parse('<b><i>bold italic</b> just italic</i>')
        b = doc.find_all('b')[0]
        i = doc.find_all('i')[0]
        self.assertIs(i.parent, b)
        self.assertEqual(i.text_content(), 'bold italic')
        # "just italic" ends up outside <b> entirely, matching real browsers
        trailing = [c for c in doc.children if c.node_type == 'text' and 'just italic' in c.data]
        self.assertEqual(len(trailing), 1)

    def test_unclosed_elements_at_eof_are_implicitly_closed(self):
        doc = parse('<div><p>unclosed')
        p = doc.find_all('p')[0]
        self.assertEqual(p.text_content(), 'unclosed')

    def test_stray_end_tag_is_ignored(self):
        doc = parse('<p>hello</div></p>')
        p = doc.find_all('p')[0]
        self.assertEqual(p.text_content(), 'hello')
        self.assertEqual(doc.find_all('div'), [])

    def test_adjacent_text_nodes_merge(self):
        doc = parse('<p>1 &lt; 2</p>')
        p = doc.find_all('p')[0]
        text_children = [c for c in p.children if c.node_type == 'text']
        self.assertEqual(len(text_children), 1)


class TestRawText(unittest.TestCase):
    def test_script_content_is_not_tokenized_as_markup(self):
        doc = parse('<script>if (a < b) { x.innerHTML = "</div>"; }</script><p>after</p>')
        script = doc.find_all('script')[0]
        self.assertIn('</div>', script.text_content())
        self.assertEqual(len(doc.find_all('div')), 0)

    def test_style_content_is_raw_not_html_escaped(self):
        doc = parse('<style>p::before { content: "&amp;"; }</style>')
        style = doc.find_all('style')[0]
        self.assertEqual(style.text_content(), 'p::before { content: "&amp;"; }')

    def test_script_and_style_never_get_element_children(self):
        doc = parse('<script>var x = 1;</script>')
        script = doc.find_all('script')[0]
        self.assertTrue(all(c.node_type == 'text' for c in script.children))


if __name__ == '__main__':
    unittest.main()
