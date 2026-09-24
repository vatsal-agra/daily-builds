import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import encoder, testimages
from spectral.markers import parse, JpegParseError, write_soi


class TestMarkers(unittest.TestCase):
    def setUp(self):
        self.image = testimages.gradient(16, 16)
        self.valid_jpeg = encoder.encode(self.image, quality=70, subsampling="420")

    def test_parses_a_real_encoded_file(self):
        frame = parse(self.valid_jpeg)
        self.assertEqual((frame.width, frame.height), (16, 16))
        self.assertEqual(len(frame.components), 3)
        self.assertFalse(frame.progressive)

    def test_missing_soi_raises_clean_error(self):
        with self.assertRaises(JpegParseError):
            parse(b"not a jpeg file at all")

    def test_empty_bytes_raises_clean_error(self):
        with self.assertRaises(JpegParseError):
            parse(b"")

    def test_truncated_right_after_soi_raises_clean_error(self):
        with self.assertRaises(JpegParseError):
            parse(write_soi())

    def test_truncated_mid_segment_raises_clean_error(self):
        truncated = self.valid_jpeg[:30]
        with self.assertRaises(JpegParseError):
            parse(truncated)

    def test_corrupt_segment_length_raises_clean_error(self):
        data = bytearray(self.valid_jpeg)
        # Find the APP0 marker (0xFF 0xE0) and corrupt its length field.
        idx = data.index(bytes([0xFF, 0xE0]))
        data[idx + 2] = 0xFF
        data[idx + 3] = 0xFF
        with self.assertRaises(JpegParseError):
            parse(bytes(data))

    def test_no_sof_raises_clean_error(self):
        # SOI immediately followed by EOI: no frame header at all.
        with self.assertRaises(JpegParseError):
            parse(bytes([0xFF, 0xD8, 0xFF, 0xD9]))

    def test_corrupt_dqt_precision_nibble_raises_clean_error_not_struct_error(self):
        # Regression: a corrupted DQT segment can claim 16-bit table
        # precision (Pq=1) in a payload only sized for the real 8-bit
        # table, which used to raise a raw struct.error trying to
        # unpack 128 bytes from a ~65-byte payload. Found by a random
        # bit-flip fuzz run, not by inspection.
        data = bytearray(self.valid_jpeg)
        dqt_idx = data.index(bytes([0xFF, 0xDB]))
        precision_byte_offset = dqt_idx + 4  # marker(2) + length(2) + Pq/Tq byte
        data[precision_byte_offset] |= 0x10  # set Pq=1 (16-bit) without resizing the segment
        with self.assertRaises(JpegParseError):
            parse(bytes(data))

    def test_flips_dont_crash_the_parser(self):
        # Adversarial fuzz: flip single bytes throughout a real file and
        # require every result to either parse or raise JpegParseError --
        # never a raw traceback.
        for i in range(0, len(self.valid_jpeg), 7):
            data = bytearray(self.valid_jpeg)
            data[i] ^= 0xFF
            try:
                parse(bytes(data))
            except JpegParseError:
                pass
            except Exception as e:  # pragma: no cover - this is the failure case
                self.fail(f"byte flip at {i} raised {type(e).__name__}: {e} instead of JpegParseError")


if __name__ == "__main__":
    unittest.main()
