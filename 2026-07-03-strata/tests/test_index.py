import os
import shutil
import tempfile
import unittest

from strata.index import Index
from strata.objects import MODE_EXEC, MODE_FILE


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "index")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_set_get(self):
        idx = Index(self.path)
        idx.set("a.txt", "h" * 64)
        self.assertEqual(idx.get("a.txt"), {"hash": "h" * 64, "mode": MODE_FILE})

    def test_persists_across_instances(self):
        idx = Index(self.path)
        idx.set("a.txt", "h" * 64, MODE_EXEC)
        idx.save()
        idx2 = Index(self.path)
        self.assertEqual(idx2.get("a.txt"), {"hash": "h" * 64, "mode": MODE_EXEC})

    def test_remove(self):
        idx = Index(self.path)
        idx.set("a.txt", "h" * 64)
        idx.remove("a.txt")
        self.assertIsNone(idx.get("a.txt"))

    def test_remove_missing_is_noop(self):
        idx = Index(self.path)
        idx.remove("does-not-exist.txt")  # must not raise

    def test_empty_index_starts_empty(self):
        idx = Index(self.path)
        self.assertEqual(idx.paths(), set())

    def test_as_dict(self):
        idx = Index(self.path)
        idx.set("a.txt", "a" * 64)
        idx.set("b.txt", "b" * 64)
        self.assertEqual(idx.as_dict(), {"a.txt": "a" * 64, "b.txt": "b" * 64})


if __name__ == "__main__":
    unittest.main()
