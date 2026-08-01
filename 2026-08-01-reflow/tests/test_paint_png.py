import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reflow.browser import render_page
from reflow.colors import parse_color
from reflow.png_encoder import Canvas, encode_rgb


def decode_png_pixels(png_bytes):
    """A tiny, independent PNG *decoder* (distinct code path from the
    encoder under test) used only so tests can assert on real pixel
    values instead of trusting the encoder's own math."""
    assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8
    width = height = None
    idat = b''
    while pos < len(png_bytes):
        length = struct.unpack('>I', png_bytes[pos:pos + 4])[0]
        ctype = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + length]
        if ctype == b'IHDR':
            width, height = struct.unpack('>II', data[:8])
        elif ctype == b'IDAT':
            idat += data
        pos += 8 + length + 4
    raw = zlib.decompress(idat)
    row_bytes = width * 3
    pixels = {}
    offset = 0
    for y in range(height):
        filter_type = raw[offset]
        assert filter_type == 0, 'test decoder only supports filter type 0 (None)'
        row = raw[offset + 1:offset + 1 + row_bytes]
        for x in range(width):
            pixels[(x, y)] = tuple(row[x * 3:x * 3 + 3])
        offset += 1 + row_bytes
    return width, height, pixels


class TestPNGEncoder(unittest.TestCase):
    def test_signature_and_chunk_structure(self):
        canvas = Canvas(4, 4, (0, 0, 0))
        png = canvas.to_png()
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertIn(b'IHDR', png)
        self.assertIn(b'IDAT', png)
        self.assertIn(b'IEND', png)

    def test_roundtrip_solid_color(self):
        canvas = Canvas(5, 3, (10, 20, 30))
        w, h, pixels = decode_png_pixels(canvas.to_png())
        self.assertEqual((w, h), (5, 3))
        self.assertTrue(all(v == (10, 20, 30) for v in pixels.values()))

    def test_fill_rect_and_roundtrip(self):
        canvas = Canvas(10, 10, (255, 255, 255))
        canvas.fill_rect(2, 2, 4, 4, (255, 0, 0))
        _w, _h, pixels = decode_png_pixels(canvas.to_png())
        self.assertEqual(pixels[(3, 3)], (255, 0, 0))
        self.assertEqual(pixels[(0, 0)], (255, 255, 255))
        self.assertEqual(pixels[(9, 9)], (255, 255, 255))

    def test_fill_rect_clips_out_of_bounds(self):
        canvas = Canvas(5, 5, (0, 0, 0))
        canvas.fill_rect(-3, -3, 10, 10, (1, 2, 3))  # must not raise or corrupt memory
        _w, _h, pixels = decode_png_pixels(canvas.to_png())
        self.assertEqual(pixels[(4, 4)], (1, 2, 3))

    def test_encode_rgb_rejects_wrong_length(self):
        with self.assertRaises(ValueError):
            encode_rgb(bytes([0, 0, 0]), 2, 2)


class TestColors(unittest.TestCase):
    def test_named_color(self):
        self.assertEqual(parse_color('red'), (255, 0, 0))

    def test_hex_short_and_long(self):
        self.assertEqual(parse_color('#f00'), (255, 0, 0))
        self.assertEqual(parse_color('#ff0000'), (255, 0, 0))

    def test_rgb_function(self):
        self.assertEqual(parse_color('rgb(10, 20, 30)'), (10, 20, 30))

    def test_transparent_and_none_return_none(self):
        self.assertIsNone(parse_color('transparent'))
        self.assertIsNone(parse_color('none'))
        self.assertIsNone(parse_color(None))

    def test_case_insensitive(self):
        self.assertEqual(parse_color('RED'), (255, 0, 0))


class TestPaintIntegration(unittest.TestCase):
    def test_background_color_painted_at_correct_pixels(self):
        r = render_page('<div id="d">x</div>', 'div{background-color:red; width:20px; height:20px;}', viewport_width=50)
        _w, _h, pixels = decode_png_pixels(r.png)
        self.assertEqual(pixels[(5, 5)], (255, 0, 0))
        self.assertEqual(pixels[(45, 5)], (255, 255, 255))

    def test_text_color_produces_non_background_pixels(self):
        r = render_page('<p>HELLO</p>', 'p{color:blue;}', viewport_width=100)
        _w, _h, pixels = decode_png_pixels(r.png)
        colors_seen = set(pixels.values())
        self.assertIn((0, 0, 255), colors_seen, 'blue text glyph pixels should appear somewhere on the canvas')

    def test_canvas_dimensions_match_layout(self):
        r = render_page('<div style="width:123px;height:45px;"></div>', viewport_width=200)
        self.assertEqual(r.canvas.width, 200)
        self.assertEqual(r.canvas.height, 45)


if __name__ == '__main__':
    unittest.main()
