import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest.cli import main


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()


class TestCliWorkflow(CliTestCase):
    def test_init_add_commit_log(self):
        code, out, _ = self.run_cli("init", ".")
        self.assertEqual(code, 0)
        self.assertIn("Initialized", out)

        with open("a.txt", "w") as f:
            f.write("hello\n")
        code, out, _ = self.run_cli("add", "a.txt")
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli("commit", "-m", "first commit")
        self.assertEqual(code, 0)
        self.assertIn("first commit", out)

        code, out, _ = self.run_cli("log")
        self.assertEqual(code, 0)
        self.assertIn("first commit", out)
        self.assertIn("commit ", out)

    def test_status_reports_untracked(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("x\n")
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Untracked files", out)
        self.assertIn("a.txt", out)

    def test_branch_and_checkout(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("v1\n")
        self.run_cli("add", "a.txt")
        self.run_cli("commit", "-m", "first")
        code, out, _ = self.run_cli("branch", "feature")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("branch")
        self.assertIn("feature", out)
        self.assertIn("* main", out)
        code, out, _ = self.run_cli("checkout", "feature")
        self.assertEqual(code, 0)

    def test_diff_worktree_vs_index(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("line1\n")
        self.run_cli("add", "a.txt")
        self.run_cli("commit", "-m", "first")
        with open("a.txt", "w") as f:
            f.write("line1\nline2\n")
        code, out, _ = self.run_cli("diff")
        self.assertEqual(code, 0)
        self.assertIn("+line2", out)

    def test_hash_object_and_cat_file_round_trip(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("payload\n")
        code, out, _ = self.run_cli("hash-object", "-w", "a.txt")
        self.assertEqual(code, 0)
        sha = out.strip()
        code, out, _ = self.run_cli("cat-file", sha)
        self.assertEqual(code, 0)
        self.assertEqual(out, "payload\n")

    def test_commit_without_repo_reports_clean_error(self):
        code, out, err = self.run_cli("status")
        self.assertNotEqual(code, 0)
        self.assertIn("not a palimpsest repository", err)

    def test_checkout_unknown_branch_reports_error(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("v1\n")
        self.run_cli("add", "a.txt")
        self.run_cli("commit", "-m", "first")
        code, out, err = self.run_cli("checkout", "doesnotexist")
        self.assertNotEqual(code, 0)
        self.assertIn("unknown revision", err)


if __name__ == "__main__":
    unittest.main()
