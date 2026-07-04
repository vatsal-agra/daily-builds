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

    def test_diff_binary_file_reports_differ_not_garbage(self):
        self.run_cli("init", ".")
        with open("bin.dat", "wb") as f:
            f.write(b"a\x00b\xffc")
        self.run_cli("add", "bin.dat")
        self.run_cli("commit", "-m", "add binary")
        with open("bin.dat", "wb") as f:
            f.write(b"a\x00b\xffCHANGED")
        code, out, _ = self.run_cli("diff")
        self.assertEqual(code, 0)
        self.assertIn("Binary files", out)
        self.assertIn("differ", out)
        self.assertNotIn("\x00", out)

    def test_delete_then_add_then_commit_round_trip(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("hi\n")
        self.run_cli("add", "a.txt")
        self.run_cli("commit", "-m", "add a")
        os.remove("a.txt")
        code, out, _ = self.run_cli("add", "a.txt")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("commit", "-m", "remove a")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("log")
        self.assertIn("remove a", out)

    def test_merge_cli_round_trip(self):
        self.run_cli("init", ".")
        with open("f.txt", "w") as f:
            f.write("line1\nline2\nline3\n")
        self.run_cli("add", "f.txt")
        self.run_cli("commit", "-m", "base")
        self.run_cli("branch", "feature")
        self.run_cli("checkout", "feature")
        with open("f.txt", "w") as f:
            f.write("line1\nline2\nTHEIRS\n")
        self.run_cli("add", "f.txt")
        self.run_cli("commit", "-m", "feature change")
        self.run_cli("checkout", "main")
        with open("f.txt", "w") as f:
            f.write("OURS\nline2\nline3\n")
        self.run_cli("add", "f.txt")
        self.run_cli("commit", "-m", "main change")
        code, out, _ = self.run_cli("merge", "feature")
        self.assertEqual(code, 0)
        self.assertIn("Merge made", out)
        with open("f.txt") as f:
            self.assertEqual(f.read(), "OURS\nline2\nTHEIRS\n")

    def test_viz_writes_html_file(self):
        self.run_cli("init", ".")
        with open("a.txt", "w") as f:
            f.write("hi\n")
        self.run_cli("add", "a.txt")
        self.run_cli("commit", "-m", "first")
        code, out, _ = self.run_cli("viz", "-o", "out.html")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists("out.html"))
        with open("out.html") as f:
            content = f.read()
        self.assertIn("<html>", content)
        self.assertIn("first", content)

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
