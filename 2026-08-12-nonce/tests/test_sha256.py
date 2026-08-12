import hashlib
import hmac as hmaclib
import os
import unittest

from nonce.crypto.sha256 import sha256, sha256d, hmac_sha256

# FIPS 180-4 / NIST published SHA-256 test vectors
FIPS_ABC_DIGEST = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
FIPS_EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestSHA256(unittest.TestCase):
    def test_known_vectors_against_hashlib(self):
        for msg in [b"", b"a", b"abc", b"a" * 55, b"a" * 56, b"a" * 57, b"a" * 64,
                    b"a" * 1000, os.urandom(1000)]:
            self.assertEqual(sha256(msg), hashlib.sha256(msg).digest(), msg=f"len={len(msg)}")

    def test_known_vectors_match_published_fips_digests(self):
        self.assertEqual(sha256(b"abc").hex(), FIPS_ABC_DIGEST)
        self.assertEqual(sha256(b"").hex(), FIPS_EMPTY_DIGEST)

    def test_double_sha256(self):
        for msg in [b"", b"hello", os.urandom(64)]:
            self.assertEqual(sha256d(msg), sha256(sha256(msg)))
            self.assertEqual(sha256d(msg), hashlib.sha256(hashlib.sha256(msg).digest()).digest())

    def test_hmac_matches_stdlib(self):
        for _ in range(20):
            key, msg = os.urandom(64), os.urandom(200)
            self.assertEqual(hmac_sha256(key, msg), hmaclib.new(key, msg, hashlib.sha256).digest())

    def test_hmac_short_and_long_keys(self):
        for keylen in [1, 32, 64, 65, 200]:
            key = os.urandom(keylen)
            msg = b"test message"
            self.assertEqual(hmac_sha256(key, msg), hmaclib.new(key, msg, hashlib.sha256).digest())

    def test_avalanche_effect(self):
        # flipping one input bit should change roughly half the output bits
        h1 = sha256(b"test message")
        h2 = sha256(b"test messagf")  # last char flipped by one bit's worth
        diff_bits = bin(int.from_bytes(h1, "big") ^ int.from_bytes(h2, "big")).count("1")
        self.assertGreater(diff_bits, 100)  # far from identical; loose bound, not a strict avalanche test


if __name__ == "__main__":
    unittest.main()
