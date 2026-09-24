import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import dct


class TestDCT(unittest.TestCase):
    def test_fast_matches_naive_random_blocks(self):
        rng = random.Random(1)
        for _ in range(20):
            block = [rng.uniform(-128, 127) for _ in range(64)]
            fast = dct.dct_2d(block)
            naive = dct.dct_2d_naive(block)
            for a, b in zip(fast, naive):
                self.assertAlmostEqual(a, b, places=8)

    def test_round_trip_identity(self):
        rng = random.Random(2)
        for _ in range(20):
            block = [rng.uniform(-128, 127) for _ in range(64)]
            coeffs = dct.dct_2d(block)
            recon = dct.idct_2d(coeffs)
            for a, b in zip(block, recon):
                self.assertAlmostEqual(a, b, places=8)

    def test_constant_block_has_only_dc(self):
        # A perfectly flat block should transform to a pure DC coefficient
        # (index 0) with every AC coefficient exactly zero -- this is the
        # textbook sanity check for a DCT: constant signal = zero frequency.
        block = [42.0] * 64
        coeffs = dct.dct_2d(block)
        for i in range(1, 64):
            self.assertAlmostEqual(coeffs[i], 0.0, places=8)
        self.assertNotAlmostEqual(coeffs[0], 0.0)

    def test_dc_coefficient_matches_independent_oracle(self):
        # The DC term is proportional to the block's mean. Rather than
        # re-derive and hand-type the exact scaling constant here (the
        # transcription risk this module's own docstring warns about),
        # cross-check against the independent brute-force oracle instead
        # of a second hand-typed formula.
        block = [10.0] * 64
        coeffs = dct.dct_2d(block)
        from spectral.dct import dct_2d_naive
        self.assertAlmostEqual(coeffs[0], dct_2d_naive(block)[0], places=8)

    def test_energy_conservation_parseval(self):
        # An orthonormal transform preserves total signal energy (Parseval's
        # theorem): sum(f^2) == sum(F^2).
        rng = random.Random(3)
        block = [rng.uniform(-100, 100) for _ in range(64)]
        coeffs = dct.dct_2d(block)
        energy_in = sum(x * x for x in block)
        energy_out = sum(x * x for x in coeffs)
        self.assertAlmostEqual(energy_in, energy_out, places=6)

    def test_basis_matrix_is_orthonormal(self):
        # BASIS . BASIS^T should be the identity matrix.
        from spectral.dct import BASIS, N
        for i in range(N):
            for j in range(N):
                dot = sum(BASIS[i][k] * BASIS[j][k] for k in range(N))
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(dot, expected, places=8)


if __name__ == "__main__":
    unittest.main()
