import unittest

from vignette import tables


class TestTables(unittest.TestCase):
    def test_zigzag_is_a_permutation(self):
        self.assertEqual(sorted(tables.ZIGZAG), list(range(64)))
        self.assertEqual(sorted(tables.INVERSE_ZIGZAG), list(range(64)))

    def test_zigzag_inverse_round_trips(self):
        for i in range(64):
            self.assertEqual(tables.INVERSE_ZIGZAG[tables.ZIGZAG[i]], i)

    def test_zigzag_starts_and_ends_correctly(self):
        # position 0 is the DC term (0,0); position 63 is the highest
        # frequency corner (7,7) = index 63 in an 8x8 row-major layout
        self.assertEqual(tables.ZIGZAG[0], 0)
        self.assertEqual(tables.ZIGZAG[63], 63)

    def test_quality_scaling_clamps_range(self):
        for q in [-100, 0, 1, 50, 99, 100, 500]:
            scaled = tables.scale_quant_table(tables.STD_LUMINANCE_QT, q)
            self.assertEqual(len(scaled), 64)
            for v in scaled:
                self.assertGreaterEqual(v, 1)
                self.assertLessEqual(v, 255)

    def test_quality_100_is_near_lossless_scale(self):
        scaled = tables.scale_quant_table(tables.STD_LUMINANCE_QT, 100)
        self.assertTrue(all(v == 1 for v in scaled))

    def test_lower_quality_means_larger_or_equal_divisors(self):
        q90 = tables.scale_quant_table(tables.STD_LUMINANCE_QT, 90)
        q10 = tables.scale_quant_table(tables.STD_LUMINANCE_QT, 10)
        for a, b in zip(q90, q10):
            self.assertLessEqual(a, b)

    def test_size_category(self):
        self.assertEqual(tables.size_category(0), 0)
        self.assertEqual(tables.size_category(1), 1)
        self.assertEqual(tables.size_category(-1), 1)
        self.assertEqual(tables.size_category(2), 2)
        self.assertEqual(tables.size_category(3), 2)
        self.assertEqual(tables.size_category(-3), 2)
        self.assertEqual(tables.size_category(255), 8)

    def test_magnitude_round_trip(self):
        for v in list(range(-600, 600)):
            size = tables.size_category(v)
            bits = tables.encode_magnitude(v, size)
            self.assertEqual(tables.decode_magnitude(bits, size), v)

    def test_standard_table_sizes(self):
        self.assertEqual(
            sum(tables.STD_DC_LUMINANCE_BITS), len(tables.STD_DC_LUMINANCE_VALUES)
        )
        self.assertEqual(
            sum(tables.STD_AC_LUMINANCE_BITS), len(tables.STD_AC_LUMINANCE_VALUES)
        )
        self.assertEqual(len(tables.STD_AC_LUMINANCE_VALUES), 162)
        self.assertEqual(len(tables.STD_AC_CHROMINANCE_VALUES), 162)


if __name__ == "__main__":
    unittest.main()
