import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import crypto as c


class TestCurveArithmetic(unittest.TestCase):
    def test_generator_order(self):
        self.assertIsNone(c.point_mul(c.N, c.G))
        self.assertTrue(c.is_on_curve(c.G))

    def test_point_add_commutative_and_on_curve(self):
        p1 = c.point_mul(12345, c.G)
        p2 = c.point_mul(6789, c.G)
        self.assertTrue(c.is_on_curve(p1))
        self.assertTrue(c.is_on_curve(p2))
        self.assertEqual(c.point_add(p1, p2), c.point_add(p2, p1))

    def test_scalar_mul_matches_repeated_addition(self):
        p = c.point_mul(7, c.G)
        acc = None
        for _ in range(7):
            acc = c.point_add(acc, c.G)
        self.assertEqual(p, acc)

    def test_point_plus_negation_is_infinity(self):
        p = c.point_mul(999, c.G)
        neg = (p[0], (-p[1]) % c.P)
        self.assertIsNone(c.point_add(p, neg))


class TestKeypairs(unittest.TestCase):
    def test_generate_and_compress_roundtrip(self):
        kp = c.KeyPair.generate()
        self.assertTrue(c.is_on_curve(kp.public_key))
        recovered = c.decompress_pubkey(kp.pubkey_bytes())
        self.assertEqual(recovered, kp.public_key)

    def test_from_private_matches_generate_derivation(self):
        kp = c.KeyPair.generate()
        kp2 = c.KeyPair.from_private(kp.private_key)
        self.assertEqual(kp.public_key, kp2.public_key)


class TestECDSA(unittest.TestCase):
    def setUp(self):
        self.kp = c.KeyPair.generate()
        self.msg = c.hash256(b"hello genesis")

    def test_valid_signature_verifies(self):
        sig = c.sign(self.msg, self.kp.private_key)
        self.assertTrue(c.verify(self.msg, sig, self.kp.public_key))

    def test_tampered_message_fails(self):
        sig = c.sign(self.msg, self.kp.private_key)
        self.assertFalse(c.verify(c.hash256(b"tampered"), sig, self.kp.public_key))

    def test_wrong_key_fails(self):
        sig = c.sign(self.msg, self.kp.private_key)
        other = c.KeyPair.generate()
        self.assertFalse(c.verify(self.msg, sig, other.public_key))

    def test_tampered_signature_fails(self):
        r, s = c.sign(self.msg, self.kp.private_key)
        self.assertFalse(c.verify(self.msg, (r, (s + 1) % c.N), self.kp.public_key))

    def test_low_s_normalization(self):
        for _ in range(10):
            r, s = c.sign(self.msg, self.kp.private_key)
            self.assertLessEqual(s, c.N // 2)

    def test_malformed_signature_components_rejected(self):
        self.assertFalse(c.verify(self.msg, (0, 1), self.kp.public_key))
        self.assertFalse(c.verify(self.msg, (1, 0), self.kp.public_key))
        self.assertFalse(c.verify(self.msg, (c.N, 1), self.kp.public_key))


class TestAddresses(unittest.TestCase):
    def test_base58_roundtrip_various_inputs(self):
        for data in [b"\x00\x00abc", b"\x00", b"hello world", bytes(range(32)), b""]:
            self.assertEqual(c.b58decode(c.b58encode(data)), data)

    def test_address_roundtrip(self):
        kp = c.KeyPair.generate()
        addr = kp.address()
        self.assertTrue(addr[0] == "1")  # version-0 addresses start with '1', like Bitcoin mainnet's
        pkh = c.address_to_pubkey_hash(addr)
        self.assertEqual(pkh, c.hash160(kp.pubkey_bytes()))

    def test_corrupted_address_checksum_rejected(self):
        kp = c.KeyPair.generate()
        addr = kp.address()
        corrupted = addr[:-1] + ("1" if addr[-1] != "1" else "2")
        with self.assertRaises(ValueError):
            c.address_to_pubkey_hash(corrupted)

    def test_ripemd160_fallback_matches_hashlib_when_available(self):
        try:
            r = c.hashlib.new("ripemd160")
        except (ValueError, TypeError):
            self.skipTest("hashlib has no ripemd160 in this environment")
        data = b"test message for ripemd160"
        r.update(data)
        self.assertEqual(c._ripemd160(data), r.digest())


if __name__ == "__main__":
    unittest.main()
