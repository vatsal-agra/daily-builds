import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meridian import hashing


class TestRingSize(unittest.TestCase):
    def test_ring_size_is_power_of_two(self):
        self.assertEqual(hashing.ring_size(8), 256)
        self.assertEqual(hashing.ring_size(32), 2 ** 32)


class TestHashing(unittest.TestCase):
    def test_sha1_id_matches_real_sha1_truncated(self):
        data = b"hello world"
        expected = int.from_bytes(hashlib.sha1(data).digest(), "big") % (1 << 16)
        self.assertEqual(hashing.sha1_id(data, m_bits=16), expected)

    def test_key_id_and_node_id_are_deterministic(self):
        self.assertEqual(hashing.key_id("alice", 32), hashing.key_id("alice", 32))
        self.assertEqual(
            hashing.node_id_for_addr("127.0.0.1", 9000, 32),
            hashing.node_id_for_addr("127.0.0.1", 9000, 32),
        )

    def test_key_id_bounded_by_ring_size(self):
        for m in (4, 8, 16, 32):
            for key in ("a", "bb", "a much longer key with spaces!!"):
                self.assertLess(hashing.key_id(key, m), hashing.ring_size(m))

    def test_smaller_m_bits_reduction_is_consistent_with_larger(self):
        # (x mod 2^32) mod 2^m == x mod 2^m for any m <= 32 -- the property
        # that made the m_bits threading bug (see REVIEW.md #3) numerically
        # invisible on the default ring size. Pin it down explicitly so a
        # future change can't silently break it without a test noticing.
        key = "some-key"
        wide = hashing.key_id(key, 32)
        for m in (4, 8, 12, 16, 24):
            self.assertEqual(wide % hashing.ring_size(m), hashing.key_id(key, m))


class TestInInterval(unittest.TestCase):
    M = 8  # ring of 256 for readable numbers

    def test_simple_non_wrapping(self):
        self.assertTrue(hashing.in_interval(5, 1, 10, self.M))
        self.assertFalse(hashing.in_interval(1, 1, 10, self.M))  # open on left
        self.assertFalse(hashing.in_interval(10, 1, 10, self.M))  # open on right
        self.assertFalse(hashing.in_interval(20, 1, 10, self.M))

    def test_inclusive_endpoints(self):
        self.assertTrue(hashing.in_interval(1, 1, 10, self.M, incl_a=True))
        self.assertTrue(hashing.in_interval(10, 1, 10, self.M, incl_b=True))
        self.assertFalse(hashing.in_interval(1, 1, 10, self.M, incl_b=True))

    def test_wraparound(self):
        # interval (250, 5) wraps past the 256 boundary
        self.assertTrue(hashing.in_interval(255, 250, 5, self.M))
        self.assertTrue(hashing.in_interval(0, 250, 5, self.M))
        self.assertTrue(hashing.in_interval(3, 250, 5, self.M))
        self.assertFalse(hashing.in_interval(100, 250, 5, self.M))
        self.assertFalse(hashing.in_interval(250, 250, 5, self.M))
        self.assertFalse(hashing.in_interval(5, 250, 5, self.M))

    def test_degenerate_a_equals_b_is_the_whole_ring(self):
        # This is exactly what a single-node ring's own (self, successor)
        # interval looks like when successor == self.
        self.assertTrue(hashing.in_interval(0, 42, 42, self.M))
        self.assertTrue(hashing.in_interval(200, 42, 42, self.M))
        self.assertFalse(hashing.in_interval(42, 42, 42, self.M))
        self.assertTrue(hashing.in_interval(42, 42, 42, self.M, incl_a=True))
        self.assertTrue(hashing.in_interval(42, 42, 42, self.M, incl_b=True))

    def test_values_normalized_modulo_ring_size(self):
        # x, a, b larger than the ring size are reduced mod 2^m before
        # testing -- this is what lets a node's own ring-local m_bits
        # correctly interpret an id that was computed in a wider space.
        size = hashing.ring_size(self.M)
        self.assertEqual(
            hashing.in_interval(5 + size, 1, 10, self.M),
            hashing.in_interval(5, 1, 10, self.M),
        )


class TestFingerStart(unittest.TestCase):
    def test_matches_chord_paper_formula(self):
        m = 3
        # node id 1 on an 8-point ring: starts are (1+1)=2, (1+2)=3, (1+4)=5
        self.assertEqual(hashing.finger_start(1, 0, m), 2)
        self.assertEqual(hashing.finger_start(1, 1, m), 3)
        self.assertEqual(hashing.finger_start(1, 2, m), 5)

    def test_wraps_past_ring_size(self):
        m = 3
        # node id 7 (max on an 8-point ring): (7+4)=11 -> wraps to 3
        self.assertEqual(hashing.finger_start(7, 2, m), 3)


if __name__ == "__main__":
    unittest.main()
