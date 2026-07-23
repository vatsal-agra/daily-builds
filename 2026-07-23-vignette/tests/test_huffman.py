import random
import unittest

from vignette import huffman, tables


class TestHuffTable(unittest.TestCase):
    def test_standard_tables_build_without_error(self):
        for bits, vals in [
            (tables.STD_DC_LUMINANCE_BITS, tables.STD_DC_LUMINANCE_VALUES),
            (tables.STD_DC_CHROMINANCE_BITS, tables.STD_DC_CHROMINANCE_VALUES),
            (tables.STD_AC_LUMINANCE_BITS, tables.STD_AC_LUMINANCE_VALUES),
            (tables.STD_AC_CHROMINANCE_BITS, tables.STD_AC_CHROMINANCE_VALUES),
        ]:
            t = huffman.HuffTable(bits, vals)
            self.assertEqual(len(t.encode_map), len(vals))
            self.assertEqual(len(t.decode_map), len(vals))
            self.assertLessEqual(t.max_code_length, 16)

    def test_codes_are_prefix_free(self):
        t = huffman.HuffTable(
            tables.STD_AC_LUMINANCE_BITS, tables.STD_AC_LUMINANCE_VALUES
        )
        codes = [(length, code) for (code, length) in t.encode_map.values()]
        # No code string is a prefix of another: check by expanding to bit
        # strings and comparing pairwise (alphabet is small enough, 162).
        strings = [format(code, f"0{length}b") for length, code in codes]
        for i, a in enumerate(strings):
            for b in strings[i + 1:]:
                self.assertFalse(a.startswith(b) or b.startswith(a))

    def test_bit_writer_reader_round_trip(self):
        random.seed(4)
        bits = [(random.getrandbits(1), 1) for _ in range(50)]
        # also throw in some multi-bit values, including ones that produce
        # 0xFF bytes (byte-stuffing exercise)
        values = [(0xFF, 8), (0x00, 8), (0b101, 3), (0b11111111, 8), (0, 1), (1, 1)]
        writer = huffman.BitWriter()
        for v, n in bits:
            writer.write_bits(v, n)
        for v, n in values:
            writer.write_bits(v, n)
        data = writer.pad_and_get_bytes()

        reader = huffman.BitReader(data)
        for v, n in bits:
            got = 0
            for _ in range(n):
                got = (got << 1) | reader.read_bit()
            self.assertEqual(got, v)
        for v, n in values:
            got = 0
            for _ in range(n):
                got = (got << 1) | reader.read_bit()
            self.assertEqual(got, v)

    def test_byte_stuffing_roundtrips_0xff(self):
        writer = huffman.BitWriter()
        writer.write_bits(0xFF, 8)
        writer.write_bits(0xFF, 8)
        writer.write_bits(0x00, 8)
        data = writer.pad_and_get_bytes()
        # 0xFF bytes must each be followed by a stuffed 0x00 in the raw bytes
        self.assertEqual(data[0], 0xFF)
        self.assertEqual(data[1], 0x00)
        self.assertEqual(data[2], 0xFF)
        self.assertEqual(data[3], 0x00)

        reader = huffman.BitReader(data)
        for expected in (0xFF, 0xFF, 0x00):
            got = 0
            for _ in range(8):
                got = (got << 1) | reader.read_bit()
            self.assertEqual(got, expected)


class TestOptimalTable(unittest.TestCase):
    def test_matches_shannon_bound_ordering(self):
        # A very skewed distribution should give the most frequent symbol
        # the shortest code.
        freqs = {0: 1000, 1: 10, 2: 5, 3: 1}
        bits, huffval = huffman.build_optimal_table(freqs)
        t = huffman.HuffTable(bits, huffval)
        len_of = {sym: t.encode_map[sym][1] for sym in freqs}
        self.assertLessEqual(len_of[0], len_of[1])
        self.assertLessEqual(len_of[1], len_of[3])

    def test_single_symbol_alphabet(self):
        result = huffman.build_optimal_table({7: 100})
        self.assertIsNotNone(result)
        bits, huffval = result
        t = huffman.HuffTable(bits, huffval)
        self.assertEqual(t.encode_map[7][1], 1)

    def test_pathological_distribution_falls_back(self):
        fib = [1, 1]
        for _ in range(30):
            fib.append(fib[-1] + fib[-2])
        freqs = {i: fib[i] for i in range(25)}
        result = huffman.build_optimal_table(freqs, max_length=16)
        self.assertIsNone(result)

    def test_empty_freqs_returns_none(self):
        self.assertIsNone(huffman.build_optimal_table({}))


if __name__ == "__main__":
    unittest.main()
