"""End-to-end tests that invoke the real `strata` CLI as a subprocess,
the same way a user would, rather than calling internal Python APIs."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, args, cwd=None, expect_ok=True):
        env = dict(os.environ)
        env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "strata"] + args,
            cwd=cwd or self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if expect_ok and result.returncode != 0:
            self.fail(f"strata {args} failed ({result.returncode}):\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}")
        return result


class TestCliBasicFlow(CliTestCase):
    def test_init_add_commit_log(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("hello\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "Initial commit"], cwd=repo)
        result = self.run_cli(["log"], cwd=repo)
        self.assertIn("Initial commit", result.stdout)

    def test_status_reports_untracked(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "u.txt"), "w") as fh:
            fh.write("x")
        result = self.run_cli(["status"], cwd=repo)
        self.assertIn("Untracked files", result.stdout)
        self.assertIn("u.txt", result.stdout)

    def test_branch_checkout_diff(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("one\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c1"], cwd=repo)
        self.run_cli(["branch", "feature"], cwd=repo)
        self.run_cli(["checkout", "feature"], cwd=repo)
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("one\ntwo\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c2"], cwd=repo)
        self.run_cli(["checkout", "main"], cwd=repo)
        result = self.run_cli(["diff", "main", "feature"], cwd=repo)
        self.assertIn("+two", result.stdout)

    def test_merge_conflict_then_resolve(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("base\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "init"], cwd=repo)
        self.run_cli(["branch", "A"], cwd=repo)
        self.run_cli(["branch", "B"], cwd=repo)
        self.run_cli(["checkout", "A"], cwd=repo)
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("base\nA change\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "a change"], cwd=repo)
        self.run_cli(["checkout", "B"], cwd=repo)
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("base\nB change\n")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "b change"], cwd=repo)
        result = self.run_cli(["merge", "A"], cwd=repo, expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("CONFLICT", result.stdout)
        with open(os.path.join(repo, "a.txt")) as fh:
            self.assertIn("<<<<<<<", fh.read())

    def test_config_roundtrip(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        self.run_cli(["config", "user.name", "Ada"], cwd=repo)
        result = self.run_cli(["config", "user.name"], cwd=repo)
        self.assertEqual(result.stdout.strip(), "Ada")

    def test_viz_writes_valid_html(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("x")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c1"], cwd=repo)
        self.run_cli(["viz", "-o", "graph.html"], cwd=repo)
        out_path = os.path.join(repo, "graph.html")
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path) as fh:
            content = fh.read()
        self.assertTrue(content.startswith("<!doctype html>"))
        self.assertIn("const DATA = ", content)


class TestCliErrorHandling(CliTestCase):
    def test_commands_outside_repo_fail_cleanly(self):
        result = self.run_cli(["status"], expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a strata repository", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_checkout_unknown_branch_fails_cleanly(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("x")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c1"], cwd=repo)
        result = self.run_cli(["checkout", "no-such-branch"], cwd=repo, expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_empty_commit_message_fails_cleanly(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("x")
        self.run_cli(["add", "a.txt"], cwd=repo)
        result = self.run_cli(["commit", "-m", ""], cwd=repo, expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_corrupt_object_fails_cleanly_not_traceback(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("x")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c1"], cwd=repo)

        # Corrupt the exact object `strata log` reads (the HEAD commit
        # object) rather than an arbitrary one — `log` only walks commit
        # objects, so corrupting an unrelated blob/tree wouldn't trigger it.
        with open(os.path.join(repo, ".strata", "refs", "heads", "main")) as fh:
            head_commit_id = fh.read().strip()
        obj_path = os.path.join(repo, ".strata", "objects", head_commit_id[:2], head_commit_id[2:])
        self.assertTrue(os.path.isfile(obj_path))
        with open(obj_path, "r+b") as fh:
            data = bytearray(fh.read())
            data[0] ^= 0xFF
            fh.seek(0)
            fh.write(data)

        result = self.run_cli(["log"], cwd=repo, expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("object store error", result.stderr)

    def test_branch_path_traversal_rejected(self):
        self.run_cli(["init", "repo"])
        repo = os.path.join(self.tmp, "repo")
        with open(os.path.join(repo, "a.txt"), "w") as fh:
            fh.write("x")
        self.run_cli(["add", "a.txt"], cwd=repo)
        self.run_cli(["commit", "-m", "c1"], cwd=repo)
        result = self.run_cli(["branch", "../../evil"], cwd=repo, expect_ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))


if __name__ == "__main__":
    unittest.main()
