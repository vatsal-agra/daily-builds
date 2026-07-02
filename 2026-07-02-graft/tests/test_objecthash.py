import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import objecthash


class TestBlob(unittest.TestCase):
    def test_hash_bytes_matches_known_git_sha(self):
        # "hello world\n" is a famous test vector: git hash-object always
        # returns this sha for this exact content.
        sha1, store = objecthash.hash_bytes("blob", b"hello world\n")
        self.assertEqual(sha1, "3b18e512dba79e4c8300dd08aeb37f8e728b8dad")
        self.assertTrue(store.startswith(b"blob 12\0"))

    def test_empty_blob_known_sha(self):
        sha1, _ = objecthash.hash_bytes("blob", b"")
        self.assertEqual(sha1, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_write_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            sha1 = objecthash.write_object(d, "blob", b"round trip content")
            obj_type, content = objecthash.read_object_raw(d, sha1)
            self.assertEqual(obj_type, "blob")
            self.assertEqual(content, b"round trip content")

    def test_write_is_idempotent_content_addressed(self):
        with tempfile.TemporaryDirectory() as d:
            sha1a = objecthash.write_object(d, "blob", b"same content")
            sha1b = objecthash.write_object(d, "blob", b"same content")
            self.assertEqual(sha1a, sha1b)

    def test_corrupt_object_size_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as d:
            sha1 = objecthash.write_object(d, "blob", b"abc")
            path = objecthash.object_path(d, sha1)
            import zlib
            with open(path, "wb") as f:
                f.write(zlib.compress(b"blob 999\0abc"))
            with self.assertRaises(objecthash.ObjectError):
                objecthash.read_object_raw(d, sha1)


class TestTree(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        entries = [
            objecthash.TreeEntry("100644", "b.txt", "a" * 40),
            objecthash.TreeEntry("100644", "a.txt", "b" * 40),
            objecthash.TreeEntry("40000", "sub", "c" * 40),
        ]
        content = objecthash.encode_tree(entries)
        decoded = objecthash.decode_tree(content)
        self.assertEqual([e.name for e in decoded], ["a.txt", "b.txt", "sub"])

    def test_git_directory_sort_quirk(self):
        # git sorts as if directories have a trailing '/': "lib.py" < "lib"
        entries = [
            objecthash.TreeEntry("40000", "lib", "a" * 40),
            objecthash.TreeEntry("100644", "lib.py", "b" * 40),
        ]
        content = objecthash.encode_tree(entries)
        decoded = objecthash.decode_tree(content)
        self.assertEqual([e.name for e in decoded], ["lib.py", "lib"])

    def test_duplicate_name_rejected(self):
        entries = [
            objecthash.TreeEntry("100644", "x", "a" * 40),
            objecthash.TreeEntry("100644", "x", "b" * 40),
        ]
        with self.assertRaises(objecthash.ObjectError):
            objecthash.encode_tree(entries)

    def test_empty_tree_known_sha(self):
        sha1, _ = objecthash.hash_bytes("tree", objecthash.encode_tree([]))
        self.assertEqual(sha1, "4b825dc642cb6eb9a060e54bf8d69288fbee4904")


class TestCommit(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        content = objecthash.encode_commit(
            "t" * 40, ["p" * 40], ("A", "a@b.com", 1000, "+0000"),
            ("A", "a@b.com", 1000, "+0000"), "hello\n\nbody line\n",
        )
        info = objecthash.decode_commit(content)
        self.assertEqual(info["tree"], "t" * 40)
        self.assertEqual(info["parents"], ["p" * 40])
        self.assertEqual(info["message"], "hello\n\nbody line\n")

    def test_root_commit_no_parents(self):
        content = objecthash.encode_commit(
            "t" * 40, [], ("A", "a@b.com", 1, "+0000"),
            ("A", "a@b.com", 1, "+0000"), "root",
        )
        info = objecthash.decode_commit(content)
        self.assertEqual(info["parents"], [])

    def test_message_without_trailing_newline_gets_one(self):
        content = objecthash.encode_commit(
            "t" * 40, [], ("A", "a@b.com", 1, "+0000"),
            ("A", "a@b.com", 1, "+0000"), "no newline",
        )
        self.assertTrue(content.endswith(b"no newline\n"))


if __name__ == "__main__":
    unittest.main()
