import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.browser import render_page
from reflow.visualize import dump_cascade_text, dump_cssom_text, layout_to_svg


class TestRobustnessAgainstDegenerateInput(unittest.TestCase):
    def test_empty_html_does_not_crash(self):
        r = render_page('')
        self.assertGreaterEqual(r.canvas.width, 1)
        self.assertGreaterEqual(r.canvas.height, 1)

    def test_malformed_css_with_missing_brace_does_not_crash(self):
        html = '<html><head><style>p { color: red\ndiv { color: blue; }</style></head><body><p>x</p></body></html>'
        r = render_page(html, viewport_width=200)
        self.assertGreater(len(r.png), 0)

    def test_css_with_unsupported_at_rule_and_pseudo_class_does_not_crash(self):
        html = (
            '<html><head><style>'
            '@media (max-width: 600px) { p { color: red; } }'
            'a:hover { color: green; }'
            'div[data-x] { color: blue; }'
            '</style></head><body><p class="a">test</p></body></html>'
        )
        r = render_page(html, viewport_width=200)
        self.assertGreater(len(r.png), 0)

    def test_deeply_mismatched_tags_do_not_crash(self):
        r = render_page('<b><i><u>text</b>more</i>even more</u>tail', viewport_width=200)
        self.assertGreater(len(r.png), 0)

    def test_script_with_html_like_string_literal(self):
        # A literal "</div>" (not "</script>") inside a JS string must not
        # be parsed as markup -- <script> is only watching for its own
        # closing tag, not arbitrary HTML-looking substrings.
        html = '<script>if (x) { log("</div> looks like a tag but is not"); }</script><p>real</p>'
        doc = render_page(html).dom
        self.assertEqual(len(doc.find_all('div')), 0)
        self.assertEqual(len(doc.find_all('p')), 1)

    def test_unescaped_closing_script_tag_inside_string_ends_script_early(self):
        # This is genuine, spec-accurate behavior (not a bug): the HTML
        # tokenizer has no idea it's inside a JS string literal, so a
        # literal "</script>" -- even inside quotes -- really does end
        # the element early. It's exactly why real code must escape it as
        # "<\/script>" to embed such text safely. Documented here so the
        # behavior is intentional, not accidentally "fixed" later.
        html = '<script>var s = "</script>"; after</script>'
        doc = render_page(html).dom
        script = doc.find_all('script')[0]
        self.assertEqual(script.text_content(), 'var s = "')


class TestFullPageIntegration(unittest.TestCase):
    def test_example_hello_page_renders(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'examples', 'hello.html')
        with open(path, encoding='utf-8') as f:
            html_text = f.read()
        r = render_page(html_text, viewport_width=500)
        self.assertGreater(r.canvas.width, 0)
        self.assertGreater(r.canvas.height, 0)
        self.assertEqual(r.png[:8], b'\x89PNG\r\n\x1a\n')

    def test_example_flex_page_renders(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'examples', 'flex.html')
        with open(path, encoding='utf-8') as f:
            html_text = f.read()
        r = render_page(html_text, viewport_width=500)
        self.assertEqual(r.png[:8], b'\x89PNG\r\n\x1a\n')


class TestVisualizerHelpers(unittest.TestCase):
    def test_dump_cssom_text_lists_every_rule(self):
        r = render_page('<p>x</p>', 'p{color:red;} .x{color:blue;}', viewport_width=100)
        text = dump_cssom_text(r.stylesheet)
        self.assertIn('color: red', text)
        self.assertIn('color: blue', text)

    def test_dump_cascade_text_includes_matched_selector(self):
        r = render_page('<p class="hi">x</p>', '.hi{color:red;}', viewport_width=100)
        text = dump_cascade_text(r.dom, r.styles)
        self.assertIn('.hi', text)

    def test_layout_svg_is_well_formed_and_matches_canvas_size(self):
        r = render_page('<div style="width:50px;height:30px;"></div>', viewport_width=100)
        svg = layout_to_svg(r.layout_root)
        self.assertTrue(svg.startswith('<svg'))
        self.assertTrue(svg.endswith('</svg>'))
        self.assertIn(f'width="{r.canvas.width}"', svg)


if __name__ == '__main__':
    unittest.main()
