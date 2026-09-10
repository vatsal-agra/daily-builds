import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from png_encoder import Canvas, decode_png, encode_png


class EncodeDecodeRoundTripTests(unittest.TestCase):
    def test_solid_color_round_trips(self):
        w, h = 10, 8
        data = bytes([12, 34, 56, 255]) * (w * h)
        png = encode_png(w, h, data)
        rw, rh, rdata = decode_png(png)
        self.assertEqual((rw, rh), (w, h))
        self.assertEqual(rdata, data)

    def test_gradient_round_trips(self):
        w, h = 16, 16
        data = bytearray()
        for y in range(h):
            for x in range(w):
                data += bytes([x * 16 % 256, y * 16 % 256, (x + y) % 256, 255])
        png = encode_png(w, h, bytes(data))
        rw, rh, rdata = decode_png(png)
        self.assertEqual(rdata, bytes(data))

    def test_png_signature_present(self):
        png = encode_png(2, 2, bytes([255, 0, 0, 255]) * 4)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_ihdr_chunk_dimensions(self):
        import struct
        png = encode_png(37, 19, bytes([0, 0, 0, 255]) * (37 * 19))
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (37, 19))


class CanvasTests(unittest.TestCase):
    def test_fill_rect_sets_pixels(self):
        c = Canvas(10, 10, background=(255, 255, 255, 255))
        c.fill_rect(2, 2, 4, 4, (255, 0, 0, 255))
        idx = (3 * 10 + 3) * 4
        self.assertEqual(tuple(c.pixels[idx:idx + 4]), (255, 0, 0, 255))
        idx_outside = (0 * 10 + 0) * 4
        self.assertEqual(tuple(c.pixels[idx_outside:idx_outside + 4]), (255, 255, 255, 255))

    def test_alpha_blending(self):
        c = Canvas(4, 4, background=(0, 0, 0, 255))
        c.fill_rect(0, 0, 4, 4, (255, 255, 255, 128))
        idx = 0
        r, g, b, a = c.pixels[idx:idx + 4]
        self.assertTrue(100 < r < 150)
        self.assertEqual(a, 255)

    def test_out_of_bounds_is_clipped_not_crashed(self):
        c = Canvas(5, 5)
        c.fill_rect(-10, -10, 100, 100, (1, 2, 3, 255))  # should not raise
        c.set_pixel(999, 999, (1, 2, 3, 255))  # should not raise

    def test_to_png_bytes_is_a_real_png(self):
        c = Canvas(20, 20)
        c.fill_rect(0, 0, 20, 20, (10, 20, 30, 255))
        data = c.to_png_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")


@unittest.skipUnless(_file_available := (os.system("which file > /dev/null 2>&1") == 0),
                      "system `file` utility not available")
class FileUtilityCrossCheckTests(unittest.TestCase):
    """Independently confirms a rendered PNG is a real, well-formed PNG by
    asking the OS's own `file` utility -- not just our own decoder."""

    def test_file_utility_recognizes_our_png(self):
        c = Canvas(33, 17)
        c.fill_rect(0, 0, 33, 17, (200, 100, 50, 255))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(c.to_png_bytes())
            path = f.name
        try:
            result = subprocess.run(["file", path], capture_output=True, text=True)
            self.assertIn("PNG image data", result.stdout)
            self.assertIn("33 x 17", result.stdout)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
