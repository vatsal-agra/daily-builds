import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import bmp, png_reader, testimages


def _write_test_png(path, width, height, pixels_rgb):
    """Construct a minimal, valid, non-interlaced 8-bit RGB PNG by hand
    for test fixtures. This is test scaffolding, not part of Spectral's
    supported I/O surface (Spectral only *reads* PNGs, via png_reader.py,
    to get real pixels in as encoder input; it never writes them)."""
    def chunk(ctype, data):
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        for x in range(width):
            r, g, b = pixels_rgb[y * width + x]
            raw += bytes([r, g, b])
    idat = zlib.compress(bytes(raw), 9)
    data = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)


class TestBmp(unittest.TestCase):
    def test_round_trip(self):
        for gen in (testimages.gradient, testimages.checkerboard):
            img = gen(20, 13)
            path = "/tmp/_spectral_test.bmp"
            bmp.write_bmp(path, img)
            back = bmp.read_bmp(path)
            self.assertEqual((back.width, back.height), (img.width, img.height))
            self.assertEqual(back.r, img.r)
            self.assertEqual(back.g, img.g)
            self.assertEqual(back.b, img.b)
            os.remove(path)

    def test_odd_width_padding(self):
        # width=5 -> row_size must round up to a 4-byte boundary.
        img = testimages.solid(5, 3, (10, 20, 30))
        path = "/tmp/_spectral_test_odd.bmp"
        bmp.write_bmp(path, img)
        back = bmp.read_bmp(path)
        self.assertEqual(back.r, img.r)
        os.remove(path)

    def test_rejects_wrong_magic(self):
        path = "/tmp/_spectral_not_a_bmp.bmp"
        with open(path, "wb") as f:
            f.write(b"not a bmp" + b"\x00" * 50)
        with self.assertRaises(ValueError):
            bmp.read_bmp(path)
        os.remove(path)


class TestPngReader(unittest.TestCase):
    def test_reads_hand_built_rgb_png(self):
        pixels = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)]
        path = "/tmp/_spectral_test.png"
        _write_test_png(path, 2, 2, pixels)
        img = png_reader.read_png(path)
        self.assertEqual((img.width, img.height), (2, 2))
        self.assertEqual(list(zip(img.r, img.g, img.b)), pixels)
        os.remove(path)

    def test_reads_larger_gradient_png_matches_source(self):
        src = testimages.gradient(24, 17)
        pixels = list(zip(src.r, src.g, src.b))
        path = "/tmp/_spectral_test_grad.png"
        _write_test_png(path, 24, 17, pixels)
        img = png_reader.read_png(path)
        self.assertEqual(img.r, src.r)
        self.assertEqual(img.g, src.g)
        self.assertEqual(img.b, src.b)
        os.remove(path)

    def test_rejects_wrong_signature(self):
        path = "/tmp/_spectral_not_a_png.png"
        with open(path, "wb") as f:
            f.write(b"not a png" + b"\x00" * 50)
        with self.assertRaises(ValueError):
            png_reader.read_png(path)
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
