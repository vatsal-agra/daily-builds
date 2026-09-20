import unittest

from folio.dom import Comment, Element, Text, find_all, find_first
from folio.html_parser import parse_html, unescape_entities


class TestTokenizerHang(unittest.TestCase):
    """Regression for REVIEW.md finding #1: a malformed '<...>' sequence
    must never hang the tokenizer."""

    def test_malformed_tag_does_not_hang(self):
        import signal

        def handler(signum, frame):
            raise TimeoutError("tokenizer hung")

        old = signal.signal(signal.SIGALRM, handler)
        signal.alarm(3)
        try:
            doc = parse_html("<div>hi <3d> there</div>")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        div = find_first(doc, "div")
        self.assertIsNotNone(div)
        self.assertIn("<", div.text_content())

    def test_lone_trailing_lt(self):
        doc = parse_html("<p>trailing<")
        p = find_first(doc, "p")
        self.assertIn("trailing", p.text_content())

    def test_space_after_lt(self):
        doc = parse_html("<p>a < b</p>")
        p = find_first(doc, "p")
        self.assertIn("a", p.text_content())


class TestBasicParsing(unittest.TestCase):
    def test_simple_tree(self):
        doc = parse_html("<div><p>hello</p></div>")
        div = find_first(doc, "div")
        p = find_first(doc, "p")
        self.assertEqual(p.parent, div)
        self.assertEqual(p.text_content(), "hello")

    def test_attributes(self):
        doc = parse_html('<div class="a b" id=main data-x=1 disabled>x</div>')
        div = find_first(doc, "div")
        self.assertEqual(div.classes, ["a", "b"])
        self.assertEqual(div.id, "main")
        self.assertEqual(div.get("data-x"), "1")
        self.assertEqual(div.get("disabled"), "")

    def test_unquoted_and_single_quoted_attrs(self):
        doc = parse_html("<div class='card' data-n=42>x</div>")
        div = find_first(doc, "div")
        self.assertEqual(div.get("class"), "card")
        self.assertEqual(div.get("data-n"), "42")

    def test_unterminated_quote_does_not_crash(self):
        doc = parse_html('<div class="unterminated>text after</div>')
        # Must not raise; exact recovery shape isn't the point, survival is.
        self.assertIsNotNone(doc)

    def test_void_elements_not_pushed(self):
        doc = parse_html("<div><img src='x.png'>after</div>")
        div = find_first(doc, "div")
        # img has no children and 'after' is a sibling, not nested inside it.
        img = find_first(doc, "img")
        self.assertEqual(img.children, [])
        self.assertIn("after", div.text_content())

    def test_self_closing_non_void(self):
        doc = parse_html("<div/>after")
        div = find_first(doc, "div")
        self.assertEqual(div.children, [])

    def test_comment_parsed_not_rendered_as_element(self):
        doc = parse_html("<div><!-- a comment -->text</div>")
        div = find_first(doc, "div")
        comments = [c for c in div.children if isinstance(c, Comment)]
        self.assertEqual(len(comments), 1)
        self.assertIn("a comment", comments[0].data)

    def test_doctype_ignored_gracefully(self):
        doc = parse_html("<!DOCTYPE html><html><body>x</body></html>")
        self.assertIsNotNone(find_first(doc, "html"))


class TestImpliedEndTags(unittest.TestCase):
    def test_p_auto_closes_on_new_p(self):
        doc = parse_html("<p>first<p>second")
        ps = find_all(doc, "p")
        self.assertEqual(len(ps), 2)
        self.assertEqual(ps[0].text_content(), "first")
        self.assertEqual(ps[1].text_content(), "second")

    def test_li_auto_closes_on_new_li(self):
        doc = parse_html("<ul><li>one<li>two</ul>")
        lis = find_all(doc, "li")
        self.assertEqual(len(lis), 2)
        self.assertEqual(lis[0].text_content(), "one")
        self.assertEqual(lis[1].text_content(), "two")
        # Both <li>s must be children of the same <ul>, not nested in each other.
        ul = find_first(doc, "ul")
        self.assertEqual(lis[0].parent, ul)
        self.assertEqual(lis[1].parent, ul)

    def test_p_closes_before_block_level_sibling(self):
        doc = parse_html("<p>text<ul><li>item</li></ul>")
        ul = find_first(doc, "ul")
        p = find_first(doc, "p")
        # The <ul> must NOT be nested inside the unclosed <p>.
        self.assertNotEqual(ul.parent, p)


class TestRawTextElements(unittest.TestCase):
    def test_script_content_not_tokenized_as_tags(self):
        html = (
            "<script>if (a < b) { x('<div>fake</div>'); }</script>"
            "<p>after</p>"
        )
        doc = parse_html(html)
        script = find_first(doc, "script")
        text = script.text_content()
        self.assertIn("<div>fake</div>", text)
        # The fake <div> must not have become a real DOM element.
        self.assertIsNone(find_first(doc, "div"))
        p = find_first(doc, "p")
        self.assertEqual(p.text_content(), "after")

    def test_style_content_raw(self):
        doc = parse_html("<style>div > p { color: red; }</style>")
        style = find_first(doc, "style")
        self.assertIn("color: red", style.text_content())


class TestEntities(unittest.TestCase):
    def test_named_entities(self):
        self.assertEqual(unescape_entities("a &amp; b"), "a & b")
        self.assertEqual(unescape_entities("&lt;tag&gt;"), "<tag>")
        self.assertEqual(unescape_entities("&quot;q&quot;"), '"q"')

    def test_numeric_entities(self):
        self.assertEqual(unescape_entities("&#65;&#66;"), "AB")
        self.assertEqual(unescape_entities("&#x41;"), "A")

    def test_unknown_entity_left_alone(self):
        self.assertEqual(unescape_entities("&notarealentity;"), "&notarealentity;")


class TestMultiRoot(unittest.TestCase):
    """Regression for REVIEW.md finding #2."""

    def test_multiple_top_level_elements_all_parsed(self):
        doc = parse_html("<div>First</div><div>Second</div>")
        divs = find_all(doc, "div")
        self.assertEqual(len(divs), 2)
        self.assertEqual(divs[0].text_content(), "First")
        self.assertEqual(divs[1].text_content(), "Second")


if __name__ == "__main__":
    unittest.main()
