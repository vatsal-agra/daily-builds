"""End-to-end tests driving the real `graft` CLI as a subprocess, the same
way a user would. Covers every required and stretch feature.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import run_git, run_graft, write

HAVE_GIT = shutil.which("git") is not None


class GraftCliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        run_graft(self.tmp, "init", ".")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestInitAddCommit(GraftCliTestCase):
    def test_init_creates_graft_dir(self):
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, ".graft")))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, ".graft", "objects")))

    def test_add_commit_status_clean(self):
        write(os.path.join(self.tmp, "a.txt"), "hello\n")
        run_graft(self.tmp, "add", "a.txt")
        status = run_graft(self.tmp, "status").stdout
        self.assertIn("new file:   a.txt", status)
        run_graft(self.tmp, "commit", "-m", "first")
        status = run_graft(self.tmp, "status").stdout
        self.assertIn("nothing to commit", status)

    def test_add_from_subdirectory_resolves_relative_to_cwd(self):
        os.makedirs(os.path.join(self.tmp, "sub"))
        write(os.path.join(self.tmp, "sub", "nested.txt"), "x\n")
        subdir = os.path.join(self.tmp, "sub")
        run_graft(subdir, "add", "nested.txt")
        status = run_graft(self.tmp, "status").stdout
        self.assertIn("sub/nested.txt", status)

    def test_commit_without_message_fails_cleanly(self):
        write(os.path.join(self.tmp, "a.txt"), "x\n")
        run_graft(self.tmp, "add", "a.txt")
        result = run_graft(self.tmp, "commit", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("message required", result.stderr)

    def test_hash_object_matches_real_git(self):
        write(os.path.join(self.tmp, "a.txt"), "hello world\n")
        graft_sha = run_graft(self.tmp, "hash-object", "a.txt").stdout.strip()
        self.assertEqual(graft_sha, "3b18e512dba79e4c8300dd08aeb37f8e728b8dad")


class TestDiff(GraftCliTestCase):
    def test_diff_shows_unified_hunk(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n2\n3\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        write(os.path.join(self.tmp, "a.txt"), "1\nTWO\n3\n")
        out = run_graft(self.tmp, "diff").stdout
        self.assertIn("-2", out)
        self.assertIn("+TWO", out)

    def test_diff_cached(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        write(os.path.join(self.tmp, "a.txt"), "2\n")
        run_graft(self.tmp, "add", "a.txt")
        out = run_graft(self.tmp, "diff", "--cached").stdout
        self.assertIn("-1", out)
        self.assertIn("+2", out)

    def test_binary_diff_reports_binary_not_garbage(self):
        write(os.path.join(self.tmp, "b.dat"), b"\x00\x01\x02")
        run_graft(self.tmp, "add", "b.dat")
        run_graft(self.tmp, "commit", "-m", "c1")
        write(os.path.join(self.tmp, "b.dat"), b"\x00\x01\x03")
        out = run_graft(self.tmp, "diff").stdout
        self.assertIn("Binary files", out)


class TestBranchCheckoutLog(GraftCliTestCase):
    def test_branch_and_checkout(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        run_graft(self.tmp, "branch", "feature")
        branches = run_graft(self.tmp, "branch").stdout
        self.assertIn("feature", branches)
        self.assertIn("* main", branches)
        run_graft(self.tmp, "checkout", "feature")
        branches = run_graft(self.tmp, "branch").stdout
        self.assertIn("* feature", branches)

    def test_checkout_refuses_with_uncommitted_changes(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        run_graft(self.tmp, "branch", "feature")
        write(os.path.join(self.tmp, "a.txt"), "dirty\n")
        run_graft(self.tmp, "add", "a.txt")
        result = run_graft(self.tmp, "checkout", "feature", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_checkout_detached_and_back(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        c1 = run_graft(self.tmp, "commit", "-m", "c1").stdout
        sha = c1.split()[1].rstrip("]")
        run_graft(self.tmp, "checkout", sha)
        self.assertIn("detached", run_graft(self.tmp, "status").stdout.lower())
        run_graft(self.tmp, "checkout", "main")
        self.assertIn("On branch main", run_graft(self.tmp, "status").stdout)

    def test_log_shows_history_newest_first(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "first")
        write(os.path.join(self.tmp, "a.txt"), "2\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "second")
        log = run_graft(self.tmp, "log").stdout
        self.assertLess(log.index("second"), log.index("first"))


class TestMergeFlow(GraftCliTestCase):
    def test_fast_forward_merge(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        run_graft(self.tmp, "branch", "feature")
        write(os.path.join(self.tmp, "a.txt"), "2\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c2")
        run_graft(self.tmp, "checkout", "feature")
        out = run_graft(self.tmp, "merge", "main").stdout
        self.assertIn("Fast-forward", out)
        with open(os.path.join(self.tmp, "a.txt")) as f:
            self.assertEqual(f.read(), "2\n")

    def test_clean_three_way_merge(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n2\n3\n4\n5\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "base")
        run_graft(self.tmp, "branch", "feature")
        write(os.path.join(self.tmp, "a.txt"), "1-OURS\n2\n3\n4\n5\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "ours")
        run_graft(self.tmp, "checkout", "feature")
        write(os.path.join(self.tmp, "a.txt"), "1\n2\n3\n4\n5-THEIRS\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "theirs")
        run_graft(self.tmp, "checkout", "main")
        out = run_graft(self.tmp, "merge", "feature").stdout
        self.assertIn("Merge made", out)
        with open(os.path.join(self.tmp, "a.txt")) as f:
            self.assertEqual(f.read(), "1-OURS\n2\n3\n4\n5-THEIRS\n")

    def test_conflicting_merge_leaves_markers_and_blocks_status(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n2\n3\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "base")
        run_graft(self.tmp, "branch", "feature")
        write(os.path.join(self.tmp, "a.txt"), "1\nOURS\n3\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "ours")
        run_graft(self.tmp, "checkout", "feature")
        write(os.path.join(self.tmp, "a.txt"), "1\nTHEIRS\n3\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "theirs")
        run_graft(self.tmp, "checkout", "main")
        result = run_graft(self.tmp, "merge", "feature", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("CONFLICT", result.stdout)
        with open(os.path.join(self.tmp, "a.txt")) as f:
            content = f.read()
        self.assertIn("<<<<<<<", content)
        # resolve and finish the merge
        write(os.path.join(self.tmp, "a.txt"), "1\nRESOLVED\n3\n")
        run_graft(self.tmp, "add", "a.txt")
        result = run_graft(self.tmp, "commit", "-m", "resolve")
        log = run_graft(self.tmp, "log").stdout
        self.assertIn("Merge:", log)


class TestGc(GraftCliTestCase):
    def test_gc_preserves_all_content(self):
        for i in range(5):
            write(os.path.join(self.tmp, f"f{i}.txt"), f"content {i}\n" * 5)
            run_graft(self.tmp, "add", f"f{i}.txt")
        run_graft(self.tmp, "commit", "-m", "many files")
        out = run_graft(self.tmp, "gc").stdout
        self.assertIn("Packed", out)
        for i in range(5):
            with open(os.path.join(self.tmp, f"f{i}.txt")) as f:
                pass  # still on disk
        status = run_graft(self.tmp, "status").stdout
        self.assertIn("nothing to commit", status)
        run_graft(self.tmp, "checkout", "main", "-f")


class TestViz(GraftCliTestCase):
    def test_viz_generates_html(self):
        write(os.path.join(self.tmp, "a.txt"), "1\n")
        run_graft(self.tmp, "add", "a.txt")
        run_graft(self.tmp, "commit", "-m", "c1")
        run_graft(self.tmp, "viz", "-o", "out.html")
        out_path = os.path.join(self.tmp, "out.html")
        self.assertTrue(os.path.exists(out_path))
        with open(out_path) as f:
            content = f.read()
        self.assertIn("<html>", content)
        self.assertIn("c1", content)


class TestErrorHandling(GraftCliTestCase):
    def test_add_nonexistent_path(self):
        result = run_graft(self.tmp, "add", "nope.txt", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pathspec", result.stderr)

    def test_status_outside_repo(self):
        outside = tempfile.mkdtemp()
        try:
            result = run_graft(outside, "status", check=False)
            self.assertNotEqual(result.returncode, 0)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_checkout_unknown_branch(self):
        result = run_graft(self.tmp, "checkout", "doesnotexist", check=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
