import struct
import unittest
import zlib

from folio.png_encoder import encode_png


def _decode_png(data):
    """A tiny independent PNG reader (bypasses Folio's own code entirely)
    used only to verify encode_png's output -- so this test doesn't just
    check "Folio's encoder agrees with itself"."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    chunks = {}
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        crc_stored = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        crc_actual = zlib.crc32(tag + payload) & 0xFFFFFFFF
        assert crc_stored == crc_actual, f"bad CRC for chunk {tag}"
        chunks.setdefault(tag, []).append(payload)
        pos += 12 + length
        if tag == b"IEND":
            break
    width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(
        ">IIBBBBB", chunks[b"IHDR"][0]
    )
    raw = zlib.decompress(b"".join(chunks[b"IDAT"]))
    return width, height, bit_depth, color_type, raw


class TestPngEncoder(unittest.TestCase):
    def test_signature_and_structure(self):
        pixels = bytes([255, 0, 0] * 4)  # 2x2 solid red
        data = encode_png(pixels, 2, 2)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    def test_independent_decode_recovers_exact_pixels(self):
        # A small deterministic pattern: 3x2 image, distinct RGB per pixel.
        w, h = 3, 2
        pixels = bytearray()
        for y in range(h):
            for x in range(w):
                pixels += bytes([x * 40, y * 80, (x + y) * 10])
        data = encode_png(bytes(pixels), w, h)
        width, height, bit_depth, color_type, raw = _decode_png(data)
        self.assertEqual((width, height), (w, h))
        self.assertEqual(bit_depth, 8)
        self.assertEqual(color_type, 2)  # truecolor RGB, no alpha

        # raw has one filter-type byte prepended per scanline (row).
        stride = w * 3
        recovered = bytearray()
        for row in range(h):
            start = row * (stride + 1)
            filter_byte = raw[start]
            self.assertEqual(filter_byte, 0)  # "None" filter, as documented
            recovered += raw[start + 1:start + 1 + stride]
        self.assertEqual(bytes(recovered), bytes(pixels))

    def test_mismatched_buffer_length_raises(self):
        with self.assertRaises(ValueError):
            encode_png(bytes([0, 0, 0]), 2, 2)  # only 1 pixel of data for a 2x2 image

    def test_1x1_minimal_image(self):
        data = encode_png(bytes([1, 2, 3]), 1, 1)
        width, height, _, _, raw = _decode_png(data)
        self.assertEqual((width, height), (1, 1))
        self.assertEqual(raw, bytes([0, 1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
