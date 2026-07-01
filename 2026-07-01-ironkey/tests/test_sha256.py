from . import _path  # noqa: F401
import hashlib
import unittest

import sha256


class TestSHA256(unittest.TestCase):
    def test_matches_hashlib_boundary_lengths(self):
        lengths = [0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 1000, 100_000]
        for n in lengths:
            msg = bytes((i * 37 + 1) % 256 for i in range(n))
            with self.subTest(n=n):
                self.assertEqual(sha256.sha256(msg), hashlib.sha256(msg).digest())

    def test_matches_hashlib_known_strings(self):
        for s in [b"", b"abc", b"The quick brown fox jumps over the lazy dog"]:
            self.assertEqual(sha256.sha256_hex(s), hashlib.sha256(s).hexdigest())

    def test_one_million_a(self):
        msg = b"a" * 1_000_000
        self.assertEqual(sha256.sha256(msg), hashlib.sha256(msg).digest())

    def test_rejects_str_input(self):
        with self.assertRaises(TypeError):
            sha256.sha256("not bytes")

    def test_incremental_class_matches_one_shot(self):
        h = sha256.SHA256()
        h.update(b"hello ")
        h.update(b"world")
        self.assertEqual(h.digest(), sha256.sha256(b"hello world"))
        self.assertEqual(h.hexdigest(), hashlib.sha256(b"hello world").hexdigest())

    def test_trace_compress_first_block_final_state_matches_full_hash_for_single_block_msg(self):
        msg = b"short message fits in one block"
        trace = sha256.trace_compress_first_block(msg)
        self.assertTrue(trace["is_only_block"])
        final_words = trace["final_words"]
        digest = b"".join(w.to_bytes(4, "big") for w in final_words)
        self.assertEqual(digest, hashlib.sha256(msg).digest())

    def test_trace_multi_block_flag(self):
        msg = b"x" * 1000  # spans multiple 64-byte blocks after padding
        trace = sha256.trace_compress_first_block(msg)
        self.assertFalse(trace["is_only_block"])
        self.assertGreater(trace["total_blocks"], 1)


if __name__ == "__main__":
    unittest.main()
