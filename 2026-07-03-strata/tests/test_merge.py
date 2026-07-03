import random
import unittest

from strata.merge import three_way_merge


def _mklines(n, alphabet="ABCDE"):
    return [random.choice(alphabet) + "\n" for _ in range(n)]


def _mutate(lines, ops=2):
    lines = list(lines)
    for _ in range(ops):
        choice = random.choice(["ins", "del", "mod"]) if lines else "ins"
        if choice == "ins" or not lines:
            lines.insert(random.randint(0, len(lines)), random.choice("XYZ") + "\n")
        elif choice == "del":
            del lines[random.randint(0, len(lines) - 1)]
        else:
            lines[random.randint(0, len(lines) - 1)] = random.choice("XYZ") + "\n"
    return lines


class TestThreeWayMerge(unittest.TestCase):
    def test_eof_dual_insert_conflicts(self):
        # Regression test for REVIEW.md finding #3: appending different
        # content at EOF on both sides used to be silently dropped.
        base = "hello world\nmodified on feature\n"
        ours = base + "branchB change\n"
        theirs = base + "branchA change\n"
        r = three_way_merge(base, ours, theirs, "branchB", "branchA")
        self.assertTrue(r.has_conflict)
        self.assertIn("<<<<<<< branchB", r.text)
        self.assertIn("branchB change", r.text)
        self.assertIn(">>>>>>> branchA", r.text)
        self.assertIn("branchA change", r.text)

    def test_one_side_unchanged_never_conflicts(self):
        random.seed(7)
        for _ in range(400):
            base_lines = _mklines(random.randint(0, 8))
            base = "".join(base_lines)
            theirs_lines = _mutate(base_lines, random.randint(1, 3))
            r = three_way_merge(base, base, "".join(theirs_lines))
            self.assertFalse(r.has_conflict)
            self.assertEqual(r.text, "".join(theirs_lines))

            ours_lines = _mutate(base_lines, random.randint(1, 3))
            r = three_way_merge(base, "".join(ours_lines), base)
            self.assertFalse(r.has_conflict)
            self.assertEqual(r.text, "".join(ours_lines))

    def test_identical_change_never_conflicts(self):
        random.seed(7)
        for _ in range(300):
            base_lines = _mklines(random.randint(0, 8))
            base = "".join(base_lines)
            mutated = _mutate(base_lines, random.randint(1, 3))
            r = three_way_merge(base, "".join(mutated), "".join(mutated))
            self.assertFalse(r.has_conflict)

    def test_disjoint_edits_merge_silently(self):
        random.seed(11)
        for _ in range(400):
            n = random.randint(4, 12)
            base_lines = [f"L{i}\n" for i in range(n)]
            base = "".join(base_lines)
            mid = n // 2
            ours_lines = list(base_lines)
            theirs_lines = list(base_lines)
            expected = list(base_lines)
            if mid >= 1:
                idx = random.randint(0, mid - 1)
                ours_lines[idx] = "OURS-CHANGE\n"
                expected[idx] = "OURS-CHANGE\n"
            if mid + 1 <= n - 1:
                idx2 = random.randint(mid + 1, n - 1)
                theirs_lines[idx2] = "THEIRS-CHANGE\n"
                expected[idx2] = "THEIRS-CHANGE\n"
            r = three_way_merge(base, "".join(ours_lines), "".join(theirs_lines))
            self.assertFalse(r.has_conflict)
            self.assertEqual(r.text, "".join(expected))

    def test_same_line_conflicting_edits_always_conflict(self):
        random.seed(13)
        for _ in range(300):
            n = random.randint(1, 10)
            base_lines = [f"L{i}\n" for i in range(n)]
            base = "".join(base_lines)
            idx = random.randint(0, n - 1)
            ours_lines = list(base_lines)
            ours_lines[idx] = "OURS\n"
            theirs_lines = list(base_lines)
            theirs_lines[idx] = "THEIRS\n"
            r = three_way_merge(base, "".join(ours_lines), "".join(theirs_lines), "ours", "theirs")
            self.assertTrue(r.has_conflict)
            self.assertIn("OURS", r.text)
            self.assertIn("THEIRS", r.text)

    def test_no_changes_produces_base(self):
        base = "a\nb\nc\n"
        r = three_way_merge(base, base, base)
        self.assertFalse(r.has_conflict)
        self.assertEqual(r.text, base)


if __name__ == "__main__":
    unittest.main()
