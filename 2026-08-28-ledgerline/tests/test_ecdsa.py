import hashlib
import unittest

from ledgerline import ecdsa


class TestCurveArithmetic(unittest.TestCase):
    def test_generator_on_curve(self):
        self.assertTrue(ecdsa.is_on_curve(ecdsa.G))

    def test_n_times_g_is_infinity(self):
        self.assertIsNone(ecdsa.scalar_mult(ecdsa.N, ecdsa.G))

    def test_point_doubling_matches_addition(self):
        double = ecdsa.point_add(ecdsa.G, ecdsa.G)
        via_scalar = ecdsa.scalar_mult(2, ecdsa.G)
        self.assertEqual(double, via_scalar)
        self.assertTrue(ecdsa.is_on_curve(double))

    def test_scalar_mult_random_points_on_curve(self):
        for k in [1, 2, 3, 5, 17, 12345, ecdsa.N - 1]:
            pt = ecdsa.scalar_mult(k, ecdsa.G)
            self.assertTrue(ecdsa.is_on_curve(pt), f"k={k}")

    def test_additive_homomorphism(self):
        # (a+b)*G == a*G + b*G
        a, b = 12345, 67890
        lhs = ecdsa.scalar_mult(a + b, ecdsa.G)
        rhs = ecdsa.point_add(ecdsa.scalar_mult(a, ecdsa.G), ecdsa.scalar_mult(b, ecdsa.G))
        self.assertEqual(lhs, rhs)

    def test_point_add_identity(self):
        pt = ecdsa.scalar_mult(42, ecdsa.G)
        self.assertEqual(ecdsa.point_add(pt, None), pt)
        self.assertEqual(ecdsa.point_add(None, pt), pt)

    def test_point_add_inverse_is_infinity(self):
        pt = ecdsa.scalar_mult(42, ecdsa.G)
        self.assertIsNone(ecdsa.point_add(pt, ecdsa.point_neg(pt)))


class TestKeysAndEncoding(unittest.TestCase):
    def test_compress_decompress_roundtrip(self):
        for _ in range(10):
            priv = ecdsa.generate_private_key()
            pub = ecdsa.private_to_public(priv)
            comp = ecdsa.compress_pubkey(pub)
            self.assertEqual(len(comp), 33)
            self.assertEqual(ecdsa.decompress_pubkey(comp), pub)

    def test_decompress_rejects_bad_length(self):
        with self.assertRaises(ValueError):
            ecdsa.decompress_pubkey(b"\x02" * 10)

    def test_decompress_rejects_bad_prefix(self):
        priv = ecdsa.generate_private_key()
        comp = bytearray(ecdsa.compress_pubkey(ecdsa.private_to_public(priv)))
        comp[0] = 0x04
        with self.assertRaises(ValueError):
            ecdsa.decompress_pubkey(bytes(comp))

    def test_two_random_keys_differ(self):
        a, b = ecdsa.generate_private_key(), ecdsa.generate_private_key()
        self.assertNotEqual(a, b)


class TestSigning(unittest.TestCase):
    def setUp(self):
        self.priv = ecdsa.generate_private_key()
        self.pub = ecdsa.private_to_public(self.priv)
        self.digest = hashlib.sha256(b"hello ledgerline").digest()

    def test_sign_verify(self):
        sig = ecdsa.sign(self.digest, self.priv)
        self.assertTrue(ecdsa.verify(self.digest, sig, self.pub))

    def test_deterministic_signing(self):
        sig1 = ecdsa.sign(self.digest, self.priv)
        sig2 = ecdsa.sign(self.digest, self.priv)
        self.assertEqual(sig1, sig2, "RFC 6979 signing must be deterministic")

    def test_tampered_message_rejected(self):
        sig = ecdsa.sign(self.digest, self.priv)
        tampered = bytes([self.digest[0] ^ 0xFF]) + self.digest[1:]
        self.assertFalse(ecdsa.verify(tampered, sig, self.pub))

    def test_wrong_key_rejected(self):
        other_priv = ecdsa.generate_private_key()
        sig = ecdsa.sign(self.digest, other_priv)
        self.assertFalse(ecdsa.verify(self.digest, sig, self.pub))

    def test_tampered_signature_rejected(self):
        sig = ecdsa.sign(self.digest, self.priv)
        bad = ecdsa.Signature(sig.r, (sig.s + 1) % ecdsa.N)
        self.assertFalse(ecdsa.verify(self.digest, bad, self.pub))

    def test_low_s_normalization(self):
        sig = ecdsa.sign(self.digest, self.priv)
        self.assertLessEqual(sig.s, ecdsa.N // 2)

    def test_der_roundtrip(self):
        sig = ecdsa.sign(self.digest, self.priv)
        der = sig.to_der()
        self.assertEqual(ecdsa.Signature.from_der(der), sig)

    def test_verify_wrong_length_digest_rejected(self):
        sig = ecdsa.sign(self.digest, self.priv)
        self.assertFalse(ecdsa.verify(b"short", sig, self.pub))


if __name__ == "__main__":
    unittest.main()
