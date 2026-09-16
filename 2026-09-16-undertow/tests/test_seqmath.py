import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from undertow.seqmath import SEQ_MOD, seq_add, seq_diff, seq_ge, seq_gt, seq_le, seq_lt


class TestSeqMath(unittest.TestCase):
    def test_add_wraps(self):
        self.assertEqual(seq_add(SEQ_MOD - 1, 1), 0)
        self.assertEqual(seq_add(SEQ_MOD - 5, 10), 5)
        self.assertEqual(seq_add(0, 0), 0)

    def test_lt_no_wrap(self):
        self.assertTrue(seq_lt(10, 20))
        self.assertFalse(seq_lt(20, 10))
        self.assertFalse(seq_lt(10, 10))

    def test_lt_across_wrap_boundary(self):
        a = SEQ_MOD - 1
        b = 5
        self.assertTrue(seq_lt(a, b))
        self.assertFalse(seq_lt(b, a))

    def test_diff_across_wrap_boundary(self):
        a = SEQ_MOD - 5
        b = 10
        self.assertEqual(seq_diff(a, b), 15)
        self.assertEqual(seq_diff(b, a), -15)

    def test_diff_no_wrap(self):
        self.assertEqual(seq_diff(100, 150), 50)
        self.assertEqual(seq_diff(150, 100), -50)

    def test_le_ge_consistent_with_lt(self):
        for a, b in [(1, 2), (2, 1), (5, 5), (SEQ_MOD - 1, 0)]:
            self.assertEqual(seq_le(a, b), seq_lt(a, b) or a == b)
            self.assertEqual(seq_gt(a, b), seq_lt(b, a))
            self.assertEqual(seq_ge(a, b), seq_le(b, a))

    def test_wraparound_exact_boundary(self):
        # the exact byte where a real connection's sequence number rolls
        # from 2**32-1 back to 0 must still compare correctly
        boundary = SEQ_MOD - 1
        after = seq_add(boundary, 1)
        self.assertEqual(after, 0)
        self.assertTrue(seq_lt(boundary, after))
        self.assertEqual(seq_diff(boundary, after), 1)

    def test_ordering_transitive_within_half_window(self):
        base = 1000
        seqs = [seq_add(base, i) for i in range(0, 1000, 37)]
        for i in range(len(seqs) - 1):
            self.assertTrue(seq_lt(seqs[i], seqs[i + 1]))


if __name__ == "__main__":
    unittest.main()
