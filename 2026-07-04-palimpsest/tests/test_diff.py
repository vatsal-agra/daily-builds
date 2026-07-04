import os
import random
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest.diffalgo import myers_diff, opcodes, unified_diff

PATCH_AVAILABLE = True
try:
    subprocess.run(["patch", "--version"], capture_output=True)
except FileNotFoundError:
    PATCH_AVAILABLE = False


def brute_force_lcs_len(a, b):
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = (
                dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
            )
    return dp[0][0]


def apply_ops(a, b, ops):
    recon_a = [a[op.a_index] for op in ops if op.tag in ("equal", "delete")]
    recon_b = [b[op.b_index] for op in ops if op.tag in ("equal", "insert")]
    return recon_a, recon_b


class TestMyersDiffMinimality(unittest.TestCase):
    def test_identical_sequences_are_all_equal(self):
        a = ["x", "y", "z"]
        ops = myers_diff(a, list(a))
        self.assertTrue(all(op.tag == "equal" for op in ops))
        self.assertEqual(len(ops), 3)

    def test_empty_vs_empty(self):
        self.assertEqual(myers_diff([], []), [])

    def test_empty_vs_nonempty_is_all_inserts(self):
        ops = myers_diff([], ["a", "b"])
        self.assertTrue(all(op.tag == "insert" for op in ops))

    def test_random_sequences_are_minimal_and_reconstruct_both_sides(self):
        random.seed(42)
        for _ in range(1000):
            a = [random.choice("abcde") for _ in range(random.randint(0, 12))]
            b = [random.choice("abcde") for _ in range(random.randint(0, 12))]
            ops = myers_diff(a, b)
            expected_edits = len(a) + len(b) - 2 * brute_force_lcs_len(a, b)
            actual_edits = sum(1 for op in ops if op.tag != "equal")
            self.assertEqual(actual_edits, expected_edits, (a, b))
            recon_a, recon_b = apply_ops(a, b, ops)
            self.assertEqual(recon_a, a)
            self.assertEqual(recon_b, b)


class TestOpcodes(unittest.TestCase):
    def test_replace_merges_adjacent_delete_insert(self):
        codes = opcodes(["a"], ["b"])
        self.assertEqual(codes, [("replace", 0, 1, 0, 1)])

    def test_pure_equal(self):
        codes = opcodes(["a", "b"], ["a", "b"])
        self.assertEqual(codes, [("equal", 0, 2, 0, 2)])


class TestUnifiedDiff(unittest.TestCase):
    def test_no_diff_for_equal_input(self):
        self.assertEqual(unified_diff(["a"], ["a"]), "")

    def test_simple_insertion(self):
        out = unified_diff(["a", "c"], ["a", "b", "c"], "x", "y")
        self.assertIn("+b", out)
        self.assertIn("--- x", out)
        self.assertIn("+++ y", out)

    @unittest.skipUnless(PATCH_AVAILABLE, "patch(1) not installed")
    def test_random_diffs_apply_cleanly_via_real_patch(self):
        random.seed(11)
        for trial in range(300):
            a = [random.choice("abcde") for _ in range(random.randint(0, 20))]
            b = [random.choice("abcde") for _ in range(random.randint(0, 20))]
            diff_text = unified_diff(a, b, "a.txt", "b.txt")
            if not diff_text:
                self.assertEqual(a, b)
                continue
            with tempfile.TemporaryDirectory() as d:
                fa = os.path.join(d, "a.txt")
                with open(fa, "w") as f:
                    f.write("\n".join(a) + ("\n" if a else ""))
                patchfile = os.path.join(d, "p.diff")
                with open(patchfile, "w") as f:
                    f.write(diff_text)
                result = subprocess.run(
                    ["patch", "-p0", "-s", "-o", os.path.join(d, "out.txt"), fa, patchfile],
                    capture_output=True, text=True, cwd=d,
                )
                self.assertEqual(result.returncode, 0, (trial, a, b, diff_text, result.stderr))
                with open(os.path.join(d, "out.txt")) as f:
                    content = f.read()
                expected = "\n".join(b) + ("\n" if b else "")
                self.assertEqual(content, expected, (trial, a, b))

    def test_context_lines_are_bounded(self):
        a = [str(i) for i in range(20)]
        b = list(a)
        b[10] = "CHANGED"
        out = unified_diff(a, b, context=3)
        # only lines 7..13 (0-indexed) should appear as context/changed
        self.assertIn("@@ -8,7 +8,7 @@", out)
        self.assertNotIn("\n 0\n", out)


if __name__ == "__main__":
    unittest.main()
