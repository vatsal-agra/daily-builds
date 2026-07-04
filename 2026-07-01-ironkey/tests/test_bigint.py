from . import _path  # noqa: F401
import unittest

import bigint


class TestModExp(unittest.TestCase):
    def test_matches_python_pow(self):
        cases = [(2, 10, 1000), (7, 128, 13), (123456789, 987654321, 1000000007), (0, 5, 7), (5, 0, 7)]
        for base, exp, mod in cases:
            self.assertEqual(bigint.modexp(base, exp, mod), pow(base, exp, mod))

    def test_mod_one_is_zero(self):
        self.assertEqual(bigint.modexp(123, 456, 1), 0)

    def test_negative_exponent_uses_modinv(self):
        # a^-1 mod m computed via modexp(a, -1, m) should equal modinv(a, m)
        a, m = 7, 41
        self.assertEqual(bigint.modexp(a, -1, m), bigint.modinv(a, m))


class TestEgcdModinv(unittest.TestCase):
    def test_bezout_identity(self):
        for a, b in [(240, 46), (17, 13), (1000000007, 998244353)]:
            g, x, y = bigint.egcd(a, b)
            self.assertEqual(a * x + b * y, g)

    def test_modinv_round_trips(self):
        for a, m in [(3, 11), (7, 41), (65537, 104729)]:
            inv = bigint.modinv(a, m)
            self.assertEqual((a * inv) % m, 1)

    def test_modinv_raises_when_not_coprime(self):
        with self.assertRaises(ValueError):
            bigint.modinv(4, 8)


class TestPrimality(unittest.TestCase):
    KNOWN_PRIMES = [2, 3, 5, 7, 11, 97, 104729, 1299709, 2**61 - 1]
    KNOWN_COMPOSITES = [1, 4, 6, 8, 9, 100, 104730, 561, 1105]  # 561, 1105 are Carmichael numbers

    def test_known_primes(self):
        for p in self.KNOWN_PRIMES:
            self.assertTrue(bigint.is_probable_prime(p), f"{p} should be prime")

    def test_known_composites_including_carmichael(self):
        for c in self.KNOWN_COMPOSITES:
            self.assertFalse(bigint.is_probable_prime(c), f"{c} should be composite")

    def test_gen_prime_has_correct_bit_length_and_is_prime(self):
        for bits in (64, 128, 256):
            p = bigint.gen_prime(bits)
            self.assertEqual(p.bit_length(), bits)
            self.assertTrue(p % 2 == 1)
            self.assertTrue(bigint.is_probable_prime(p))


class TestCRT(unittest.TestCase):
    def test_crt_recovers_known_value(self):
        # x = 41 satisfies x=1 mod 4, x=6 mod 7 (since real RSA CRT combos matter)
        x_expected = 41
        residues = [x_expected % 4, x_expected % 7]
        x = bigint.crt(residues, [4, 7])
        self.assertEqual(x, x_expected % 28)

    def test_crt_against_brute_force(self):
        moduli = [7, 11, 13]
        for x_true in range(0, 7 * 11 * 13, 97):
            residues = [x_true % m for m in moduli]
            self.assertEqual(bigint.crt(residues, moduli), x_true)


class TestRandRangeUniformity(unittest.TestCase):
    """Exact enumeration (not sampling) that the rejection-sampling fix
    from the Phase 3 review actually holds: the accepted region must be
    an exact multiple of the range width for every (span, nbytes)."""

    def test_accept_region_is_exact_multiple_of_range(self):
        import collections

        def enumerate_accept(span, nbytes):
            total_space = 1 << (nbytes * 8)
            span_range = span + 1
            limit = (total_space // span_range) * span_range
            counts = collections.Counter()
            for raw in range(total_space):
                if raw < limit:
                    counts[raw % span_range] += 1
            return counts

        for span in range(1, 25):
            for nbytes in (1, 2):
                if span + 1 > (1 << (nbytes * 8)):
                    continue
                counts = enumerate_accept(span, nbytes)
                self.assertEqual(
                    len(set(counts.values())), 1,
                    f"non-uniform for span={span}, nbytes={nbytes}: {counts}"
                )

    def test_randrange_stays_in_bounds(self):
        for _ in range(2000):
            v = bigint._os_randrange(5, 19)
            self.assertTrue(5 <= v <= 19)


if __name__ == "__main__":
    unittest.main()
