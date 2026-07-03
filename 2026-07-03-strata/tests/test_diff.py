import difflib
import random
import unittest

from strata.diff import diff_tags, get_opcodes, split_lines, unified_diff


def _lcs_len(a, b):
    """Brute-force O(n*m) DP — the true minimum edit distance oracle.
    (difflib.SequenceMatcher is a *heuristic* matcher, not a minimal one,
    so it's not a valid oracle here — see REVIEW.md finding #1.)"""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    return dp[0][0]


class TestMyersDiffOptimality(unittest.TestCase):
    """Every edit script Myers produces must (a) correctly transform a into b
    and (b) have the true minimum possible number of insert/delete ops."""

    def _check(self, a, b):
        tags = diff_tags(a, b)
        ai = bi = 0
        rebuilt = []
        for t in tags:
            if t == "equal":
                self.assertEqual(a[ai], b[bi])
                rebuilt.append(a[ai])
                ai += 1
                bi += 1
            elif t == "delete":
                ai += 1
            else:
                rebuilt.append(b[bi])
                bi += 1
        self.assertEqual(rebuilt, b)
        self.assertEqual(ai, len(a))
        self.assertEqual(bi, len(b))
        n_ops = sum(1 for t in tags if t != "equal")
        expected = len(a) + len(b) - 2 * _lcs_len(a, b)
        self.assertEqual(n_ops, expected, f"a={a!r} b={b!r} tags={tags!r}")

    def test_edge_cases(self):
        self._check([], [])
        self._check([], ["x"])
        self._check(["x"], [])
        self._check(["x"], ["x"])
        self._check(["a", "b", "c"], ["a", "b", "c"])

    def test_random_fuzz_is_minimal(self):
        random.seed(1)
        for alphabet in ["ab", "abc", "abcd"]:
            for _ in range(600):
                a = [random.choice(alphabet) for _ in range(random.randint(0, 10))]
                b = [random.choice(alphabet) for _ in range(random.randint(0, 10))]
                self._check(a, b)


class TestUnifiedDiffMatchesReference(unittest.TestCase):
    """unified_diff() must byte-for-byte match Python's own difflib.unified_diff
    (the standard-library reference implementation of the same format) whenever
    every line is newline-terminated (difflib itself mishandles missing final
    newlines, so that case is tested separately below)."""

    def _check(self, a_text, b_text):
        mine = "".join(unified_diff(split_lines(a_text), split_lines(b_text), "a/x", "b/x"))
        ref = "".join(difflib.unified_diff(split_lines(a_text), split_lines(b_text), "a/x", "b/x"))
        self.assertEqual(mine, ref, f"a={a_text!r} b={b_text!r}")

    def test_basic_cases(self):
        self._check("", "a\nb\nc\n")
        self._check("a\nb\nc\n", "")
        self._check("a\nb\nc\nd\ne\nf\ng\nh\n", "a\nX\nc\nd\ne\nf\nY\nh\n")
        self._check("same\n", "same\n")
        self._check("", "")

    def test_random_fuzz(self):
        random.seed(3)
        for _ in range(400):
            a_lines = [f"{random.choice('abcd')}{i}\n" for i in range(random.randint(0, 15))]
            b_lines = list(a_lines)
            for _ in range(random.randint(0, 4)):
                if not b_lines or random.random() < 0.4:
                    b_lines.insert(random.randint(0, len(b_lines)), f"NEW{random.randint(0,9)}\n")
                else:
                    idx = random.randint(0, len(b_lines) - 1)
                    if random.random() < 0.5:
                        del b_lines[idx]
                    else:
                        b_lines[idx] = f"MOD{random.randint(0,9)}\n"
            self._check("".join(a_lines), "".join(b_lines))

    def test_missing_trailing_newline_produces_marker(self):
        out = "".join(unified_diff(split_lines("a\nb"), split_lines("a\nb\nc"), "a/x", "b/x"))
        self.assertIn("\\ No newline at end of file", out)

    def test_no_diff_for_identical_input(self):
        self.assertEqual(unified_diff(split_lines("same\n"), split_lines("same\n")), [])


class TestGetOpcodes(unittest.TestCase):
    def test_covers_full_range(self):
        a = ["a", "b", "c"]
        b = ["a", "x", "c"]
        opcodes = get_opcodes(a, b)
        self.assertEqual(opcodes[0][1], 0)
        self.assertEqual(opcodes[-1][2], len(a))
        self.assertEqual(opcodes[0][3], 0)
        self.assertEqual(opcodes[-1][4], len(b))


if __name__ == "__main__":
    unittest.main()
