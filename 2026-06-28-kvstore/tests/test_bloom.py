"""Tests for Bloom filter."""

import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kvstore.bloom import BloomFilter


class TestBloomFilter(unittest.TestCase):

    def test_basic_add_and_check(self):
        bf = BloomFilter(100, 0.01)
        bf.add(b"hello")
        bf.add(b"world")
        self.assertTrue(bf.may_contain(b"hello"))
        self.assertTrue(bf.may_contain(b"world"))

    def test_definitely_absent(self):
        bf = BloomFilter(1000, 0.001)
        for i in range(500):
            bf.add(f"key:{i}".encode())
        # Keys not added should mostly not match
        fp = sum(
            1 for i in range(1000, 2000)
            if bf.may_contain(f"key:{i}".encode())
        )
        # FP rate should be very low (<5% with 0.1% configured rate)
        self.assertLess(fp, 50, f"Too many false positives: {fp}/1000")

    def test_no_false_negatives(self):
        bf = BloomFilter(1000, 0.01)
        keys = [f"item:{i}".encode() for i in range(1000)]
        for k in keys:
            bf.add(k)
        for k in keys:
            self.assertTrue(bf.may_contain(k),
                            f"False negative for {k!r}")

    def test_serialize_roundtrip(self):
        bf = BloomFilter(200, 0.01)
        keys = [f"k{i}".encode() for i in range(100)]
        for k in keys:
            bf.add(k)

        serialized = bf.to_bytes()
        bf2 = BloomFilter.from_bytes(serialized)

        for k in keys:
            self.assertTrue(bf2.may_contain(k),
                            f"After roundtrip, false negative for {k!r}")

    def test_empty_filter(self):
        bf = BloomFilter(10, 0.01)
        self.assertFalse(bf.may_contain(b"nothing"))

    def test_single_element(self):
        bf = BloomFilter(1, 0.01)
        bf.add(b"one")
        self.assertTrue(bf.may_contain(b"one"))
        self.assertFalse(bf.may_contain(b"two"))

    def test_fp_rate_roughly_respected(self):
        """Check that configured 1% FP rate is approximately achieved."""
        n = 1000
        fp_rate = 0.01
        bf = BloomFilter(n, fp_rate)
        for i in range(n):
            bf.add(f"present:{i}".encode())
        fps = sum(
            1 for i in range(10000)
            if bf.may_contain(f"absent:{i}".encode())
        )
        # Should be well below 10% even if configured rate is 1%
        self.assertLess(fps / 10000, 0.10)

    def test_bytes_deterministic(self):
        bf = BloomFilter(50, 0.01)
        for i in range(20):
            bf.add(f"key{i}".encode())
        b1 = bf.to_bytes()
        bf2 = BloomFilter(50, 0.01)
        for i in range(20):
            bf2.add(f"key{i}".encode())
        b2 = bf2.to_bytes()
        self.assertEqual(b1, b2)


if __name__ == "__main__":
    unittest.main()
