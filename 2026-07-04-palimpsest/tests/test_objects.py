import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palimpsest import objects as om
from palimpsest.objects import Commit, ObjectStore, TreeEntry
from tests import gitoracle


class TestBlobHashing(unittest.TestCase):
    def test_empty_blob_matches_git_well_known_sha(self):
        sha, _ = om.hash_object_bytes("blob", b"")
        self.assertEqual(sha, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_known_string_matches_git_well_known_sha(self):
        sha, _ = om.hash_object_bytes("blob", b"hello world\n")
        self.assertEqual(sha, "3b18e512dba79e4c8300dd08aeb37f8e728b8dad")

    @unittest.skipUnless(gitoracle.GIT_AVAILABLE, "git not installed")
    def test_random_content_matches_real_git_hash_object(self):
        random.seed(1)
        with tempfile.TemporaryDirectory() as d:
            gitoracle.git_init(d)
            for i in range(20):
                data = bytes(random.randrange(256) for _ in range(random.randint(0, 500)))
                path = os.path.join(d, f"f{i}.bin")
                with open(path, "wb") as f:
                    f.write(data)
                expected = gitoracle.git_hash_object(d, path)
                sha, _ = om.hash_object_bytes("blob", data)
                self.assertEqual(sha, expected, f"mismatch on trial {i}")


class TestObjectStore(unittest.TestCase):
    def test_write_read_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            store = ObjectStore(os.path.join(d, "objects"))
            sha = store.write_blob(b"some content")
            self.assertEqual(store.read_blob(sha), b"some content")

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            store = ObjectStore(os.path.join(d, "objects"))
            sha1 = store.write_blob(b"x")
            sha2 = store.write_blob(b"x")
            self.assertEqual(sha1, sha2)

    def test_missing_object_raises(self):
        with tempfile.TemporaryDirectory() as d:
            store = ObjectStore(os.path.join(d, "objects"))
            with self.assertRaises(KeyError):
                store.read_blob("0" * 40)


class TestTreeEncoding(unittest.TestCase):
    def test_round_trip(self):
        entries = [
            TreeEntry(mode=om.MODE_FILE, name="b.txt", sha="a" * 40),
            TreeEntry(mode=om.MODE_DIR, name="a", sha="b" * 40),
        ]
        encoded = om.encode_tree(entries)
        decoded = om.decode_tree(encoded)
        self.assertEqual({(e.mode, e.name, e.sha) for e in decoded},
                          {(e.mode, e.name, e.sha) for e in entries})

    def test_directory_sorts_after_dotted_prefix_match(self):
        # Classic git tree-sort gotcha: "a.txt" vs directory "a" — the
        # directory name sorts as if it had a trailing '/', so "a" (dir)
        # sorts AFTER "a.txt" ('.' = 0x2e < '/' = 0x2f).
        entries = [
            TreeEntry(mode=om.MODE_DIR, name="a", sha="1" * 40),
            TreeEntry(mode=om.MODE_FILE, name="a.txt", sha="2" * 40),
        ]
        encoded = om.encode_tree(entries)
        decoded = om.decode_tree(encoded)
        self.assertEqual([e.name for e in decoded], ["a.txt", "a"])

    @unittest.skipUnless(gitoracle.GIT_AVAILABLE, "git not installed")
    def test_matches_real_git_mktree(self):
        with tempfile.TemporaryDirectory() as d:
            gitoracle.git_init(d)
            import subprocess

            blob_sha = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=d, input="hello\n", text=True, capture_output=True,
                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": d},
            ).stdout.strip()

            subtree_sha = gitoracle.git_mktree(
                d, [(om.MODE_FILE, "inner.txt", blob_sha, "blob")]
            )

            entries = [
                TreeEntry(mode=om.MODE_FILE, name="a.txt", sha=blob_sha),
                TreeEntry(mode=om.MODE_DIR, name="a", sha=subtree_sha),
                TreeEntry(mode=om.MODE_FILE, name="zzz", sha=blob_sha),
                TreeEntry(mode=om.MODE_FILE, name="b-file", sha=blob_sha),
            ]
            our_sha, _ = om.hash_object_bytes("tree", om.encode_tree(entries))
            git_sha = gitoracle.git_mktree(
                d, [(e.mode, e.name, e.sha, "tree" if e.mode == om.MODE_DIR else "blob") for e in entries]
            )
            self.assertEqual(our_sha, git_sha)


class TestCommitEncoding(unittest.TestCase):
    def test_round_trip(self):
        c = Commit(
            tree="a" * 40,
            parents=["b" * 40],
            author_time=1000,
            committer_time=1000,
            message="hello\n",
        )
        decoded = Commit.decode(c.encode())
        self.assertEqual(decoded.tree, c.tree)
        self.assertEqual(decoded.parents, c.parents)
        self.assertEqual(decoded.message, c.message)
        self.assertEqual(decoded.author_time, 1000)

    def test_message_without_trailing_newline_gets_one(self):
        c = Commit(tree="a" * 40, message="no newline")
        self.assertTrue(c.encode().endswith(b"no newline\n"))

    @unittest.skipUnless(gitoracle.GIT_AVAILABLE, "git not installed")
    def test_matches_real_git_commit_tree(self):
        with tempfile.TemporaryDirectory() as d:
            gitoracle.git_init(d)
            empty_tree = gitoracle.git_mktree(d, [])
            ts = 1700000000
            git_sha = gitoracle.git_commit_tree(d, empty_tree, [], "initial\n", ts)

            c = Commit(tree=empty_tree, author_time=ts, committer_time=ts, message="initial\n")
            our_sha, _ = om.hash_object_bytes("commit", c.encode())
            self.assertEqual(our_sha, git_sha)

    @unittest.skipUnless(gitoracle.GIT_AVAILABLE, "git not installed")
    def test_matches_real_git_commit_tree_with_parent(self):
        with tempfile.TemporaryDirectory() as d:
            gitoracle.git_init(d)
            empty_tree = gitoracle.git_mktree(d, [])
            ts = 1700000000
            parent_sha = gitoracle.git_commit_tree(d, empty_tree, [], "first\n", ts)
            child_sha = gitoracle.git_commit_tree(d, empty_tree, [parent_sha], "second\n", ts + 10)

            c1 = Commit(tree=empty_tree, author_time=ts, committer_time=ts, message="first\n")
            our_parent, _ = om.hash_object_bytes("commit", c1.encode())
            self.assertEqual(our_parent, parent_sha)

            c2 = Commit(
                tree=empty_tree,
                parents=[our_parent],
                author_time=ts + 10,
                committer_time=ts + 10,
                message="second\n",
            )
            our_child, _ = om.hash_object_bytes("commit", c2.encode())
            self.assertEqual(our_child, child_sha)


if __name__ == "__main__":
    unittest.main()
