import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import quant


class TestQuant(unittest.TestCase):
    def test_zigzag_is_a_permutation(self):
        self.assertEqual(sorted(quant.ZIGZAG), list(range(64)))
        self.assertEqual(sorted(quant.INV_ZIGZAG), list(range(64)))

    def test_zigzag_round_trip(self):
        block = list(range(64))
        zz = quant.to_zigzag(block)
        back = quant.from_zigzag(zz)
        self.assertEqual(block, back)

    def test_zigzag_starts_top_left_and_visits_neighbors(self):
        # The zigzag order must start at index 0 (DC) and its first few
        # steps must be adjacent positions in the 8x8 grid (0,0)->(0,1)->
        # (1,0)->(2,0)->(1,1)->(0,2)... i.e. natural-order indices 0,1,8,16,9,2
        self.assertEqual(quant.ZIGZAG[:6], [0, 1, 8, 16, 9, 2])

    def test_quality_50_matches_base_tables_exactly(self):
        self.assertEqual(quant.scale_qtable(quant.STD_LUMA_QTABLE, 50), quant.STD_LUMA_QTABLE)
        self.assertEqual(quant.scale_qtable(quant.STD_CHROMA_QTABLE, 50), quant.STD_CHROMA_QTABLE)

    def test_quality_100_floors_at_one(self):
        table = quant.scale_qtable(quant.STD_LUMA_QTABLE, 100)
        self.assertTrue(all(v == 1 for v in table))

    def test_quality_monotonic_ordering(self):
        # Higher quality must never produce a coarser (larger) quantizer
        # than a lower quality, entry for entry.
        prev = quant.scale_qtable(quant.STD_LUMA_QTABLE, 1)
        for q in range(2, 101):
            cur = quant.scale_qtable(quant.STD_LUMA_QTABLE, q)
            for a, b in zip(cur, prev):
                self.assertLessEqual(a, b)
            prev = cur

    def test_quality_clamped_out_of_range(self):
        self.assertEqual(
            quant.scale_qtable(quant.STD_LUMA_QTABLE, 0),
            quant.scale_qtable(quant.STD_LUMA_QTABLE, 1),
        )
        self.assertEqual(
            quant.scale_qtable(quant.STD_LUMA_QTABLE, 500),
            quant.scale_qtable(quant.STD_LUMA_QTABLE, 100),
        )

    def test_quantize_dequantize_round_trip_is_lossy_but_bounded(self):
        qtable = quant.scale_qtable(quant.STD_LUMA_QTABLE, 90)
        coeffs = [123.4, -50.2, 3.0] + [0.0] * 61
        q = quant.quantize(coeffs, qtable)
        deq = quant.dequantize(q, qtable)
        for orig, back, step in zip(coeffs, deq, qtable):
            self.assertLessEqual(abs(orig - back), step / 2.0 + 1e-6)

    def test_all_zero_block_quantizes_to_all_zero(self):
        qtable = quant.scale_qtable(quant.STD_LUMA_QTABLE, 50)
        q = quant.quantize([0.0] * 64, qtable)
        self.assertEqual(q, [0] * 64)


if __name__ == "__main__":
    unittest.main()
