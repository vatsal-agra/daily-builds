import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cascade.html_parser import parse
from cascade.dom import Element


class TestHtmlParser(unittest.TestCase):
    def test_basic_tree(self):
        doc = parse("<html><body><p>hello</p></body></html>")
        p = doc.find("p")
        self.assertIsNotNone(p)
        self.assertEqual(p.text_content(), "hello")

    def test_attributes(self):
        doc = parse('<div class=foo id=\'bar\' data-x checked disabled="">x</div>')
        el = doc.find("div")
        self.assertEqual(el.attrs, {"class": "foo", "id": "bar", "data-x": "",
                                     "checked": "", "disabled": ""})

    def test_void_elements_self_close(self):
        doc = parse("<div><br><img src=x><p>after</p></div>")
        div = doc.find("div")
        # br/img should not have swallowed <p> as a child
        self.assertIsNotNone(doc.find("p"))
        self.assertEqual(doc.find("br").children, [])

    def test_unclosed_p_auto_closes_on_next_p(self):
        doc = parse("<div><p>one<p>two</div>")
        ps = doc.find_all("p")
        self.assertEqual(len(ps), 2)
        # both should be children of div, not nested inside each other
        div = doc.find("div")
        self.assertEqual(div.element_children(), ps)
        self.assertEqual(ps[0].text_content(), "one")
        self.assertEqual(ps[1].text_content(), "two")

    def test_li_auto_closes(self):
        doc = parse("<ul><li>a<li>b<li>c</ul>")
        lis = doc.find_all("li")
        self.assertEqual(len(lis), 3)
        ul = doc.find("ul")
        self.assertEqual(ul.element_children(), lis)

    def test_deeply_nested_does_not_crash(self):
        html = "<div>" * 300 + "deep" + "</div>" * 300
        doc = parse(html)
        self.assertIsNotNone(doc)

    def test_unclosed_comment_does_not_crash(self):
        doc = parse("<div><!-- unclosed <p>hi</div>")
        self.assertIsNotNone(doc)

    def test_stray_end_tag_ignored(self):
        doc = parse("<div>hello</span></div>")
        div = doc.find("div")
        self.assertEqual(div.text_content(), "hello")

    def test_script_content_not_parsed_as_markup(self):
        doc = parse('<script>if (a < b) { var x = "<div>fake</div>"; }</script><p>real</p>')
        self.assertEqual(len(doc.find_all("p")), 1)
        self.assertIn("<div>fake</div>", doc.find("script").text_content())

    def test_style_content_not_parsed_as_markup(self):
        doc = parse("<style>div::before { content: '<p>'; }</style><p>real</p>")
        self.assertEqual(len(doc.find_all("p")), 1)

    def test_entities(self):
        doc = parse("<p>a &amp; b &lt;3 &#65; &#x42;</p>")
        self.assertEqual(doc.find("p").text_content(), "a & b <3 A B")

    def test_case_insensitive_tags(self):
        doc = parse("<DIV><P>x</P></DIV>")
        self.assertIsNotNone(doc.find("div"))
        self.assertIsNotNone(doc.find("p"))

    def test_bare_text_gets_implicit_body(self):
        doc = parse("hello world")
        body = doc.find("body")
        self.assertIsNotNone(body)
        self.assertEqual(body.text_content(), "hello world")

    def test_multiple_top_level_tags_get_wrapped(self):
        doc = parse("<p>one</p><p>two</p>")
        body = doc.find("body")
        self.assertIsNotNone(body)
        self.assertEqual(len(body.find_all("p")), 2)

    def test_head_stays_outside_synthetic_body(self):
        doc = parse("<head><title>T</title></head><p>content</p>")
        body = doc.find("body")
        head = doc.find("head")
        self.assertIsNotNone(body)
        self.assertIsNotNone(head)
        self.assertNotIn(head, list(body.walk()))
        self.assertIn(doc.find("p"), list(body.walk()))

    def test_explicit_body_untouched(self):
        doc = parse("<html><body><p>x</p></body></html>")
        bodies = doc.find_all("body")
        self.assertEqual(len(bodies), 1)

    def test_empty_document(self):
        doc = parse("")
        self.assertIsNotNone(doc)


if __name__ == "__main__":
    unittest.main()
