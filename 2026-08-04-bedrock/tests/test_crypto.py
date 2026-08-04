import unittest

from bedrock import crypto


class TestFieldAndCurve(unittest.TestCase):
    def test_generator_is_on_curve(self):
        self.assertTrue(crypto.is_on_curve(crypto.G))

    def test_infinity_is_on_curve(self):
        self.assertTrue(crypto.is_on_curve(None))

    def test_scalar_mult_by_order_is_infinity(self):
        self.assertIsNone(crypto.scalar_mult(crypto.N, crypto.G))

    def test_point_add_identity(self):
        p = crypto.scalar_mult(7, crypto.G)
        self.assertEqual(crypto.point_add(p, None), p)
        self.assertEqual(crypto.point_add(None, p), p)

    def test_point_plus_negation_is_infinity(self):
        p = crypto.scalar_mult(12345, crypto.G)
        self.assertIsNone(crypto.point_add(p, crypto.point_neg(p)))

    def test_scalar_mult_distributes(self):
        p1 = crypto.scalar_mult(6, crypto.G)
        p2 = crypto.point_add(crypto.scalar_mult(2, crypto.G), crypto.scalar_mult(4, crypto.G))
        self.assertEqual(p1, p2)

    def test_derived_points_are_on_curve(self):
        for k in (1, 2, 3, 1000, crypto.N - 1):
            self.assertTrue(crypto.is_on_curve(crypto.scalar_mult(k, crypto.G)))

    def test_inv_mod(self):
        for x in (1, 2, 12345, crypto.P - 1):
            self.assertEqual((x * crypto.inv_mod(x, crypto.P)) % crypto.P, 1)

    def test_inv_mod_zero_raises(self):
        with self.assertRaises(crypto.CurveError):
            crypto.inv_mod(0, crypto.P)


class TestKeysAndCompression(unittest.TestCase):
    def test_keypair_roundtrip(self):
        priv = crypto.generate_private_key()
        pub = crypto.derive_public_key(priv)
        self.assertTrue(crypto.is_on_curve(pub))

    def test_compress_decompress_roundtrip(self):
        for _ in range(10):
            priv = crypto.generate_private_key()
            pub = crypto.derive_public_key(priv)
            comp = crypto.compress_pubkey(pub)
            self.assertEqual(len(comp), 33)
            self.assertIn(comp[0], (2, 3))
            self.assertEqual(crypto.decompress_pubkey(comp), pub)

    def test_decompress_rejects_bad_length(self):
        with self.assertRaises(crypto.CurveError):
            crypto.decompress_pubkey(b"\x02" * 10)

    def test_decompress_rejects_bad_prefix(self):
        pub = crypto.derive_public_key(crypto.generate_private_key())
        comp = bytearray(crypto.compress_pubkey(pub))
        comp[0] = 4
        with self.assertRaises(crypto.CurveError):
            crypto.decompress_pubkey(bytes(comp))

    def test_private_key_out_of_range_rejected(self):
        with self.assertRaises(crypto.CurveError):
            crypto.derive_public_key(0)
        with self.assertRaises(crypto.CurveError):
            crypto.derive_public_key(crypto.N)


class TestECDSA(unittest.TestCase):
    def setUp(self):
        self.priv = crypto.generate_private_key()
        self.pub = crypto.derive_public_key(self.priv)

    def test_sign_verify_roundtrip(self):
        for msg in (b"", b"hello", b"x" * 1000, bytes(range(256))):
            sig = crypto.sign(self.priv, msg)
            self.assertTrue(crypto.verify(self.pub, msg, sig))

    def test_wrong_message_rejected(self):
        sig = crypto.sign(self.priv, b"message A")
        self.assertFalse(crypto.verify(self.pub, b"message B", sig))

    def test_wrong_key_rejected(self):
        other_pub = crypto.derive_public_key(crypto.generate_private_key())
        sig = crypto.sign(self.priv, b"hello")
        self.assertFalse(crypto.verify(other_pub, b"hello", sig))

    def test_bit_flipped_signature_rejected(self):
        r, s = crypto.sign(self.priv, b"hello")
        self.assertFalse(crypto.verify(self.pub, b"hello", (r ^ 1, s)))
        self.assertFalse(crypto.verify(self.pub, b"hello", (r, s ^ 1)))

    def test_out_of_range_signature_rejected(self):
        self.assertFalse(crypto.verify(self.pub, b"hello", (0, 1)))
        self.assertFalse(crypto.verify(self.pub, b"hello", (1, 0)))
        self.assertFalse(crypto.verify(self.pub, b"hello", (crypto.N, 1)))

    def test_none_pubkey_rejected(self):
        sig = crypto.sign(self.priv, b"hello")
        self.assertFalse(crypto.verify(None, b"hello", sig))

    def test_signatures_are_canonical_low_s(self):
        for _ in range(10):
            _, s = crypto.sign(self.priv, b"canonical check")
            self.assertLessEqual(s, crypto.N // 2)

    def test_malleable_high_s_signature_rejected(self):
        # Regression: verify() used to accept both (r, s) and (r, N - s) for
        # the same message, a classic transaction-malleability bug (see
        # REVIEW.md #3).
        r, s = crypto.sign(self.priv, b"malleability check")
        malleable = (r, crypto.N - s)
        self.assertNotEqual(malleable[1], s)
        self.assertFalse(crypto.verify(self.pub, b"malleability check", malleable))

    def test_encode_decode_signature_roundtrip(self):
        sig = crypto.sign(self.priv, b"hello")
        encoded = crypto.encode_signature(sig)
        self.assertEqual(len(encoded), 64)
        self.assertEqual(crypto.decode_signature(encoded), sig)

    def test_decode_signature_rejects_bad_length(self):
        with self.assertRaises(crypto.CurveError):
            crypto.decode_signature(b"\x00" * 63)


class TestBase58(unittest.TestCase):
    def test_roundtrip(self):
        for data in (b"", b"\x00", b"\x00\x00abc", b"hello world", bytes(range(64))):
            self.assertEqual(crypto.base58_decode(crypto.base58_encode(data)), data)

    def test_leading_zero_bytes_become_leading_ones(self):
        encoded = crypto.base58_encode(b"\x00\x00\x01")
        self.assertTrue(encoded.startswith("11"))

    def test_invalid_character_rejected(self):
        with self.assertRaises(ValueError):
            crypto.base58_decode("0OIl")  # all four excluded from the alphabet


class TestAddresses(unittest.TestCase):
    def test_address_roundtrip_validity(self):
        for _ in range(20):
            priv = crypto.generate_private_key()
            pub = crypto.derive_public_key(priv)
            addr = crypto.pubkey_to_address(pub)
            self.assertTrue(crypto.is_valid_address(addr))

    def test_different_keys_different_addresses(self):
        addrs = {crypto.pubkey_to_address(crypto.derive_public_key(crypto.generate_private_key())) for _ in range(20)}
        self.assertEqual(len(addrs), 20)

    def test_tampered_address_rejected(self):
        addr = crypto.pubkey_to_address(crypto.derive_public_key(crypto.generate_private_key()))
        tampered = addr[:-1] + ("1" if addr[-1] != "1" else "2")
        self.assertFalse(crypto.is_valid_address(tampered))

    def test_garbage_rejected(self):
        self.assertFalse(crypto.is_valid_address(""))
        self.assertFalse(crypto.is_valid_address("not an address"))
        self.assertFalse(crypto.is_valid_address("0OIl"))


if __name__ == "__main__":
    unittest.main()
