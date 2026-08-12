import os
import secrets
import unittest

from nonce.crypto import secp256k1 as ec
from nonce.crypto.sha256 import sha256


class TestCurveMath(unittest.TestCase):
    def test_generator_on_curve(self):
        self.assertTrue(ec.is_on_curve(ec.G))

    def test_generator_order(self):
        self.assertIsNone(ec.scalar_mult(ec.N, ec.G))  # N*G == point at infinity

    def test_doubling_matches_addition(self):
        g2a = ec.scalar_mult(2, ec.G)
        g2b = ec.point_add(ec.G, ec.G)
        self.assertEqual(g2a, g2b)

    def test_small_multiples_consistent(self):
        g3 = ec.scalar_mult(3, ec.G)
        self.assertEqual(ec.point_add(ec.scalar_mult(2, ec.G), ec.G), g3)

    def test_infinity_is_identity(self):
        self.assertEqual(ec.point_add(ec.G, ec.INFINITY), ec.G)
        self.assertEqual(ec.point_add(ec.INFINITY, ec.G), ec.G)

    def test_point_plus_its_negation_is_infinity(self):
        x, y = ec.G
        neg_g = (x, ec.P - y)
        self.assertTrue(ec.is_on_curve(neg_g))
        self.assertIsNone(ec.point_add(ec.G, neg_g))


class TestPubkeyEncoding(unittest.TestCase):
    def test_compressed_round_trip(self):
        for _ in range(20):
            priv = secrets.randbelow(ec.N - 1) + 1
            pub = ec.privkey_to_pubkey(priv)
            data = ec.pubkey_to_bytes(pub, compressed=True)
            self.assertEqual(len(data), 33)
            self.assertEqual(ec.bytes_to_pubkey(data), pub)

    def test_uncompressed_round_trip(self):
        priv = secrets.randbelow(ec.N - 1) + 1
        pub = ec.privkey_to_pubkey(priv)
        data = ec.pubkey_to_bytes(pub, compressed=False)
        self.assertEqual(len(data), 65)
        self.assertEqual(ec.bytes_to_pubkey(data), pub)

    def test_invalid_point_rejected(self):
        garbage = b"\x02" + (b"\xff" * 32)
        with self.assertRaises(ValueError):
            ec.bytes_to_pubkey(garbage)


class TestECDSA(unittest.TestCase):
    def test_sign_verify_round_trip_and_determinism(self):
        for _ in range(50):
            priv = secrets.randbelow(ec.N - 1) + 1
            pub = ec.privkey_to_pubkey(priv)
            h = sha256(os.urandom(64))
            sig1 = ec.sign(priv, h)
            sig2 = ec.sign(priv, h)
            self.assertEqual(sig1, sig2, "RFC6979 deterministic k must reproduce the same signature")
            self.assertTrue(ec.verify(pub, h, sig1))

    def test_low_s_normalization(self):
        for _ in range(20):
            priv = secrets.randbelow(ec.N - 1) + 1
            h = sha256(os.urandom(32))
            r, s = ec.sign(priv, h)
            self.assertLessEqual(s, ec.N // 2)

    def test_high_s_signature_rejected(self):
        priv = secrets.randbelow(ec.N - 1) + 1
        pub = ec.privkey_to_pubkey(priv)
        h = sha256(os.urandom(32))
        r, s = ec.sign(priv, h)
        high_s = ec.N - s
        self.assertGreater(high_s, ec.N // 2)
        self.assertTrue(ec.verify(pub, h, (r, s)))
        self.assertFalse(ec.verify(pub, h, (r, high_s)), "non-canonical high-S signature must be rejected")

    def test_tampered_message_rejected(self):
        priv = secrets.randbelow(ec.N - 1) + 1
        pub = ec.privkey_to_pubkey(priv)
        sig = ec.sign(priv, sha256(b"pay alice 10"))
        self.assertFalse(ec.verify(pub, sha256(b"pay alice 11"), sig))

    def test_wrong_pubkey_rejected(self):
        priv_a = secrets.randbelow(ec.N - 1) + 1
        priv_b = secrets.randbelow(ec.N - 1) + 1
        pub_b = ec.privkey_to_pubkey(priv_b)
        h = sha256(b"message")
        sig = ec.sign(priv_a, h)
        self.assertFalse(ec.verify(pub_b, h, sig))

    def test_flipped_signature_bit_rejected(self):
        priv = secrets.randbelow(ec.N - 1) + 1
        pub = ec.privkey_to_pubkey(priv)
        h = sha256(b"message")
        r, s = ec.sign(priv, h)
        self.assertFalse(ec.verify(pub, h, (r ^ 1, s)))

    def test_out_of_range_rs_rejected(self):
        pub = ec.privkey_to_pubkey(1)
        h = sha256(b"x")
        self.assertFalse(ec.verify(pub, h, (0, 1)))
        self.assertFalse(ec.verify(pub, h, (1, 0)))
        self.assertFalse(ec.verify(pub, h, (ec.N, 1)))


if __name__ == "__main__":
    unittest.main()
