import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import merge as merge_mod


def rand_edit(base, rng):
    lines = list(base)
    if not lines or rng.random() < 0.3:
        pos = rng.randint(0, len(lines))
        lines.insert(pos, f"NEW{rng.randint(0, 999)}")
    else:
        pos = rng.randint(0, len(lines) - 1)
        if rng.random() < 0.5:
            del lines[pos]
        else:
            lines[pos] = lines[pos] + "_MOD"
    return lines


class TestMerge3Lines(unittest.TestCase):
    def test_no_edits_no_conflict(self):
        base = ["a", "b", "c"]
        merged, conflict = merge_mod.merge3_lines(base, base, base)
        self.assertFalse(conflict)
        self.assertEqual(merged, base)

    def test_only_ours_changed(self):
        base = ["a", "b", "c"]
        ours = ["a", "B", "c"]
        merged, conflict = merge_mod.merge3_lines(base, ours, base)
        self.assertFalse(conflict)
        self.assertEqual(merged, ours)

    def test_only_theirs_changed(self):
        base = ["a", "b", "c"]
        theirs = ["a", "b", "C"]
        merged, conflict = merge_mod.merge3_lines(base, base, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, theirs)

    def test_edits_separated_by_unchanged_line_merge_cleanly(self):
        # Verified against real git: a >=1 unchanged-line gap between two
        # edited regions merges without conflict.
        base = ["line1", "line2", "line3", "line4", "line5"]
        ours = ["line1", "line2-ours", "line3", "line4", "line5"]
        theirs = ["line1", "line2", "line3", "line4-theirs", "line5"]
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
        self.assertFalse(conflict, merged)
        self.assertEqual(
            merged, ["line1", "line2-ours", "line3", "line4-theirs", "line5"]
        )

    def test_immediately_adjacent_edits_conflict(self):
        # Verified against real git: editing two directly-adjacent lines
        # (no unchanged line of separation) conflicts, even though the
        # edited ranges themselves don't overlap -- git is conservative
        # about hunks that touch.
        base = ["line1", "line2", "line3"]
        ours = ["line1", "line2-ours", "line3"]
        theirs = ["line1", "line2", "line3-theirs"]
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
        self.assertTrue(conflict, merged)

    def test_identical_edits_no_conflict(self):
        base = ["a", "b", "c"]
        ours = ["a", "X", "c"]
        theirs = ["a", "X", "c"]
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ours)

    def test_overlapping_edits_conflict_with_markers(self):
        base = ["a", "b", "c"]
        ours = ["a", "OURS", "c"]
        theirs = ["a", "THEIRS", "c"]
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs, "mine", "yours")
        self.assertTrue(conflict)
        self.assertIn("<<<<<<< mine", merged)
        self.assertIn("OURS", merged)
        self.assertIn("=======", merged)
        self.assertIn("THEIRS", merged)
        self.assertIn(">>>>>>> yours", merged)

    def test_insert_at_same_point_both_sides_different_content_conflicts(self):
        base = ["a", "b"]
        ours = ["a", "OURS-INSERT", "b"]
        theirs = ["a", "THEIRS-INSERT", "b"]
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
        self.assertTrue(conflict)

    def test_deletion_vs_untouched(self):
        base = ["a", "b", "c"]
        ours = ["a", "c"]  # deleted "b"
        theirs = base
        merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ours)

    def test_fuzz_merge_invariants(self):
        rng = random.Random(7)
        conflicts = 0
        for _ in range(500):
            base = [f"L{i}" for i in range(rng.randint(3, 15))]
            ours = rand_edit(base, rng)
            theirs = rand_edit(base, rng)
            merged, conflict = merge_mod.merge3_lines(base, ours, theirs)
            if conflict:
                conflicts += 1
                self.assertTrue(any(l.startswith("<<<<<<<") for l in merged))
            else:
                if ours == base:
                    self.assertEqual(merged, theirs)
                if theirs == base:
                    self.assertEqual(merged, ours)
                if ours == theirs:
                    self.assertEqual(merged, ours)
        self.assertGreater(conflicts, 0)  # sanity: fuzz actually exercises conflicts


class TestFindMergeBase(unittest.TestCase):
    def test_linear_history(self):
        class FakeRepo:
            def __init__(self, commits):
                self.commits = commits

            def read_object_any(self, sha):
                return "commit", self.commits[sha]

        from graft import objecthash

        def make(parents):
            return objecthash.encode_commit(
                "t" * 40, parents, ("a", "a@a", 1, "+0000"), ("a", "a@a", 1, "+0000"), "m"
            )

        c1 = make([])
        c2 = make(["c1"])
        commits = {"c1": c1, "c2": c2}
        repo = FakeRepo(commits)
        self.assertEqual(merge_mod.find_merge_base(repo, "c1", "c1"), "c1")
        self.assertEqual(merge_mod.find_merge_base(repo, "c2", "c1"), "c1")


if __name__ == "__main__":
    unittest.main()
