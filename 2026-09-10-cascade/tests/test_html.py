import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dom import Element, Text, find_all, find_first
from html_parser import parse_html
from html_tokenizer import decode_entities, tokenize


class TokenizerTests(unittest.TestCase):
    def test_simple_tag_and_text(self):
        toks = tokenize("<p>hi</p>")
        kinds = [t.kind for t in toks]
        self.assertEqual(kinds, ["starttag", "text", "endtag"])
        self.assertEqual(toks[0].name, "p")
        self.assertEqual(toks[1].data, "hi")

    def test_attributes_quoted_and_unquoted(self):
        toks = tokenize('<div id="a" class=\'b c\' data-x=y>')
        attrs = toks[0].attrs
        self.assertEqual(attrs["id"], "a")
        self.assertEqual(attrs["class"], "b c")
        self.assertEqual(attrs["data-x"], "y")

    def test_boolean_attribute(self):
        toks = tokenize("<input disabled>")
        self.assertIn("disabled", toks[0].attrs)
        self.assertEqual(toks[0].attrs["disabled"], "")

    def test_self_closing(self):
        toks = tokenize("<br/>")
        self.assertTrue(toks[0].self_closing)

    def test_comment(self):
        toks = tokenize("a<!-- hi -->b")
        kinds = [t.kind for t in toks]
        self.assertIn("comment", kinds)
        self.assertEqual(toks[1].data, " hi ")

    def test_doctype_ignored_downstream(self):
        toks = tokenize("<!DOCTYPE html><p>x</p>")
        self.assertEqual(toks[0].kind, "doctype")

    def test_script_is_raw_text(self):
        toks = tokenize("<script>if (a < b) { x(); }</script>after")
        text_tok = [t for t in toks if t.kind == "text" and "a < b" in (t.data or "")]
        self.assertEqual(len(text_tok), 1)

    def test_style_is_raw_text(self):
        toks = tokenize("<style>p::before{content:'<x>'}</style>")
        self.assertTrue(any(t.kind == "text" and "<x>" in (t.data or "") for t in toks))

    def test_named_entities(self):
        self.assertEqual(decode_entities("a &amp; b &lt;c&gt;"), "a & b <c>")

    def test_numeric_entities(self):
        self.assertEqual(decode_entities("&#65;&#x42;"), "AB")

    def test_unknown_entity_left_alone(self):
        self.assertEqual(decode_entities("&notreal;"), "&notreal;")

    def test_unclosed_tag_at_eof(self):
        toks = tokenize("<div><p>text")
        self.assertEqual([t.kind for t in toks if t.kind == "starttag"][-1], "starttag")


class ParserTests(unittest.TestCase):
    def test_implicit_html_head_body(self):
        doc = parse_html("<p>hi</p>")
        html = doc.children[0]
        self.assertEqual(html.tag, "html")
        self.assertEqual(html.children[0].tag, "head")
        self.assertEqual(html.children[1].tag, "body")

    def test_body_gets_the_content(self):
        doc = parse_html("<p>hi</p>")
        body = doc.children[0].children[1]
        self.assertEqual(len(body.element_children()), 1)
        self.assertEqual(body.element_children()[0].tag, "p")

    def test_head_elements_go_to_head(self):
        doc = parse_html("<title>T</title><style>a{}</style><p>hi</p>")
        head = doc.children[0].children[0]
        tags = [c.tag for c in head.element_children()]
        self.assertIn("title", tags)
        self.assertIn("style", tags)

    def test_void_element_has_no_children_stack_push(self):
        doc = parse_html("<div><img src='x.png'>after</div>")
        div = find_first(doc, "div")
        # img and the text node "after" are both direct children of div,
        # proving <img> didn't stay open and swallow "after".
        self.assertEqual(len(div.children), 2)
        self.assertEqual(div.children[0].tag, "img")
        self.assertIsInstance(div.children[1], Text)

    def test_auto_close_p(self):
        doc = parse_html("<p>one<p>two")
        ps = find_all(doc, "p")
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[0].text_content(), "one")
        self.assertEqual(ps[1].text_content(), "two")

    def test_auto_close_li(self):
        doc = parse_html("<ul><li>a<li>b<li>c</ul>")
        lis = find_all(doc, "li")
        self.assertEqual([li.text_content() for li in lis], ["a", "b", "c"])
        # all three are siblings under <ul>, not nested inside each other
        ul = find_first(doc, "ul")
        self.assertEqual(len(ul.element_children()), 3)

    def test_mismatched_end_tag_ignored(self):
        doc = parse_html("<div><span>x</b></span></div>")
        span = find_first(doc, "span")
        self.assertEqual(span.text_content(), "x")

    def test_stray_end_tag_with_no_open_element(self):
        doc = parse_html("</b><p>ok</p>")
        p = find_first(doc, "p")
        self.assertEqual(p.text_content(), "ok")

    def test_nested_structure(self):
        doc = parse_html("<div><section><h1>Title</h1><p>Body <b>bold</b> text.</p></section></div>")
        h1 = find_first(doc, "h1")
        self.assertEqual(h1.text_content(), "Title")
        b = find_first(doc, "b")
        self.assertEqual(b.text_content(), "bold")

    def test_attributes_preserved(self):
        doc = parse_html('<div id="main" class="a b"></div>')
        div = find_first(doc, "div")
        self.assertEqual(div.id, "main")
        self.assertEqual(div.classes, ["a", "b"])

    def test_comments_become_comment_nodes(self):
        doc = parse_html("<div><!-- note --></div>")
        div = find_first(doc, "div")
        self.assertEqual(len(div.children), 1)
        self.assertEqual(div.children[0].data, " note ")

    def test_entities_decoded_in_text_and_attrs(self):
        doc = parse_html('<div title="a &amp; b">x &lt; y</div>')
        div = find_first(doc, "div")
        self.assertEqual(div.attrs["title"], "a & b")
        self.assertEqual(div.text_content(), "x < y")

    def test_table_row_auto_close(self):
        doc = parse_html("<table><tr><td>a<td>b<tr><td>c</table>")
        rows = find_all(doc, "tr")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0].element_children()), 2)


if __name__ == "__main__":
    unittest.main()
