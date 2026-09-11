import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.crypto.curve import G, N, P, INFINITY, Point, is_on_curve, point_add, scalar_mult, derive_pubkey
from vein.crypto.ecdsa import generate_privkey, sign, verify, Signature
from vein.crypto.hashes import sha256


class TestCurve(unittest.TestCase):
    def test_generator_on_curve(self):
        self.assertTrue(is_on_curve(G))

    def test_order_annihilates_generator(self):
        self.assertEqual(scalar_mult(N, G), INFINITY)

    def test_doubling_matches_addition(self):
        two_g = scalar_mult(2, G)
        self.assertEqual(two_g, point_add(G, G))
        self.assertTrue(is_on_curve(two_g))

    def test_additive_homomorphism(self):
        for a, b in [(5, 7), (123, 456), (N - 1, 1), (10**6, 2 * 10**6)]:
            lhs = scalar_mult((a + b) % N, G)
            rhs = point_add(scalar_mult(a % N, G), scalar_mult(b % N, G))
            self.assertEqual(lhs, rhs)

    def test_distinct_scalars_distinct_points(self):
        pts = {scalar_mult(k, G) for k in range(1, 40)}
        self.assertEqual(len(pts), 39)

    def test_infinity_identity(self):
        p = scalar_mult(12345, G)
        self.assertEqual(point_add(p, INFINITY), p)
        self.assertEqual(point_add(INFINITY, p), p)

    def test_point_plus_negation_is_infinity(self):
        p = scalar_mult(999, G)
        neg = Point(p.x, (-p.y) % P)
        self.assertEqual(point_add(p, neg), INFINITY)

    def test_derive_pubkey_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            derive_pubkey(0)
        with self.assertRaises(ValueError):
            derive_pubkey(N)


class TestECDSA(unittest.TestCase):
    def test_sign_verify_roundtrip(self):
        priv = generate_privkey()
        pub = derive_pubkey(priv)
        msg = sha256(b"hello vein")
        sig = sign(priv, msg)
        self.assertTrue(verify(pub, msg, sig))

    def test_deterministic_rfc6979(self):
        priv = generate_privkey()
        msg = sha256(b"deterministic please")
        sig1 = sign(priv, msg)
        sig2 = sign(priv, msg)
        self.assertEqual(sig1, sig2)

    def test_wrong_message_rejected(self):
        priv = generate_privkey()
        pub = derive_pubkey(priv)
        sig = sign(priv, sha256(b"real message"))
        self.assertFalse(verify(pub, sha256(b"tampered message"), sig))

    def test_wrong_key_rejected(self):
        priv1 = generate_privkey()
        priv2 = generate_privkey()
        msg = sha256(b"msg")
        sig = sign(priv1, msg)
        self.assertFalse(verify(derive_pubkey(priv2), msg, sig))

    def test_low_s_normalization(self):
        priv = generate_privkey()
        msg = sha256(b"low-s check")
        sig = sign(priv, msg)
        self.assertLessEqual(sig.s, N // 2)

    def test_der_roundtrip(self):
        priv = generate_privkey()
        sig = sign(priv, sha256(b"der test"))
        der = sig.der_encode()
        self.assertEqual(Signature.der_decode(der), sig)

    def test_many_random_cycles(self):
        for _ in range(25):
            priv = generate_privkey()
            pub = derive_pubkey(priv)
            msg = sha256(os.urandom(64))
            sig = sign(priv, msg)
            self.assertTrue(verify(pub, msg, sig))

    def test_malformed_signature_rejected_not_crashed(self):
        priv = generate_privkey()
        pub = derive_pubkey(priv)
        msg = sha256(b"x")
        self.assertFalse(verify(pub, msg, Signature(0, 0)))
        self.assertFalse(verify(pub, msg, Signature(N, N)))


if __name__ == "__main__":
    unittest.main()
