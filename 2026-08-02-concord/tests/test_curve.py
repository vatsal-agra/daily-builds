import unittest

from concord import curve


class TestCurveArithmetic(unittest.TestCase):
    def test_generator_is_on_curve(self):
        self.assertTrue(curve.is_on_curve(curve.G))

    def test_generator_order(self):
        self.assertIs(curve.scalar_mult(curve.N, curve.G), curve.INFINITY)

    def test_point_add_infinity_identity(self):
        p = curve.scalar_mult(12345, curve.G)
        self.assertEqual(curve.point_add(p, curve.INFINITY), p)
        self.assertEqual(curve.point_add(curve.INFINITY, p), p)

    def test_point_doubling_matches_addition(self):
        p = curve.scalar_mult(777, curve.G)
        self.assertEqual(curve.point_add(p, p), curve.scalar_mult(2, p))

    def test_scalar_mult_distributes(self):
        a, b = 111, 222
        pa = curve.scalar_mult(a, curve.G)
        pb = curve.scalar_mult(b, curve.G)
        self.assertEqual(curve.point_add(pa, pb), curve.scalar_mult(a + b, curve.G))

    def test_point_negation_cancels(self):
        p = curve.scalar_mult(999, curve.G)
        neg = (p[0], curve.P - p[1])
        self.assertTrue(curve.is_on_curve(neg))
        self.assertIs(curve.point_add(p, neg), curve.INFINITY)


class TestKeysAndEncoding(unittest.TestCase):
    def test_keygen_roundtrip(self):
        d = curve.generate_private_key()
        self.assertTrue(1 <= d < curve.N)
        q = curve.private_to_public(d)
        self.assertTrue(curve.is_on_curve(q))

    def test_compress_decompress_roundtrip_both_parities(self):
        for d in (1, 2, 3, 4, 5, 999983):
            q = curve.private_to_public(d)
            comp = curve.compress_pubkey(q)
            self.assertIn(comp[0], (2, 3))
            self.assertEqual(curve.decompress_pubkey(comp), q)

    def test_decompress_rejects_bad_length(self):
        with self.assertRaises(ValueError):
            curve.decompress_pubkey(b"\x02" * 10)

    def test_decompress_rejects_bad_prefix(self):
        good = curve.compress_pubkey(curve.private_to_public(42))
        tampered = bytes([0x04]) + good[1:]
        with self.assertRaises(ValueError):
            curve.decompress_pubkey(tampered)

    def test_decompress_rejects_x_greater_than_field_prime(self):
        bogus = bytes([0x02]) + (curve.P + 5).to_bytes(32, "big")
        with self.assertRaises(ValueError):
            curve.decompress_pubkey(bogus)

    def test_decompress_rejects_non_curve_point(self):
        # a random 32-byte value is astronomically unlikely to be a valid x
        bogus_x = (12345678901234567890123456789012345678901234567890 % curve.P)
        # find one that's actually off-curve by checking the residue isn't a QR
        while pow((bogus_x**3 + curve.B) % curve.P, (curve.P - 1) // 2, curve.P) == 1:
            bogus_x += 1
        bogus = bytes([0x02]) + bogus_x.to_bytes(32, "big")
        with self.assertRaises(ValueError):
            curve.decompress_pubkey(bogus)

    def test_address_roundtrip_and_validity(self):
        q = curve.private_to_public(curve.generate_private_key())
        addr = curve.pubkey_to_address(q)
        self.assertTrue(curve.is_valid_address(addr))

    def test_address_rejects_tampering(self):
        q = curve.private_to_public(curve.generate_private_key())
        addr = curve.pubkey_to_address(q)
        tampered = addr[:-1] + ("1" if addr[-1] != "1" else "2")
        self.assertFalse(curve.is_valid_address(tampered))

    def test_address_rejects_garbage(self):
        self.assertFalse(curve.is_valid_address(""))
        self.assertFalse(curve.is_valid_address("not-base58!!"))
        self.assertFalse(curve.is_valid_address("1"))

    def test_base58_roundtrip_including_leading_zero_bytes(self):
        for data in (b"\x00\x00hello", b"\xff\xee\xdd", b"", b"\x00"):
            encoded = curve.base58_encode(data)
            decoded = curve.base58_decode(encoded)
            self.assertEqual(decoded, data)


class TestECDSA(unittest.TestCase):
    def setUp(self):
        self.d = curve.generate_private_key()
        self.q = curve.private_to_public(self.d)

    def test_sign_verify_roundtrip(self):
        msg = b"pay bob 10 coins"
        sig = curve.sign(self.d, msg)
        self.assertTrue(curve.verify(self.q, msg, sig))

    def test_verify_rejects_tampered_message(self):
        msg = b"pay bob 10 coins"
        sig = curve.sign(self.d, msg)
        self.assertFalse(curve.verify(self.q, b"pay bob 99999 coins", sig))

    def test_verify_rejects_wrong_key(self):
        msg = b"pay bob 10 coins"
        sig = curve.sign(self.d, msg)
        other_q = curve.private_to_public(curve.generate_private_key())
        self.assertFalse(curve.verify(other_q, msg, sig))

    def test_sign_always_produces_low_s(self):
        msg = b"canonical form check"
        for _ in range(10):
            r, s = curve.sign(self.d, msg)
            self.assertLessEqual(s, curve.N // 2)

    def test_verify_rejects_malleated_high_s_signature(self):
        msg = b"malleability probe"
        r, s = curve.sign(self.d, msg)
        self.assertTrue(curve.verify(self.q, msg, (r, s)))
        flipped = (r, curve.N - s)
        # the flipped signature is mathematically valid ECDSA (this is
        # exactly what makes malleability possible) but must be rejected
        # as non-canonical
        self.assertFalse(curve.verify(self.q, msg, flipped))

    def test_verify_rejects_out_of_range_r_and_s(self):
        msg = b"range check"
        self.assertFalse(curve.verify(self.q, msg, (0, 5)))
        self.assertFalse(curve.verify(self.q, msg, (5, 0)))
        self.assertFalse(curve.verify(self.q, msg, (curve.N, 5)))
        self.assertFalse(curve.verify(self.q, msg, (5, curve.N)))

    def test_sig_bytes_roundtrip(self):
        sig = curve.sign(self.d, b"round trip")
        raw = curve.sig_to_bytes(sig)
        self.assertEqual(len(raw), 64)
        self.assertEqual(curve.sig_from_bytes(raw), sig)


if __name__ == "__main__":
    unittest.main()
