import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral.bitstream import BitWriter, BitReader, bits_for_value, extend_receive


class TestBitstream(unittest.TestCase):
    def test_write_read_round_trip(self):
        w = BitWriter()
        values = [(0b101, 3), (0b11111111, 8), (0b1, 1), (0b0, 1), (0b110101010, 9)]
        for v, n in values:
            w.write_bits(v, n)
        w.align_byte()
        data = w.getvalue()
        r = BitReader(data)
        for v, n in values:
            self.assertEqual(r.read_bits(n), v)

    def test_byte_stuffing_round_trip(self):
        # 0xFF must be immediately followed by a stuffed 0x00 on the wire.
        w = BitWriter()
        w.write_bits(0xFF, 8)
        w.write_bits(0xD9, 8)  # looks like an EOI marker if unstuffed wrong
        w.align_byte()
        raw = w.getvalue()
        self.assertEqual(raw[0], 0xFF)
        self.assertEqual(raw[1], 0x00)  # the stuffed byte
        r = BitReader(raw)
        self.assertEqual(r.read_bits(8), 0xFF)
        self.assertEqual(r.read_bits(8), 0xD9)

    def test_reader_stops_at_real_marker(self):
        data = bytes([0b10101010, 0xFF, 0xD9])  # a real marker (not stuffed)
        r = BitReader(data)
        self.assertEqual(r.read_bits(8), 0b10101010)
        self.assertIsNone(r.read_bit())
        self.assertEqual(r.hit_marker, 0xD9)

    def test_extend_receive_zero_category(self):
        self.assertEqual(extend_receive(0, 0), 0)

    def test_bits_for_value_extend_receive_are_inverses(self):
        for v in list(range(-2000, 2001)):
            nbits, coded = bits_for_value(v)
            back = extend_receive(coded, nbits)
            self.assertEqual(back, v)

    def test_random_round_trip_many_widths(self):
        rng = random.Random(7)
        w = BitWriter()
        plan = []
        for _ in range(500):
            n = rng.randint(1, 16)
            v = rng.getrandbits(n)
            plan.append((v, n))
            w.write_bits(v, n)
        w.align_byte()
        r = BitReader(w.getvalue())
        for v, n in plan:
            self.assertEqual(r.read_bits(n), v)


if __name__ == "__main__":
    unittest.main()
