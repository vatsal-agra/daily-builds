import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.crypto.hashes import sha256, ripemd160, double_sha256, hash160, hmac_sha256


class TestSha256(unittest.TestCase):
    VECTORS = [b"", b"abc", b"The quick brown fox jumps over the lazy dog", bytes(range(256)) * 5]

    def test_matches_hashlib(self):
        for v in self.VECTORS:
            self.assertEqual(sha256(v), hashlib.sha256(v).digest())

    def test_long_input(self):
        data = b"a" * 1_000_000
        self.assertEqual(sha256(data), hashlib.sha256(data).digest())

    def test_boundary_lengths(self):
        # exercise the padding boundary around 55/56/64/119/120 bytes
        for n in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 121, 128]:
            data = os.urandom(n)
            self.assertEqual(sha256(data), hashlib.sha256(data).digest(), f"len={n}")


class TestRipemd160(unittest.TestCase):
    def test_matches_hashlib(self):
        for v in TestSha256.VECTORS:
            self.assertEqual(ripemd160(v), hashlib.new("ripemd160", v).digest())

    def test_boundary_lengths(self):
        for n in [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 121]:
            data = os.urandom(n)
            self.assertEqual(ripemd160(data), hashlib.new("ripemd160", data).digest(), f"len={n}")

    def test_known_vector_abc(self):
        # RIPEMD-160("abc") from the reference test vectors
        self.assertEqual(ripemd160(b"abc").hex(), "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc")


class TestCompositeHashes(unittest.TestCase):
    def test_double_sha256(self):
        data = b"vein"
        self.assertEqual(double_sha256(data), hashlib.sha256(hashlib.sha256(data).digest()).digest())

    def test_hash160(self):
        data = b"vein"
        expected = hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()
        self.assertEqual(hash160(data), expected)


class TestHmacSha256(unittest.TestCase):
    def test_matches_stdlib_hmac(self):
        import hmac
        for key_len in [0, 10, 64, 100, 200]:
            key = os.urandom(key_len)
            msg = os.urandom(50)
            self.assertEqual(hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())


if __name__ == "__main__":
    unittest.main()
