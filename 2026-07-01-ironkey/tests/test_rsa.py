from . import _path  # noqa: F401
import unittest

import rsa

# 1024 bits keeps the suite fast; one 2048-bit test below covers the
# "real" size end to end.
_FAST_BITS = 1024


class TestKeygen(unittest.TestCase):
    def test_modulus_has_exact_bit_length(self):
        for bits in (256, 512, _FAST_BITS):
            pub, priv = rsa.generate_keypair(bits=bits)
            self.assertEqual(pub.n.bit_length(), bits)
            self.assertEqual(priv.n, pub.n)

    def test_crt_params_are_consistent(self):
        pub, priv = rsa.generate_keypair(bits=_FAST_BITS)
        self.assertEqual(priv.p * priv.q, priv.n)
        self.assertEqual(priv.dp, priv.d % (priv.p - 1))
        self.assertEqual(priv.dq, priv.d % (priv.q - 1))
        self.assertEqual((priv.q * priv.qinv) % priv.p, 1)

    def test_public_key_round_trips_through_key_serialization(self, tmp_path=None):
        import tempfile
        import os

        pub, priv = rsa.generate_keypair(bits=_FAST_BITS)
        with tempfile.TemporaryDirectory() as d:
            pub_path, priv_path = os.path.join(d, "pub.json"), os.path.join(d, "priv.json")
            rsa.save_public_key(pub, pub_path)
            rsa.save_private_key(priv, priv_path)
            pub2 = rsa.load_public_key(pub_path)
            priv2 = rsa.load_private_key(priv_path)
        self.assertEqual((pub2.n, pub2.e), (pub.n, pub.e))
        self.assertEqual(priv2.d, priv.d)
        ct = rsa.oaep_encrypt(pub2, b"round trip through files")
        self.assertEqual(rsa.oaep_decrypt(priv2, ct), b"round trip through files")


class TestOAEP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pub, cls.priv = rsa.generate_keypair(bits=_FAST_BITS)

    def test_round_trip(self):
        msg = b"a real message to encrypt with OAEP"
        ct = rsa.oaep_encrypt(self.pub, msg)
        self.assertEqual(rsa.oaep_decrypt(self.priv, ct), msg)

    def test_empty_message(self):
        ct = rsa.oaep_encrypt(self.pub, b"")
        self.assertEqual(rsa.oaep_decrypt(self.priv, ct), b"")

    def test_max_length_message(self):
        k = self.pub.k
        maxlen = k - 2 * 32 - 2
        msg = (bytes(range(256)) * (maxlen // 256 + 1))[:maxlen]
        ct = rsa.oaep_encrypt(self.pub, msg)
        self.assertEqual(rsa.oaep_decrypt(self.priv, ct), msg)

    def test_over_length_message_rejected(self):
        k = self.pub.k
        maxlen = k - 2 * 32 - 2
        with self.assertRaises(ValueError):
            rsa.oaep_encrypt(self.pub, b"x" * (maxlen + 1))

    def test_randomized_ciphertexts_differ(self):
        msg = b"same message twice"
        ct1 = rsa.oaep_encrypt(self.pub, msg)
        ct2 = rsa.oaep_encrypt(self.pub, msg)
        self.assertNotEqual(ct1, ct2)
        self.assertEqual(rsa.oaep_decrypt(self.priv, ct1), msg)
        self.assertEqual(rsa.oaep_decrypt(self.priv, ct2), msg)

    def test_decryption_errors_are_generic_not_distinguishable(self):
        """Regression test for REVIEW.md finding #2 (Manger-style oracle):
        an out-of-range ciphertext representative and a bad-padding
        ciphertext must raise the exact same error message."""
        k = self.pub.k
        out_of_range_ct = b"\xff" * k
        with self.assertRaises(ValueError) as ctx1:
            rsa.oaep_decrypt(self.priv, out_of_range_ct)
        self.assertEqual(str(ctx1.exception), "decryption error")

        good_ct = rsa.oaep_encrypt(self.pub, b"tamper target")
        tampered = bytearray(good_ct)
        tampered[-1] ^= 1
        with self.assertRaises(ValueError) as ctx2:
            rsa.oaep_decrypt(self.priv, bytes(tampered))
        self.assertEqual(str(ctx2.exception), "decryption error")


class TestPSS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pub, cls.priv = rsa.generate_keypair(bits=_FAST_BITS)
        cls.pub2, cls.priv2 = rsa.generate_keypair(bits=_FAST_BITS)

    def test_sign_verify_round_trip(self):
        msg = b"sign this message"
        sig = rsa.pss_sign(self.priv, msg)
        self.assertTrue(rsa.pss_verify(self.pub, msg, sig))

    def test_rejects_modified_message(self):
        msg = b"sign this message"
        sig = rsa.pss_sign(self.priv, msg)
        self.assertFalse(rsa.pss_verify(self.pub, msg + b"!", sig))

    def test_rejects_tampered_signature(self):
        msg = b"sign this message"
        sig = bytearray(rsa.pss_sign(self.priv, msg))
        sig[10] ^= 1
        self.assertFalse(rsa.pss_verify(self.pub, msg, bytes(sig)))

    def test_rejects_signature_from_different_key(self):
        msg = b"sign this message"
        sig = rsa.pss_sign(self.priv2, msg)
        self.assertFalse(rsa.pss_verify(self.pub, msg, sig))

    def test_signatures_are_randomized(self):
        msg = b"same message"
        sig1 = rsa.pss_sign(self.priv, msg)
        sig2 = rsa.pss_sign(self.priv, msg)
        self.assertNotEqual(sig1, sig2)
        self.assertTrue(rsa.pss_verify(self.pub, msg, sig1))
        self.assertTrue(rsa.pss_verify(self.pub, msg, sig2))

    def test_rejects_wrong_length_signature(self):
        self.assertFalse(rsa.pss_verify(self.pub, b"msg", b"short"))


class TestRealSize2048(unittest.TestCase):
    def test_full_flow_at_2048_bits(self):
        pub, priv = rsa.generate_keypair(bits=2048)
        msg = b"a message at a realistic RSA key size"
        ct = rsa.oaep_encrypt(pub, msg)
        self.assertEqual(rsa.oaep_decrypt(priv, ct), msg)
        sig = rsa.pss_sign(priv, msg)
        self.assertTrue(rsa.pss_verify(pub, msg, sig))


if __name__ == "__main__":
    unittest.main()
