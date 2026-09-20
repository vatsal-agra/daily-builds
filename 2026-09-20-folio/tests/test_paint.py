import unittest

from folio.engine import render_html
from folio.paint import parse_color


class TestColorParsing(unittest.TestCase):
    def test_named_color(self):
        self.assertEqual(parse_color("red"), (255, 0, 0))
        self.assertEqual(parse_color("Blue"), (0, 0, 255))  # case-insensitive

    def test_hex_6_digit(self):
        self.assertEqual(parse_color("#ff0000"), (255, 0, 0))

    def test_hex_3_digit(self):
        self.assertEqual(parse_color("#f00"), (255, 0, 0))

    def test_rgb_function(self):
        self.assertEqual(parse_color("rgb(10, 20, 30)"), (10, 20, 30))

    def test_rgb_clamps_out_of_range(self):
        self.assertEqual(parse_color("rgb(999, -50, 999)"), (255, 0, 255))

    def test_transparent_is_none(self):
        self.assertIsNone(parse_color("transparent"))

    def test_invalid_color_falls_back_without_crashing(self):
        self.assertEqual(parse_color("not-a-color", fallback=(1, 2, 3)), (1, 2, 3))

    def test_none_value_uses_fallback(self):
        self.assertEqual(parse_color(None, fallback=(9, 9, 9)), (9, 9, 9))


class TestPaintCommandGeneration(unittest.TestCase):
    def test_background_and_text_commands_present(self):
        html = '<div style="background-color: yellow;">hi</div>'
        page = render_html(html, viewport_width=200)
        kinds = [c.kind for c in page.paint_commands]
        self.assertIn("rect", kinds)
        self.assertIn("text", kinds)

    def test_transparent_background_produces_no_rect(self):
        html = "<div>hi</div>"
        page = render_html(html, viewport_width=200)
        rects = [c for c in page.paint_commands if c.kind == "rect"]
        self.assertEqual(len(rects), 0)

    def test_anonymous_boxes_never_painted(self):
        """Anonymous inline-wrapper/line boxes must not generate their own
        background/border paint command (they'd double-paint the real
        parent element's background)."""
        html = '<div style="background-color: pink;">some wrapped text here</div>'
        page = render_html(html, viewport_width=50)
        rects = [c for c in page.paint_commands if c.kind == "rect"]
        self.assertEqual(len(rects), 1)

    def test_border_paint_commands_use_resolved_color(self):
        html = '<div style="color:green; border: 2px solid currentColor;">x</div>'
        page = render_html(html, viewport_width=200)
        border_rects = [c for c in page.paint_commands if c.kind == "rect" and c.color == (0, 128, 0)]
        self.assertGreater(len(border_rects), 0)


if __name__ == "__main__":
    unittest.main()
