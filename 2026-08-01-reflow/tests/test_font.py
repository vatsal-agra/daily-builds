import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow import font


class TestFont(unittest.TestCase):
    def test_every_printable_ascii_char_has_a_glyph_or_fallback(self):
        for code in range(32, 127):
            ch = chr(code)
            pixels = font.glyph_pixels(ch)
            if ch != ' ':
                self.assertGreater(len(pixels), 0, f'{ch!r} produced no pixels at all')

    def test_space_is_blank(self):
        self.assertEqual(font.glyph_pixels(' '), set())

    def test_measure_text_scales_linearly_with_scale_factor(self):
        w1 = font.measure_text('hello', scale=1)
        w2 = font.measure_text('hello', scale=2)
        self.assertEqual(w2, w1 * 2)

    def test_measure_text_scales_with_length(self):
        self.assertEqual(font.measure_text('aa', 1), 2 * font.measure_text('a', 1))

    def test_glyph_cache_is_consistent(self):
        first = font.glyph_pixels('A')
        second = font.glyph_pixels('A')
        self.assertEqual(first, second)

    def test_render_glyph_respects_scale(self):
        pixels_1x = list(font.render_glyph('A', scale=1))
        pixels_2x = list(font.render_glyph('A', scale=2))
        self.assertEqual(len(pixels_2x), len(pixels_1x) * 4, 'area should scale with scale^2')

    def test_unknown_character_gets_a_fallback_box_not_a_crash(self):
        pixels = font.glyph_pixels('é')  # not in the hand-authored table
        self.assertGreater(len(pixels), 0)


if __name__ == '__main__':
    unittest.main()
