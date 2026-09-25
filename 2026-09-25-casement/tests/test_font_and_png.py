import string
import unittest
import zlib

from casement.font import GLYPH_H, GLYPH_W, advance_width, glyph_bitmap
from casement.png_encoder import encode_rgba


class TestFont(unittest.TestCase):
    def test_every_printable_ascii_has_some_ink_or_is_space(self):
        for ch in string.printable:
            if ch.isspace():
                continue
            bmp = glyph_bitmap(ch)
            self.assertEqual(len(bmp), GLYPH_H)
            self.assertEqual(len(bmp[0]), GLYPH_W)
            has_ink = any(any(row) for row in bmp)
            self.assertTrue(has_ink, f"glyph for {ch!r} is entirely blank")

    def test_space_is_blank(self):
        bmp = glyph_bitmap(" ")
        self.assertFalse(any(any(row) for row in bmp))

    def test_lowercase_falls_back_to_uppercase_shape(self):
        self.assertEqual(glyph_bitmap("a"), glyph_bitmap("A"))

    def test_advance_width_scales_with_font_size(self):
        self.assertAlmostEqual(advance_width(16.0) * 2, advance_width(32.0), places=3)


class TestPNGEncoder(unittest.TestCase):
    def test_encode_produces_valid_png_structure(self):
        w, h = 4, 3
        pixels = bytearray(w * h * 4)
        for i in range(0, len(pixels), 4):
            pixels[i:i + 4] = bytes((255, 0, 0, 255))
        data = encode_rgba(w, h, pixels)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn(b"IHDR", data)
        self.assertIn(b"IDAT", data)
        self.assertIn(b"IEND", data)

    def test_round_trip_via_zlib_inflate(self):
        w, h = 2, 2
        pixels = bytearray()
        colors = [(10, 20, 30, 255), (40, 50, 60, 255), (70, 80, 90, 255), (100, 110, 120, 255)]
        for c in colors:
            pixels += bytes(c)
        data = encode_rgba(w, h, pixels)
        # Manually extract the IDAT chunk and inflate it to verify the
        # per-scanline filter-byte framing this encoder writes.
        idat_pos = data.index(b"IDAT")
        length = int.from_bytes(data[idat_pos - 4:idat_pos], "big")
        idat = data[idat_pos + 4:idat_pos + 4 + length]
        raw = zlib.decompress(idat)
        stride = w * 4 + 1  # +1 filter-type byte per scanline
        self.assertEqual(len(raw), stride * h)
        for y in range(h):
            row = raw[y * stride:(y + 1) * stride]
            self.assertEqual(row[0], 0)  # filter type 'None'
            for x in range(w):
                px = row[1 + x * 4: 1 + x * 4 + 4]
                self.assertEqual(bytes(px), bytes(colors[y * w + x]))


if __name__ == "__main__":
    unittest.main()
