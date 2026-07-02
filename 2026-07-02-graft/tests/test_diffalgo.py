import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import diffalgo


def brute_edit_distance(a, b):
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def apply_opcodes(a, b, ops):
    out = []
    for tag, i1, i2, j1, j2 in ops:
        out.extend(a[i1:i2] if tag == "equal" else b[j1:j2])
    return out


class TestMyersDiff(unittest.TestCase):
    def test_identical_sequences(self):
        self.assertEqual(diffalgo.edit_distance("abc", "abc"), 0)
        ops = diffalgo.opcodes(list("abc"), list("abc"))
        self.assertEqual(ops, [("equal", 0, 3, 0, 3)])

    def test_empty_sequences(self):
        self.assertEqual(diffalgo.edit_distance([], []), 0)
        self.assertEqual(diffalgo.edit_distance([], ["a"]), 1)
        self.assertEqual(diffalgo.edit_distance(["a"], []), 1)

    def test_pure_insertion(self):
        self.assertEqual(diffalgo.edit_distance("ac", "abc"), 1)

    def test_pure_deletion(self):
        self.assertEqual(diffalgo.edit_distance("abc", "ac"), 1)

    def test_total_replacement(self):
        self.assertEqual(diffalgo.edit_distance("aaa", "bbb"), 6)

    def test_fuzz_against_brute_force_dp_oracle(self):
        rng = random.Random(1)
        alphabet = list("ab")
        for _ in range(3000):
            a = [rng.choice(alphabet) for _ in range(rng.randint(0, 8))]
            b = [rng.choice(alphabet) for _ in range(rng.randint(0, 8))]
            self.assertEqual(
                diffalgo.edit_distance(a, b), brute_edit_distance(a, b), (a, b)
            )
            ops = diffalgo.opcodes(a, b)
            self.assertEqual(apply_opcodes(a, b, ops), b, (a, b, ops))

    def test_opcodes_reconstruct_original_a_too(self):
        rng = random.Random(2)
        for _ in range(500):
            a = [rng.choice("xyz") for _ in range(rng.randint(0, 10))]
            b = [rng.choice("xyz") for _ in range(rng.randint(0, 10))]
            ops = diffalgo.opcodes(a, b)
            recon_a = []
            for tag, i1, i2, j1, j2 in ops:
                recon_a.extend(a[i1:i2] if tag in ("equal", "delete", "replace") else [])
            self.assertEqual(recon_a, a)


class TestUnifiedDiff(unittest.TestCase):
    def test_no_diff_when_equal(self):
        lines = ["a", "b", "c"]
        self.assertEqual(diffalgo.unified_diff(lines, lines, "a", "b"), [])

    def test_single_line_change_hunk_header(self):
        a = ["1", "2", "3"]
        b = ["1", "X", "3"]
        out = diffalgo.unified_diff(a, b, "a/f", "b/f")
        self.assertEqual(out[0], "--- a/f")
        self.assertEqual(out[1], "+++ b/f")
        self.assertTrue(any(l.startswith("@@") for l in out))
        self.assertIn("-2", out)
        self.assertIn("+X", out)

    def test_context_trims_long_unchanged_runs(self):
        a = [str(i) for i in range(100)]
        b = list(a)
        b[50] = "CHANGED"
        out = diffalgo.unified_diff(a, b, "a", "b", context=3)
        # far-away unchanged lines should not appear
        self.assertNotIn(" 0", out)
        self.assertNotIn(" 99", out)
        self.assertIn(" 47", out)  # within context window
        self.assertIn(" 53", out)

    def test_pure_append_produces_insert_only_hunk(self):
        a = ["1", "2"]
        b = ["1", "2", "3"]
        out = diffalgo.unified_diff(a, b, "a", "b")
        self.assertIn("+3", out)
        self.assertNotIn("-1", out)
        self.assertNotIn("-2", out)


class TestBinaryDetection(unittest.TestCase):
    def test_nul_byte_is_binary(self):
        self.assertTrue(diffalgo.is_binary(b"hello\x00world"))

    def test_plain_text_is_not_binary(self):
        self.assertFalse(diffalgo.is_binary(b"hello world\n"))


if __name__ == "__main__":
    unittest.main()
