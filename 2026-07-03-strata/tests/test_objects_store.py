import itertools
import os
import shutil
import tempfile
import unittest

from strata.hashing import hash_object
from strata.objects import (
    MODE_DIR, MODE_FILE, Commit, InvalidObject, TreeEntry,
    decode_commit, decode_tree, encode_commit, encode_tree,
)
from strata.store import CorruptObject, ObjectNotFound, ObjectStore


class TestObjectStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = ObjectStore(os.path.join(self.tmp, "objects"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_write_read_roundtrip(self):
        oid = self.store.write("blob", b"hello world")
        obj_type, content = self.store.read(oid)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(content, b"hello world")

    def test_write_is_content_addressed(self):
        oid1 = self.store.write("blob", b"same content")
        oid2 = self.store.write("blob", b"same content")
        self.assertEqual(oid1, oid2)

    def test_write_is_idempotent_on_disk(self):
        self.store.write("blob", b"data")
        self.store.write("blob", b"data")  # must not error or duplicate
        self.assertTrue(self.store.has(hash_object("blob", b"data")))

    def test_has_false_for_missing(self):
        self.assertFalse(self.store.has("0" * 64))

    def test_read_missing_raises(self):
        with self.assertRaises(ObjectNotFound):
            self.store.read("0" * 64)

    def test_invalid_id_rejected(self):
        with self.assertRaises(ValueError):
            self.store._path("not-a-valid-hash")

    def test_corruption_detected(self):
        oid = self.store.write("blob", b"important data")
        path = self.store._path(oid)
        with open(path, "rb") as fh:
            data = bytearray(fh.read())
        data[len(data) // 2] ^= 0xFF
        with open(path, "wb") as fh:
            fh.write(data)
        with self.assertRaises(CorruptObject):
            self.store.read(oid)

    def test_iter_ids(self):
        oid1 = self.store.write("blob", b"a")
        oid2 = self.store.write("blob", b"b")
        self.assertEqual(set(self.store.iter_ids()), {oid1, oid2})

    def test_binary_content_roundtrip(self):
        data = bytes(range(256)) * 4
        oid = self.store.write("blob", data)
        self.assertEqual(self.store.read(oid)[1], data)


class TestCommitEncoding(unittest.TestCase):
    def test_roundtrip_various_messages_and_parity(self):
        messages = ["simple", "multi\nline\nmessage", "trailing newline\n", "unicode: héllo 日本語 🎉"]
        for msg in messages:
            for parents in [(), ("a" * 64,), ("a" * 64, "b" * 64)]:
                with self.subTest(msg=msg, parents=parents):
                    c = Commit(tree="c" * 64, parents=parents, author="T <t@example.com>",
                                timestamp=1234567890, message=msg)
                    decoded = decode_commit(encode_commit(c))
                    self.assertEqual(decoded.tree, c.tree)
                    self.assertEqual(decoded.parents, c.parents)
                    self.assertEqual(decoded.author, c.author)
                    self.assertEqual(decoded.timestamp, c.timestamp)
                    expected_msg = msg if msg.endswith("\n") else msg + "\n"
                    self.assertEqual(decoded.message, expected_msg)

    def test_malformed_commit_rejected(self):
        with self.assertRaises(InvalidObject):
            decode_commit(b"not a valid commit at all")


class TestTreeEncoding(unittest.TestCase):
    def _entries(self):
        names = ["a.txt", "файл.txt", "日本語.py", "with spaces.md", ".hidden", "UPPER.TXT"]
        entries = [
            TreeEntry(mode=MODE_FILE, name=n, object_id=hash_object("blob", n.encode()), kind="blob")
            for n in names
        ]
        entries.append(TreeEntry(mode=MODE_DIR, name="subdir", object_id="d" * 64, kind="tree"))
        return entries

    def test_roundtrip(self):
        entries = self._entries()
        decoded = decode_tree(encode_tree(entries))
        self.assertEqual(
            sorted((e.name, e.mode, e.object_id, e.kind) for e in decoded),
            sorted((e.name, e.mode, e.object_id, e.kind) for e in entries),
        )

    def test_encoding_is_order_independent(self):
        entries = self._entries()
        outputs = {encode_tree(list(p)) for p in itertools.islice(itertools.permutations(entries), 20)}
        self.assertEqual(len(outputs), 1)

    def test_illegal_names_rejected_on_encode(self):
        for bad in ["a/b", "a\\b", ".", "..", "", "a\tb", "a\nb"]:
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidObject):
                    encode_tree([TreeEntry(mode=MODE_FILE, name=bad, object_id="e" * 64, kind="blob")])

    def test_illegal_names_rejected_on_decode(self):
        # A hand-crafted malicious tree object (e.g. from a corrupted or
        # tampered object file) must be rejected on the READ path too, since
        # that's what actually matters for checkout's path-traversal safety.
        for bad in ["../../../etc/passwd", "a/b"]:
            with self.subTest(bad=bad):
                raw = f"{MODE_FILE} blob ".encode() + b"e" * 64 + b"\t" + bad.encode() + b"\n"
                with self.assertRaises(InvalidObject):
                    decode_tree(raw)


if __name__ == "__main__":
    unittest.main()
