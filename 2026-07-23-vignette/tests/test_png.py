import struct
import unittest
import zlib

from vignette import png
from vignette.image import gradient


class TestPNG(unittest.TestCase):
    def _chunks(self, data):
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        pos = 8
        out = []
        while pos < len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            tag = data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + length]
            crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
            self.assertEqual(zlib.crc32(tag + body) & 0xFFFFFFFF, crc)
            out.append((tag, body))
            pos += 12 + length
        return out

    def test_structure_and_dimensions(self):
        img = gradient(13, 9)
        data = png.encode_png(img)
        chunks = self._chunks(data)
        tags = [t for t, _ in chunks]
        self.assertEqual(tags, [b"IHDR", b"IDAT", b"IEND"])
        w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", chunks[0][1])
        self.assertEqual((w, h), (13, 9))
        self.assertEqual((depth, ctype), (8, 2))  # 8-bit truecolor, no alpha

    def test_decompressed_length_matches_scanline_math(self):
        img = gradient(20, 15)
        data = png.encode_png(img)
        chunks = self._chunks(data)
        idat = next(b for t, b in chunks if t == b"IDAT")
        raw = zlib.decompress(idat)
        expected = (img.width * 3 + 1) * img.height  # +1 filter-type byte/row
        self.assertEqual(len(raw), expected)

    def test_pixels_recoverable_by_unfiltering(self):
        img = gradient(6, 4)
        data = png.encode_png(img)
        chunks = self._chunks(data)
        idat = next(b for t, b in chunks if t == b"IDAT")
        raw = zlib.decompress(idat)

        def paeth(a, b, c):
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            if pa <= pb and pa <= pc:
                return a
            if pb <= pc:
                return b
            return c

        w, h = img.width, img.height
        stride = w * 3
        prev = bytearray(stride)
        out_pixels = []
        pos = 0
        for y in range(h):
            ftype = raw[pos]
            pos += 1
            row = bytearray(stride)
            for x in range(stride):
                a = row[x - 3] if x >= 3 else 0
                b = prev[x]
                c = prev[x - 3] if x >= 3 else 0
                self.assertEqual(ftype, 4)  # this encoder always uses Paeth
                row[x] = (raw[pos + x] + paeth(a, b, c)) & 0xFF
            pos += stride
            for x in range(0, stride, 3):
                out_pixels.append((row[x], row[x + 1], row[x + 2]))
            prev = row

        self.assertEqual(out_pixels, img.pixels)


if __name__ == "__main__":
    unittest.main()
