import unittest

from casement.dom import Element, Text, find_all, find_first
from casement.html_parser import parse


class TestHTMLParser(unittest.TestCase):
    def test_basic_tree(self):
        doc = parse("<html><body><p>Hello <b>world</b></p></body></html>")
        p = find_first(doc, "p")
        self.assertIsNotNone(p)
        self.assertEqual(len(p.children), 2)
        self.assertIsInstance(p.children[0], Text)
        self.assertEqual(p.children[0].data, "Hello ")
        b = p.children[1]
        self.assertEqual(b.tag, "b")
        self.assertEqual(b.children[0].data, "world")

    def test_attributes(self):
        doc = parse('<div id="main" class="a b c" data-x=\'y\'></div>')
        div = find_first(doc, "div")
        self.assertEqual(div.id, "main")
        self.assertEqual(div.classes, ["a", "b", "c"])
        self.assertEqual(div.get("data-x"), "y")

    def test_unquoted_attribute(self):
        doc = parse("<div class=foo></div>")
        div = find_first(doc, "div")
        self.assertEqual(div.classes, ["foo"])

    def test_void_elements_not_pushed(self):
        doc = parse("<div>a<br>b<img src='x.png'>c</div>")
        div = find_first(doc, "div")
        # br/img must not swallow following siblings as children
        self.assertEqual(len(div.children), 5)
        self.assertEqual(div.children[1].tag, "br")
        self.assertEqual(div.children[3].tag, "img")

    def test_self_closing_tag(self):
        doc = parse("<div><hr/>text</div>")
        div = find_first(doc, "div")
        self.assertEqual(div.children[0].tag, "hr")
        self.assertEqual(div.children[0].children, [])

    def test_auto_close_p(self):
        doc = parse("<div><p>one<p>two<div>three</div></div>")
        div = find_first(doc, "div")
        ps = find_all(div, "p")
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[0].children[0].data, "one")
        self.assertEqual(ps[1].children[0].data, "two")
        # the second <p> must not have swallowed the following <div>
        inner_divs = [n for n in div.iter() if isinstance(n, Element) and n.tag == "div" and n is not div]
        self.assertEqual(len(inner_divs), 1)
        self.assertEqual(inner_divs[0].children[0].data, "three")

    def test_auto_close_li(self):
        doc = parse("<ul><li>one<li>two<li>three</ul>")
        lis = find_all(doc, "li")
        self.assertEqual(len(lis), 3)
        self.assertEqual([li.children[0].data for li in lis], ["one", "two", "three"])

    def test_mismatched_end_tag_recovers(self):
        doc = parse("<div><span>hi</div>after")
        div = find_first(doc, "div")
        span = find_first(div, "span")
        self.assertIsNotNone(span)
        self.assertEqual(span.children[0].data, "hi")
        # 'after' text should land back at the document level, not inside span/div
        texts = [n.data for n in doc.iter() if isinstance(n, Text)]
        self.assertIn("after", texts)

    def test_stray_end_tag_ignored(self):
        doc = parse("<div>hello</p></div>")
        div = find_first(doc, "div")
        self.assertEqual(div.children[0].data, "hello")

    def test_comments_and_entities(self):
        doc = parse("<div><!-- a comment -->A &amp; B &lt;3 &#65;</div>")
        div = find_first(doc, "div")
        texts = [n.data for n in div.children if isinstance(n, Text)]
        self.assertEqual("".join(texts), "A & B <3 A")

    def test_style_and_script_are_raw_text(self):
        doc = parse("<style>div > p { color: red; } /* <fake-tag> */</style><script>if (a<b) {}</script>")
        style_el = find_first(doc, "style")
        script_el = find_first(doc, "script")
        self.assertIn("div > p", style_el.children[0].data)
        self.assertIn("a<b", script_el.children[0].data)

    def test_case_insensitive_tags(self):
        doc = parse("<DIV><P>Hi</P></DIV>")
        self.assertIsNotNone(find_first(doc, "div"))
        self.assertIsNotNone(find_first(doc, "p"))


if __name__ == "__main__":
    unittest.main()
