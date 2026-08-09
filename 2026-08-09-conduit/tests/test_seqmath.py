import unittest

from conduit.seqmath import seq_diff, seq_ge, seq_le, seq_lt


class TestSeqMath(unittest.TestCase):
    def test_simple_diff(self):
        self.assertEqual(seq_diff(10, 5), 5)
        self.assertEqual(seq_diff(5, 10), -5)
        self.assertEqual(seq_diff(5, 5), 0)

    def test_wraparound_forward(self):
        # 5 just wrapped past 0 from 0xFFFFFFFE — should read as +7, not -4294967287
        a = 5
        b = 0xFFFFFFFE
        self.assertEqual(seq_diff(a, b), 7)

    def test_wraparound_backward(self):
        a = 0xFFFFFFFE
        b = 5
        self.assertEqual(seq_diff(a, b), -7)

    def test_comparisons(self):
        self.assertTrue(seq_lt(5, 10))
        self.assertFalse(seq_lt(10, 5))
        self.assertTrue(seq_le(5, 5))
        self.assertTrue(seq_ge(10, 5))
        self.assertTrue(seq_lt(0xFFFFFFFE, 5))  # wrapped: 0xFFFFFFFE is "before" 5
        self.assertTrue(seq_ge(5, 0xFFFFFFFE))


if __name__ == "__main__":
    unittest.main()
