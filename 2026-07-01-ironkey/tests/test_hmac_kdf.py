from . import _path  # noqa: F401
import hashlib
import hmac
import unittest

import hmac_kdf


class TestHMAC(unittest.TestCase):
    def test_rfc4231_case1(self):
        key = b"\x0b" * 20
        msg = b"Hi There"
        self.assertEqual(hmac_kdf.hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())

    def test_rfc4231_case2_short_key(self):
        key, msg = b"Jefe", b"what do ya want for nothing?"
        self.assertEqual(hmac_kdf.hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())

    def test_key_longer_than_block_size_gets_hashed(self):
        key = b"\xaa" * 100
        msg = b"Test Using Larger Than Block-Size Key - Hash Key First"
        self.assertEqual(hmac_kdf.hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())

    def test_key_exactly_block_size(self):
        key = b"k" * 64
        msg = b"exact block size key"
        self.assertEqual(hmac_kdf.hmac_sha256(key, msg), hmac.new(key, msg, hashlib.sha256).digest())

    def test_empty_message(self):
        key = b"key"
        self.assertEqual(hmac_kdf.hmac_sha256(key, b""), hmac.new(key, b"", hashlib.sha256).digest())


class TestCachedHMACMatchesReference(unittest.TestCase):
    def test_cached_matches_uncached_for_varied_messages(self):
        prf = hmac_kdf._CachedKeyHMAC(b"some-password-123")
        for msg in [b"", b"x", b"a" * 31, b"a" * 32, b"a" * 33, b"a" * 200]:
            self.assertEqual(prf.compute(msg), hmac_kdf.hmac_sha256(b"some-password-123", msg))

    def test_cached_matches_for_long_key(self):
        long_key = b"k" * 200
        prf = hmac_kdf._CachedKeyHMAC(long_key)
        self.assertEqual(prf.compute(b"msg"), hmac_kdf.hmac_sha256(long_key, b"msg"))


class TestPBKDF2(unittest.TestCase):
    def test_matches_hashlib_various_params(self):
        cases = [
            (b"password", b"salt", 1, 32),
            (b"password", b"salt", 4096, 40),
            (b"", b"salt", 10, 32),
            (b"password", b"", 10, 16),
            (b"p" * 100, b"s" * 20, 50, 64),
        ]
        for password, salt, iterations, dklen in cases:
            with self.subTest(password=password, salt=salt, iterations=iterations, dklen=dklen):
                mine = hmac_kdf.pbkdf2_hmac_sha256(password, salt, iterations, dklen)
                ref = hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen)
                self.assertEqual(mine, ref)

    def test_dklen_longer_than_one_digest_needs_multiple_blocks(self):
        dk = hmac_kdf.pbkdf2_hmac_sha256(b"pw", b"salt", 10, 100)
        ref = hashlib.pbkdf2_hmac("sha256", b"pw", b"salt", 10, 100)
        self.assertEqual(dk, ref)
        self.assertEqual(len(dk), 100)

    def test_rejects_invalid_params(self):
        with self.assertRaises(ValueError):
            hmac_kdf.pbkdf2_hmac_sha256(b"pw", b"salt", 0, 32)
        with self.assertRaises(ValueError):
            hmac_kdf.pbkdf2_hmac_sha256(b"pw", b"salt", 10, 0)


if __name__ == "__main__":
    unittest.main()
