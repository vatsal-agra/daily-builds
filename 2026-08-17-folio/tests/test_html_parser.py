import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio.html_parser import parse_html
from folio.dom import ELEMENT, TEXT, COMMENT, find_element


def els(doc, tag):
    return [n for n in doc.iter_element_descendants() if n.tag == tag]


class TestTokenizerTreeBuilder(unittest.TestCase):
    def test_basic_nesting(self):
        doc = parse_html("<div><p>Hello</p></div>")
        div = find_element(doc, "div")
        self.assertIsNotNone(div)
        self.assertEqual(len(div.children), 1)
        p = div.children[0]
        self.assertEqual(p.tag, "p")
        self.assertEqual(p.children[0].data, "Hello")

    def test_attributes(self):
        doc = parse_html('<div id="x" class="a b" data-y=\'z\' disabled>hi</div>')
        div = find_element(doc, "div")
        self.assertEqual(div.id, "x")
        self.assertEqual(div.class_list, ["a", "b"])
        self.assertEqual(div.get_attr("data-y"), "z")
        self.assertEqual(div.get_attr("disabled"), "")

    def test_unquoted_and_mixed_quotes(self):
        doc = parse_html("<div class=box id='y'>x</div>")
        div = find_element(doc, "div")
        self.assertEqual(div.class_list, ["box"])
        self.assertEqual(div.id, "y")

    def test_void_elements_dont_nest(self):
        doc = parse_html("<div>a<br>b<img src=x>c<hr></div>")
        div = find_element(doc, "div")
        # br/img/hr should not have become containers holding "b"/"c"/etc.
        tags = [c.tag if c.is_element else "#text" for c in div.children]
        self.assertEqual(tags, ["#text", "br", "#text", "img", "#text", "hr"])

    def test_self_closing_custom_tag_not_pushed(self):
        doc = parse_html("<div><foo/>after</div>")
        div = find_element(doc, "div")
        self.assertEqual(len(div.children), 2)
        self.assertEqual(div.children[0].tag, "foo")
        self.assertEqual(div.children[1].data, "after")

    def test_mismatched_close_recovers(self):
        # </span> with no open <span> must not crash or corrupt the tree.
        doc = parse_html("<div><p>a</span>b</p></div>")
        div = find_element(doc, "div")
        p = find_element(doc, "p")
        self.assertIsNotNone(p)
        text = "".join(c.data for c in p.children if c.is_text)
        self.assertEqual(text, "ab")

    def test_implicit_p_close(self):
        doc = parse_html("<div><p>one<p>two<p>three</div>")
        div = find_element(doc, "div")
        ps = [c for c in div.children if c.is_element and c.tag == "p"]
        self.assertEqual(len(ps), 3)
        for p in ps:
            self.assertEqual(p.parent, div)  # not nested inside each other

    def test_implicit_li_close(self):
        doc = parse_html("<ul><li>a<li>b<li>c</ul>")
        ul = find_element(doc, "ul")
        lis = [c for c in ul.children if c.is_element]
        self.assertEqual(len(lis), 3)
        self.assertEqual([li.children[0].data for li in lis], ["a", "b", "c"])

    def test_table_row_cell_implicit_close(self):
        doc = parse_html("<table><tr><td>a<td>b<tr><td>c</table>")
        trs = els(doc, "tr")
        self.assertEqual(len(trs), 2)
        self.assertEqual(len(els(doc, "td")), 3)
        self.assertEqual(trs[0].parent.tag, "table")
        self.assertEqual(trs[1].parent.tag, "table")

    def test_comments_and_doctype(self):
        doc = parse_html("<!DOCTYPE html><!-- top --><div><!-- inner -->x</div>")
        comments = [n for n in doc.iter_descendants() if n.node_type == COMMENT]
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].data, " top ")
        self.assertEqual(comments[1].data, " inner ")

    def test_unterminated_comment_does_not_crash(self):
        doc = parse_html("<div>a</div><!-- never closed")
        div = find_element(doc, "div")
        self.assertEqual(div.children[0].data, "a")

    def test_script_is_raw_text(self):
        doc = parse_html("<script>if (a<b) { x() }</script><div>after</div>")
        script = find_element(doc, "script")
        self.assertEqual(script.children[0].data, "if (a<b) { x() }")
        div = find_element(doc, "div")
        self.assertEqual(div.children[0].data, "after")

    def test_style_is_raw_text_with_braces(self):
        doc = parse_html("<style>div>p{color:red}</style>")
        style = find_element(doc, "style")
        self.assertEqual(style.children[0].data, "div>p{color:red}")

    def test_textarea_decodes_entities_but_stays_raw(self):
        doc = parse_html("<textarea><b>not a tag</b> &amp; text</textarea>")
        ta = find_element(doc, "textarea")
        self.assertEqual(len(ta.children), 1)
        self.assertEqual(ta.children[0].data, "<b>not a tag</b> & text")

    def test_entity_decoding(self):
        doc = parse_html("<p>Tom &amp; Jerry &lt;3 &#65;&#x42; &copy; &nbsp;&unknownxyz;</p>")
        p = find_element(doc, "p")
        text = p.children[0].data
        self.assertEqual(text, "Tom & Jerry <3 AB ©  &unknownxyz;")

    def test_bare_ampersand_stays_literal(self):
        doc = parse_html("<p>Q&A</p>")
        p = find_element(doc, "p")
        self.assertEqual(p.children[0].data, "Q&A")

    def test_deeply_nested_no_crash(self):
        html = "<div>" * 500 + "x" + "</div>" * 500
        doc = parse_html(html)
        divs = els(doc, "div")
        self.assertEqual(len(divs), 500)

    def test_unclosed_tags_at_eof_recover(self):
        doc = parse_html("<div><p>a<span>b")
        # Must not raise; the parser should have built *something* sane.
        span = find_element(doc, "span")
        self.assertIsNotNone(span)
        self.assertEqual(span.children[0].data, "b")

    def test_empty_document(self):
        doc = parse_html("")
        self.assertEqual(doc.children, [])

    def test_attribute_without_value(self):
        doc = parse_html("<input disabled required type=text>")
        el = find_element(doc, "input")
        self.assertIn("disabled", el.attrs)
        self.assertIn("required", el.attrs)
        self.assertEqual(el.get_attr("type"), "text")


if __name__ == "__main__":
    unittest.main()
