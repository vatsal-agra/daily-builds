import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest.merge import find_merge_base, merge_branch, three_way_merge_lines
from palimpsest.repository import RepoError, Repository
from tests import gitoracle


class TempRepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self.repo = Repository.init(self.root)

    def tearDown(self):
        self._tmpdir.cleanup()

    def write(self, path, content):
        with open(os.path.join(self.root, path), "w") as f:
            f.write(content)

    def read(self, path):
        with open(os.path.join(self.root, path)) as f:
            return f.read()

    def commit_file(self, content, msg, ts):
        self.write("f.txt", content)
        self.repo.add(["f.txt"])
        return self.repo.commit(msg, timestamp=ts)


class TestThreeWayMergeLines(unittest.TestCase):
    def test_no_changes_is_identity(self):
        base = ["a", "b", "c"]
        merged, conflict = three_way_merge_lines(base, list(base), list(base))
        self.assertEqual(merged, base)
        self.assertFalse(conflict)

    def test_independent_changes_both_applied(self):
        base = ["a", "b", "c", "d", "e"]
        ours = ["A", "b", "c", "d", "e"]
        theirs = ["a", "b", "c", "d", "E"]
        merged, conflict = three_way_merge_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ["A", "b", "c", "d", "E"])

    def test_identical_edits_are_not_a_conflict(self):
        base = ["a", "b"]
        ours = ["A", "b"]
        theirs = ["A", "b"]
        merged, conflict = three_way_merge_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ["A", "b"])

    def test_conflicting_edits_produce_markers(self):
        base = ["a"]
        ours = ["OURS"]
        theirs = ["THEIRS"]
        merged, conflict = three_way_merge_lines(base, ours, theirs)
        self.assertTrue(conflict)
        self.assertEqual(
            merged,
            ["<<<<<<< ours", "OURS", "=======", "THEIRS", ">>>>>>> theirs"],
        )

    def test_only_ours_changed_no_conflict(self):
        base = ["a", "b", "c"]
        ours = ["a", "X", "c"]
        theirs = ["a", "b", "c"]
        merged, conflict = three_way_merge_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ["a", "X", "c"])

    def test_insertions_at_different_points_both_applied(self):
        base = ["a", "b", "c"]
        ours = ["a", "OURS-INSERT", "b", "c"]
        theirs = ["a", "b", "c", "THEIRS-INSERT"]
        merged, conflict = three_way_merge_lines(base, ours, theirs)
        self.assertFalse(conflict)
        self.assertEqual(merged, ["a", "OURS-INSERT", "b", "c", "THEIRS-INSERT"])

    def test_empty_base_both_sides_add_same_content(self):
        merged, conflict = three_way_merge_lines([], ["x"], ["x"])
        self.assertFalse(conflict)
        self.assertEqual(merged, ["x"])


class TestMergeBase(TempRepoTestCase):
    def test_linear_history_base_is_older_commit(self):
        c1 = self.commit_file("v1\n", "first", 1000)
        c2 = self.commit_file("v2\n", "second", 1001)
        self.assertEqual(find_merge_base(self.repo, c1, c2), c1)
        self.assertEqual(find_merge_base(self.repo, c2, c1), c1)

    def test_same_commit_is_its_own_base(self):
        c1 = self.commit_file("v1\n", "first", 1000)
        self.assertEqual(find_merge_base(self.repo, c1, c1), c1)

    def test_diverged_branches_share_common_ancestor(self):
        c1 = self.commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        c2 = self.commit_file("v2\n", "on feature", 1001)
        self.repo.checkout("main")
        c3 = self.commit_file("v3\n", "on main", 1002)
        self.assertEqual(find_merge_base(self.repo, c2, c3), c1)

    @unittest.skipUnless(gitoracle.GIT_AVAILABLE, "git not installed")
    def test_matches_real_git_merge_base(self):
        with tempfile.TemporaryDirectory() as d:
            gitoracle.git_init(d)
            with open(os.path.join(d, "f.txt"), "w") as f:
                f.write("v1\n")
            gitoracle.run_git(["add", "f.txt"], d)
            gitoracle.run_git(
                ["commit", "-m", "first"], d,
                {"GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"},
            )
            c1 = gitoracle.run_git(["rev-parse", "HEAD"], d).strip()
            gitoracle.run_git(["branch", "feature"], d)
            gitoracle.run_git(["checkout", "-q", "feature"], d)
            with open(os.path.join(d, "f.txt"), "w") as f:
                f.write("v2\n")
            gitoracle.run_git(["commit", "-am", "on feature"], d,
                               {"GIT_AUTHOR_DATE": "1700000001 +0000", "GIT_COMMITTER_DATE": "1700000001 +0000"})
            gitoracle.run_git(["checkout", "-q", "main"], d)
            with open(os.path.join(d, "f.txt"), "w") as f:
                f.write("v3\n")
            gitoracle.run_git(["commit", "-am", "on main"], d,
                               {"GIT_AUTHOR_DATE": "1700000002 +0000", "GIT_COMMITTER_DATE": "1700000002 +0000"})
            expected_base = gitoracle.run_git(["rev-parse", "HEAD~1"], d).strip()
            c2 = gitoracle.run_git(["rev-parse", "feature"], d).strip()
            c3 = gitoracle.run_git(["rev-parse", "main"], d).strip()
            real_base = gitoracle.run_git(["merge-base", c2, c3], d).strip()
            self.assertEqual(real_base, expected_base)

            # Rebuild the same shape with our own repo and compare merge-base sha.
            repo2 = Repository.init(os.path.join(d, "plm-mirror"))
            our_c1 = None
            with open(os.path.join(repo2.root, "f.txt"), "w") as f:
                f.write("v1\n")
            repo2.add(["f.txt"])
            our_c1 = repo2.commit("first", timestamp=1700000000)
            repo2.create_branch("feature")
            repo2.checkout("feature")
            with open(os.path.join(repo2.root, "f.txt"), "w") as f:
                f.write("v2\n")
            repo2.add(["f.txt"])
            our_c2 = repo2.commit("on feature", timestamp=1700000001)
            repo2.checkout("main")
            with open(os.path.join(repo2.root, "f.txt"), "w") as f:
                f.write("v3\n")
            repo2.add(["f.txt"])
            our_c3 = repo2.commit("on main", timestamp=1700000002)
            self.assertEqual(our_c1, c1)
            self.assertEqual(find_merge_base(repo2, our_c2, our_c3), our_c1)


class TestMergeBranch(TempRepoTestCase):
    def test_fast_forward_merge(self):
        self.commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        c2 = self.commit_file("v2\n", "advance", 1001)
        self.repo.checkout("main")
        result = merge_branch(self.repo, "feature", timestamp=1002)
        self.assertTrue(result.fast_forward)
        self.assertEqual(result.commit_sha, c2)
        self.assertEqual(self.read("f.txt"), "v2\n")
        self.assertEqual(self.repo.head_commit(), c2)

    def test_merging_ancestor_is_a_noop(self):
        c1 = self.commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        c2 = self.commit_file("v2\n", "second", 1001)
        result = merge_branch(self.repo, "feature", timestamp=1002)
        self.assertTrue(result.fast_forward)
        self.assertEqual(result.commit_sha, c2)

    def test_clean_three_way_merge_commits(self):
        self.commit_file("line1\nline2\nline3\n", "base", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        self.commit_file("line1\nline2\nTHEIRS\n", "feature change", 1001)
        self.repo.checkout("main")
        self.commit_file("OURS\nline2\nline3\n", "main change", 1002)

        result = merge_branch(self.repo, "feature", timestamp=1003)
        self.assertFalse(result.fast_forward)
        self.assertFalse(result.conflicts)
        self.assertIsNotNone(result.commit_sha)
        self.assertEqual(self.read("f.txt"), "OURS\nline2\nTHEIRS\n")
        commit = self.repo.objects.read_commit(result.commit_sha)
        self.assertEqual(len(commit.parents), 2)

    def test_conflicting_merge_leaves_markers_and_does_not_commit(self):
        self.commit_file("line1\n", "base", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        self.commit_file("FEATURE\n", "feature change", 1001)
        self.repo.checkout("main")
        head_before = self.commit_file("MAIN\n", "main change", 1002)

        result = merge_branch(self.repo, "feature", timestamp=1003)
        self.assertFalse(result.fast_forward)
        self.assertEqual(result.conflicts, ["f.txt"])
        self.assertIsNone(result.commit_sha)
        self.assertEqual(self.repo.head_commit(), head_before)  # not advanced
        content = self.read("f.txt")
        self.assertIn("<<<<<<< ours", content)
        self.assertIn("MAIN", content)
        self.assertIn("FEATURE", content)

    def test_merge_refuses_with_dirty_working_tree(self):
        self.commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout("feature")
        self.commit_file("v2\n", "advance", 1001)
        self.repo.checkout("main")
        self.write("f.txt", "dirty uncommitted\n")
        with self.assertRaises(RepoError):
            merge_branch(self.repo, "feature")

    def test_merge_unknown_branch_raises(self):
        self.commit_file("v1\n", "first", 1000)
        with self.assertRaises(RepoError):
            merge_branch(self.repo, "doesnotexist")

    def test_merge_from_detached_head_raises(self):
        c1 = self.commit_file("v1\n", "first", 1000)
        self.repo.create_branch("feature")
        self.repo.checkout(c1[:8])
        with self.assertRaises(RepoError):
            merge_branch(self.repo, "feature")


if __name__ == "__main__":
    unittest.main()
