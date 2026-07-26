import random
import unittest

from vignette import dct


class TestDCT(unittest.TestCase):
    def test_fast_matches_bruteforce(self):
        random.seed(1)
        for _ in range(10):
            block = [[random.uniform(-128, 127) for _ in range(8)] for _ in range(8)]
            fast = dct.dct_2d(block)
            brute = dct.dct_2d_bruteforce(block)
            for r in range(8):
                for c in range(8):
                    self.assertAlmostEqual(fast[r][c], brute[r][c], places=8)

    def test_round_trip_identity(self):
        random.seed(2)
        for _ in range(10):
            block = [[random.uniform(-128, 127) for _ in range(8)] for _ in range(8)]
            coeffs = dct.dct_2d(block)
            restored = dct.idct_2d(coeffs)
            for r in range(8):
                for c in range(8):
                    self.assertAlmostEqual(block[r][c], restored[r][c], places=8)

    def test_constant_block_has_only_dc(self):
        block = [[42.0] * 8 for _ in range(8)]
        coeffs = dct.dct_2d(block)
        for r in range(8):
            for c in range(8):
                if (r, c) != (0, 0):
                    self.assertAlmostEqual(coeffs[r][c], 0.0, places=8)
        self.assertNotAlmostEqual(coeffs[0][0], 0.0)

    def test_1d_round_trip(self):
        random.seed(3)
        seq = [random.uniform(-100, 100) for _ in range(8)]
        restored = dct.idct_1d(dct.dct_1d(seq))
        for a, b in zip(seq, restored):
            self.assertAlmostEqual(a, b, places=8)


if __name__ == "__main__":
    unittest.main()
