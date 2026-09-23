import unittest

from gossamer.store import LocalStore, reduce_siblings
from gossamer.vclock import VectorClock


class TestReduceSiblings(unittest.TestCase):
    def test_newer_replaces_older(self):
        v0 = VectorClock()
        v1 = v0.increment("n1")
        items = [("old", v0, 1.0), ("new", v1, 2.0)]
        reduced = reduce_siblings(items)
        self.assertEqual(len(reduced), 1)
        self.assertEqual(reduced[0][0], "new")

    def test_older_write_after_newer_is_dropped(self):
        v0 = VectorClock()
        v1 = v0.increment("n1")
        items = [("new", v1, 2.0), ("old", v0, 1.0)]
        reduced = reduce_siblings(items)
        self.assertEqual(len(reduced), 1)
        self.assertEqual(reduced[0][0], "new")

    def test_concurrent_writes_become_siblings(self):
        base = VectorClock({"n1": 1, "n2": 1})
        a = base.increment("n1")
        b = base.increment("n2")
        reduced = reduce_siblings([("a", a, 1.0), ("b", b, 2.0)])
        self.assertEqual({v for v, _, _ in reduced}, {"a", "b"})

    def test_resolving_write_collapses_siblings(self):
        base = VectorClock({"n1": 1, "n2": 1})
        a = base.increment("n1")
        b = base.increment("n2")
        resolved = a.merge(b).increment("n3")
        reduced = reduce_siblings([("a", a, 1.0), ("b", b, 2.0), ("resolved", resolved, 3.0)])
        self.assertEqual(len(reduced), 1)
        self.assertEqual(reduced[0][0], "resolved")


class TestLocalStore(unittest.TestCase):
    def test_put_and_get(self):
        store = LocalStore()
        vc = VectorClock().increment("n1")
        accepted, siblings = store.put("k", "v1", vc)
        self.assertTrue(accepted)
        self.assertEqual(len(store.get("k")), 1)
        self.assertEqual(store.get("k")[0][0], "v1")

    def test_stale_write_rejected(self):
        store = LocalStore()
        v0 = VectorClock()
        v1 = v0.increment("n1")
        store.put("k", "new", v1)
        accepted, siblings = store.put("k", "old", v0)
        self.assertFalse(accepted)
        self.assertEqual(len(store.get("k")), 1)
        self.assertEqual(store.get("k")[0][0], "new")

    def test_concurrent_write_creates_sibling(self):
        store = LocalStore()
        base = VectorClock({"n1": 1, "n2": 1})
        a = base.increment("n1")
        b = base.increment("n2")
        store.put("k", "a", a)
        accepted, siblings = store.put("k", "b", b)
        self.assertTrue(accepted)
        self.assertEqual(len(siblings), 2)

    def test_missing_key_returns_empty(self):
        store = LocalStore()
        self.assertEqual(store.get("nope"), [])

    def test_delete_key(self):
        store = LocalStore()
        store.put("k", "v", VectorClock().increment("n1"))
        store.delete_key("k")
        self.assertEqual(store.get("k"), [])

    def test_len_counts_keys_not_siblings(self):
        store = LocalStore()
        base = VectorClock({"n1": 1, "n2": 1})
        store.put("k", "a", base.increment("n1"))
        store.put("k", "b", base.increment("n2"))
        store.put("k2", "c", VectorClock().increment("n1"))
        self.assertEqual(len(store), 2)


if __name__ == "__main__":
    unittest.main()
