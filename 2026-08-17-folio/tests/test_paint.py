import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import render
from folio.paint import paint_svg, page_height


class TestPaint(unittest.TestCase):
    def test_produces_well_formed_svg_root(self):
        _, _, root, t = render("<h1>Hi</h1><p>Some text.</p>")
        svg = paint_svg(root, 800, page_height(root))
        self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"'))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertEqual(svg.count("<svg"), 1)
        self.assertEqual(svg.count("</svg>"), 1)

    def test_background_color_painted(self):
        _, _, root, t = render('<div style="background-color:#ff0000;width:10px;height:10px">x</div>')
        svg = paint_svg(root, 800, page_height(root))
        self.assertIn("rgb(255,0,0)", svg)

    def test_text_content_escaped(self):
        # Each word becomes its own positioned <text> fragment, so check the
        # escaped pieces individually rather than one contiguous run.
        _, _, root, t = render("<p>1 &lt; 2 &amp;&amp; 3 &gt; 0</p>")
        svg = paint_svg(root, 800, page_height(root))
        for piece in (">&lt;<", ">&amp;&amp;<", ">&gt;<"):
            self.assertIn(piece, svg)
        # and never a raw, unescaped '<' or stray '&' inside a <text> body.
        for m in re.finditer(r"<text[^>]*>([^<]*)</text>", svg):
            self.assertNotRegex(m.group(1), r"&(?!amp;|lt;|gt;|quot;|apos;)")
        self.assertNotIn("<p>", svg)  # never leak raw markup as an unescaped SVG child

    def test_display_none_not_painted(self):
        _, _, root, t = render('<div style="display:none">hidden text should not appear</div>')
        svg = paint_svg(root, 800, page_height(root))
        self.assertNotIn("hidden text should not appear", svg)

    def test_empty_body_does_not_crash(self):
        _, _, root, t = render("")
        svg = paint_svg(root, 800, page_height(root))
        self.assertIn("<svg", svg)

    def test_svg_dimensions_are_finite_and_positive(self):
        _, _, root, t = render("<div style='height:2000px'>x</div>")
        h = page_height(root)
        self.assertGreater(h, 0)
        self.assertLess(h, 1_000_000)


if __name__ == "__main__":
    unittest.main()
