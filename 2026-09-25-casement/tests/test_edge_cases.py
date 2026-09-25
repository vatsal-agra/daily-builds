"""Phase 3 adversarial-review battery: throw deliberately hostile HTML/CSS
at the pipeline and require that it never crashes, even when the "correct"
answer is degenerate (an empty page, a 1px image)."""

import unittest

from casement.render import render


class TestEdgeCasesDoNotCrash(unittest.TestCase):
    def _ok(self, html, css="", width=400):
        r = render(html, extra_css=css, viewport_width=width)
        self.assertGreaterEqual(r.width, 1)
        self.assertGreaterEqual(r.height, 1)
        self.assertGreater(len(r.png_bytes), 0)
        return r

    def test_empty_html(self):
        self._ok("")

    def test_empty_body(self):
        self._ok("<html><body></body></html>")

    def test_no_html_or_body_wrapper(self):
        self._ok("<div>just a div, no html/body</div>")

    def test_deeply_nested_200_levels(self):
        self._ok("<div>" * 200 + "x" + "</div>" * 200)

    def test_very_long_unbreakable_word(self):
        r = self._ok("<div style='width:120px'>" + "a" * 300 + "</div>")
        self.assertGreater(r.width, 0)

    def test_zero_width_container(self):
        self._ok("<div style='width:0'><p>text</p></div>")

    def test_negative_margin(self):
        self._ok("<div style='margin:-20px'>x</div><div>y</div>")

    def test_percentage_height_on_indefinite_container(self):
        self._ok("<div style='height:50%'><p>x</p></div>")

    def test_malformed_css_declarations(self):
        self._ok("<div class='x'>x</div>", css=".x { color: ; width: 10px background: }")

    def test_unclosed_and_unknown_at_rule(self):
        self._ok("<p>x</p>", css="@media (max-width: 1px) { p { color: red")

    def test_nested_flex_containers(self):
        self._ok(
            "<div style='display:flex'><div style='display:flex;flex:1'>"
            "<div style='flex:1'>a</div></div></div>"
        )

    def test_absolute_child_of_flex_grandchild(self):
        self._ok(
            "<div style='position:relative'><div style='display:flex'>"
            "<div style='position:absolute;top:0;left:0'>abs</div>"
            "<div>b</div></div></div>"
        )

    def test_min_width_forces_overflow(self):
        self._ok(
            "<div style='display:flex;width:100px'>"
            "<div style='min-width:80px'>a</div><div style='min-width:80px'>b</div></div>"
        )

    def test_empty_flex_container(self):
        self._ok("<div style='display:flex'></div>")

    def test_whitespace_only_text(self):
        self._ok("<p>   \n\t  </p>")

    def test_unicode_text(self):
        self._ok("<p>héllo wörld ✓</p>")

    def test_self_closing_void_elements(self):
        self._ok("<div><br/><hr/><img/></div>")

    def test_unsupported_table_tags_degrade_gracefully(self):
        self._ok("<table><tr><td>cell</td></tr></table>")

    def test_comment_only_document(self):
        self._ok("<!-- just a comment -->")

    def test_box_sizing_border_box_padding_exceeds_width(self):
        self._ok("<div style='width:5px;padding:10px;box-sizing:border-box'>x</div>")


if __name__ == "__main__":
    unittest.main()
