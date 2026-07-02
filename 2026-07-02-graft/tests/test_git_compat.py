"""Differential tests: Graft's loose-object bytes are byte-for-byte
identical to real Git's, verified by shelling out to the real `git` binary.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import objecthash, treeops
from graft.repository import Repository

HAVE_GIT = shutil.which("git") is not None


@unittest.skipUnless(HAVE_GIT, "real git binary not available")
class TestGitObjectCompat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Repository.init(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git_cat_file(self, *args):
        return subprocess.run(
            ["git", "--git-dir", self.repo.gitdir, "cat-file", *args],
            cwd=self.tmp, capture_output=True, text=True,
        )

    def test_blob_hash_matches_git_hash_object(self):
        for content in [b"", b"a", b"hello world\n", "café \n".encode("utf-8"), os.urandom(200)]:
            sha1 = self.repo.write_object("blob", content)
            git_result = subprocess.run(
                ["git", "hash-object", "--stdin"], input=content,
                capture_output=True,
            )
            self.assertEqual(sha1, git_result.stdout.decode().strip())

    def test_real_git_can_read_our_loose_blob(self):
        content = b"graft wrote this blob\n"
        sha1 = self.repo.write_object("blob", content)
        result = self._git_cat_file("-p", sha1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.encode(), content)

    def test_real_git_can_read_our_tree(self):
        blob_sha = self.repo.write_object("blob", b"x")
        entries = [
            objecthash.TreeEntry("100644", "a.txt", blob_sha),
            objecthash.TreeEntry("40000", "lib", blob_sha.replace(blob_sha[0], blob_sha[0])),
        ]
        # 'lib' needs to actually be a valid tree object too for `-p` to fully
        # resolve, but `cat-file -t` only needs the object to parse.
        sub_tree_sha = self.repo.write_object(
            "tree", objecthash.encode_tree([objecthash.TreeEntry("100644", "x.txt", blob_sha)])
        )
        entries[1] = objecthash.TreeEntry("40000", "lib", sub_tree_sha)
        tree_content = objecthash.encode_tree(entries)
        tree_sha = self.repo.write_object("tree", tree_content)

        result = self._git_cat_file("-t", tree_sha)
        self.assertEqual(result.stdout.strip(), "tree")
        result = self._git_cat_file("-p", tree_sha)
        self.assertIn("a.txt", result.stdout)
        self.assertIn("lib", result.stdout)

    def test_tree_sha_matches_real_git_write_tree(self):
        # Build an identical file layout with real git and compare the
        # resulting tree sha to what graft's treeops computes independently.
        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("alpha\n")
        os.makedirs(os.path.join(self.tmp, "lib"), exist_ok=True)
        with open(os.path.join(self.tmp, "lib", "inside.txt"), "w") as f:
            f.write("beta\n")
        with open(os.path.join(self.tmp, "lib.py"), "w") as f:
            f.write("gamma\n")

        subprocess.run(["git", "init", "-q", self.tmp], check=True)
        subprocess.run(["git", "-C", self.tmp, "add", "a.txt", "lib/inside.txt", "lib.py"], check=True)
        git_tree_sha = subprocess.run(
            ["git", "-C", self.tmp, "write-tree"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        shutil.rmtree(os.path.join(self.tmp, ".git"))

        blob_a = self.repo.write_object("blob", b"alpha\n")
        blob_inside = self.repo.write_object("blob", b"beta\n")
        blob_libpy = self.repo.write_object("blob", b"gamma\n")
        paths = {
            "a.txt": ("100644", blob_a),
            "lib/inside.txt": ("100644", blob_inside),
            "lib.py": ("100644", blob_libpy),
        }
        graft_tree_sha = treeops.build_tree_from_paths(self.repo, paths)
        self.assertEqual(graft_tree_sha, git_tree_sha)

    def test_commit_object_parses_in_real_git(self):
        tree_sha = self.repo.write_object("tree", objecthash.encode_tree([]))
        author = ("Test", "t@t.com", 1700000000, "+0000")
        content = objecthash.encode_commit(tree_sha, [], author, author, "msg\n")
        commit_sha = self.repo.write_object("commit", content)
        result = self._git_cat_file("-p", commit_sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tree " + tree_sha, result.stdout)
        self.assertIn("msg", result.stdout)


if __name__ == "__main__":
    unittest.main()
