import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import huffman
from spectral.bitstream import BitWriter, BitReader


class TestHuffman(unittest.TestCase):
    def test_standard_tables_are_prefix_free(self):
        for table in huffman.STD_TABLES.values():
            codes = list(table.encode_map.values())
            # No code may be a bit-prefix of another (the defining property
            # of a valid, uniquely-decodable prefix code).
            for i, (c1, l1) in enumerate(codes):
                for c2, l2 in codes[i + 1:]:
                    shorter, longer = (l1, l2) if l1 <= l2 else (l2, l1)
                    a, b = (c1, c2) if l1 <= l2 else (c2, c1)
                    self.assertNotEqual(a, b >> (longer - shorter))

    def test_standard_tables_satisfy_kraft_inequality(self):
        # Any valid prefix code satisfies sum(2^-length) <= 1 (Kraft's
        # inequality). JPEG's own Annex K tables are deliberately *not*
        # complete (sum < 1): the spec reserves the all-ones code point
        # at the deepest length so it never collides with a marker-like
        # bit pattern. The DC luma table's shortfall is exactly 2^-9
        # (one reserved leaf at its deepest length, 9 bits) -- checked
        # explicitly here so a real transcription error in BITS (which
        # would shift this by some *other* amount) wouldn't be mistaken
        # for the expected, documented reservation.
        for key, table in huffman.STD_TABLES.items():
            total = sum(2.0 ** -length for _, length in table.encode_map.values())
            self.assertLessEqual(total, 1.0 + 1e-9, msg=f"{key} violates Kraft's inequality")
        dc_luma_total = sum(2.0 ** -length for _, length in huffman.STD_TABLES[("dc", "luma")].encode_map.values())
        self.assertAlmostEqual(1.0 - dc_luma_total, 2.0 ** -9, places=9)

    def test_encode_decode_round_trip_standard_tables(self):
        rng = random.Random(11)
        for table in huffman.STD_TABLES.values():
            symbols = list(table.encode_map.keys())
            seq = [rng.choice(symbols) for _ in range(300)]
            w = BitWriter()
            for s in seq:
                table.encode_symbol(w, s)
            w.align_byte()
            r = BitReader(w.getvalue())
            for s in seq:
                self.assertEqual(table.decode_symbol(r), s)

    def test_build_codes_known_two_symbol_case(self):
        # BITS says one code of length 1, one of length 2: classic minimal
        # example. Canonical assignment must give the length-1 code 0b0
        # and the length-2 code 0b10 (not 0b11, which would violate the
        # "consecutive, ascending" canonical rule).
        bits = [1, 1] + [0] * 14
        values = [ord("A"), ord("B")]
        codes = huffman.build_codes(bits, values)
        self.assertEqual(codes[ord("A")], (0b0, 1))
        self.assertEqual(codes[ord("B")], (0b10, 2))

    def test_optimize_table_single_symbol(self):
        table, used_optimized = huffman.optimize_table({5: 100}, [0] * 16, [])
        self.assertTrue(used_optimized)
        self.assertEqual(table.encode_map[5], (0, 1))

    def test_optimize_table_empty_frequencies_falls_back(self):
        table, used_optimized = huffman.optimize_table({}, huffman.STD_DC_LUMA_BITS, huffman.STD_DC_LUMA_VALS)
        self.assertFalse(used_optimized)
        self.assertEqual(table.bits, huffman.STD_DC_LUMA_BITS)

    def test_optimize_table_beats_or_matches_standard_size(self):
        # A skewed real-world-like distribution (most symbols near 0,
        # power-law tail) should encode to fewer total bits with an
        # optimized table than the fixed standard table.
        freqs = {}
        for i in range(12):
            freqs[i] = max(1, 2000 // (2 ** i))
        std = huffman.STD_TABLES[("dc", "luma")]
        opt, used = huffman.optimize_table(freqs, huffman.STD_DC_LUMA_BITS, huffman.STD_DC_LUMA_VALS)
        self.assertTrue(used)

        def total_bits(table):
            return sum(freqs[s] * table.encode_map[s][1] for s in freqs)

        self.assertLessEqual(total_bits(opt), total_bits(std))

    def test_optimize_table_fibonacci_worst_case_falls_back_cleanly(self):
        # The classic pathological input for unbounded-height Huffman
        # trees: frequencies shaped like the Fibonacci sequence force
        # maximum tree depth (one new level per merge). With enough
        # symbols this exceeds JPEG's 16-bit code length limit, and the
        # implementation must fall back to the standard table rather than
        # emit a table no JPEG decoder could read.
        fib = [1, 1]
        while len(fib) < 30:
            fib.append(fib[-1] + fib[-2])
        freqs = {i: fib[i] for i in range(30)}
        table, used_optimized = huffman.optimize_table(freqs, huffman.STD_AC_LUMA_BITS, huffman.STD_AC_LUMA_VALS)
        self.assertFalse(used_optimized)
        self.assertEqual(table.bits, huffman.STD_AC_LUMA_BITS)
        self.assertLessEqual(table.max_code_length, huffman.MAX_CODE_LENGTH)


if __name__ == "__main__":
    unittest.main()
