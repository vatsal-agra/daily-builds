import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import crypto


class TestECMath(unittest.TestCase):
    def test_generator_on_curve(self):
        self.assertTrue(crypto.is_on_curve(crypto.G))

    def test_scalar_mult_order(self):
        # N * G == point at infinity
        self.assertIsNone(crypto.scalar_mult(crypto.N, crypto.G))

    def test_point_add_identity(self):
        p = crypto.scalar_mult(12345, crypto.G)
        self.assertEqual(crypto.point_add(p, None), p)
        self.assertEqual(crypto.point_add(None, p), p)

    def test_point_add_negation(self):
        p = crypto.scalar_mult(999, crypto.G)
        neg_p = crypto.point_neg(p)
        self.assertIsNone(crypto.point_add(p, neg_p))

    def test_scalar_mult_distributive(self):
        a, b = 12345, 67890
        p1 = crypto.scalar_mult(a + b, crypto.G)
        p2 = crypto.point_add(crypto.scalar_mult(a, crypto.G), crypto.scalar_mult(b, crypto.G))
        self.assertEqual(p1, p2)

    def test_compress_decompress_roundtrip(self):
        for k in (1, 2, 42, 999999, crypto.N - 1):
            pub = crypto.private_to_public(k)
            c = crypto.compress_pubkey(pub)
            self.assertEqual(len(c), 33)
            self.assertEqual(crypto.decompress_pubkey(c), pub)

    def test_decompress_rejects_invalid_point(self):
        # an x-coordinate essentially guaranteed to not be on the curve
        bad = b"\x02" + (0).to_bytes(32, "big")
        with self.assertRaises(ValueError):
            crypto.decompress_pubkey(bad)


class TestECDSA(unittest.TestCase):
    def test_sign_verify_roundtrip(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        digest = crypto.sha256(b"hello keystone")
        sig = crypto.sign(priv, digest)
        self.assertTrue(crypto.verify(pub, digest, sig))

    def test_verify_rejects_tampered_message(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        digest = crypto.sha256(b"original")
        sig = crypto.sign(priv, digest)
        tampered_digest = crypto.sha256(b"tampered")
        self.assertFalse(crypto.verify(pub, tampered_digest, sig))

    def test_verify_rejects_wrong_key(self):
        priv_a = crypto.generate_private_key()
        priv_b = crypto.generate_private_key()
        pub_b = crypto.private_to_public(priv_b)
        digest = crypto.sha256(b"message")
        sig = crypto.sign(priv_a, digest)
        self.assertFalse(crypto.verify(pub_b, digest, sig))

    def test_verify_rejects_flipped_signature(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        digest = crypto.sha256(b"message")
        r, s = crypto.sign(priv, digest)
        self.assertFalse(crypto.verify(pub, digest, (s, r)))

    def test_signature_is_low_s_normalized(self):
        priv = crypto.generate_private_key()
        digest = crypto.sha256(b"low-s check")
        _, s = crypto.sign(priv, digest)
        self.assertLessEqual(s, crypto.N // 2)

    def test_rfc6979_deterministic(self):
        priv = crypto.generate_private_key()
        digest = crypto.sha256(b"deterministic nonce check")
        sig1 = crypto.sign(priv, digest)
        sig2 = crypto.sign(priv, digest)
        self.assertEqual(sig1, sig2)

    def test_verify_rejects_out_of_range_signature(self):
        pub = crypto.private_to_public(crypto.generate_private_key())
        digest = crypto.sha256(b"x")
        self.assertFalse(crypto.verify(pub, digest, (0, 5)))
        self.assertFalse(crypto.verify(pub, digest, (5, 0)))
        self.assertFalse(crypto.verify(pub, digest, (crypto.N, 5)))


class TestRIPEMD160(unittest.TestCase):
    VECTORS = {
        b"": "9c1185a5c5e9fc54612808977ee8f548b2258d31",
        b"a": "0bdc9d2d256b3ee9daae347be6f4dc835a467ffe",
        b"abc": "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc",
        b"message digest": "5d0689ef49d2fae572b881b123a85ffa21595f36",
        b"abcdefghijklmnopqrstuvwxyz": "f71c27109c692c1b56bbdceb5b9d2865b3708dbc",
        b"a" * 1_000_000: "52783243c1697bdbe16d37f97f68f08325dc1528",
    }

    def test_official_vectors(self):
        for msg, expected in self.VECTORS.items():
            with self.subTest(msg=msg[:20]):
                self.assertEqual(crypto.ripemd160(msg).hex(), expected)


class TestBase58Check(unittest.TestCase):
    def test_roundtrip(self):
        for payload in (b"\x00" * 20, b"\xff" * 20, bytes(range(20)), b"\x00\x00hello"):
            encoded = crypto.b58check_encode(payload, version=0)
            version, decoded = crypto.b58check_decode(encoded)
            self.assertEqual(version, 0)
            self.assertEqual(decoded, payload)

    def test_bad_checksum_rejected(self):
        encoded = crypto.b58check_encode(b"\x01" * 20, version=0)
        tampered = encoded[:-1] + ("2" if encoded[-1] != "2" else "3")
        with self.assertRaises(ValueError):
            crypto.b58check_decode(tampered)

    def test_invalid_character_rejected(self):
        with self.assertRaises(ValueError):
            crypto.b58decode("not-valid-0OIl")


if __name__ == "__main__":
    unittest.main()
