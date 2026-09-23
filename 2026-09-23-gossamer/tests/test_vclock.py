import unittest

from gossamer.vclock import VectorClock, EQUAL, DESCENDS, ANCESTOR, CONCURRENT


class TestVectorClock(unittest.TestCase):
    def test_empty_equal(self):
        self.assertEqual(VectorClock().compare(VectorClock()), EQUAL)

    def test_increment_descends(self):
        a = VectorClock()
        b = a.increment("n1")
        self.assertEqual(b.compare(a), DESCENDS)
        self.assertEqual(a.compare(b), ANCESTOR)

    def test_self_equal(self):
        a = VectorClock({"n1": 2, "n2": 1})
        b = VectorClock({"n1": 2, "n2": 1})
        self.assertEqual(a.compare(b), EQUAL)

    def test_concurrent(self):
        a = VectorClock({"n1": 1})
        b = VectorClock({"n2": 1})
        self.assertEqual(a.compare(b), CONCURRENT)
        self.assertEqual(b.compare(a), CONCURRENT)

    def test_concurrent_after_divergence(self):
        base = VectorClock({"n1": 1, "n2": 1})
        a = base.increment("n1")   # {n1:2, n2:1}
        b = base.increment("n2")   # {n1:1, n2:2}
        self.assertEqual(a.compare(b), CONCURRENT)
        self.assertEqual(b.compare(a), CONCURRENT)

    def test_merge_takes_componentwise_max(self):
        a = VectorClock({"n1": 3, "n2": 1})
        b = VectorClock({"n1": 1, "n2": 4, "n3": 2})
        m = a.merge(b)
        self.assertEqual(m.to_dict(), {"n1": 3, "n2": 4, "n3": 2})

    def test_merge_then_increment_descends_both_parents(self):
        base = VectorClock({"n1": 1, "n2": 1})
        a = base.increment("n1")
        b = base.increment("n2")
        merged = a.merge(b).increment("n3")
        self.assertEqual(merged.compare(a), DESCENDS)
        self.assertEqual(merged.compare(b), DESCENDS)

    def test_merge_all(self):
        clocks = [VectorClock({"a": 1}), VectorClock({"b": 2}), VectorClock({"a": 3, "c": 1})]
        merged = VectorClock.merge_all(clocks)
        self.assertEqual(merged.to_dict(), {"a": 3, "b": 2, "c": 1})

    def test_roundtrip_dict(self):
        a = VectorClock({"n1": 5})
        self.assertEqual(VectorClock.from_dict(a.to_dict()).compare(a), EQUAL)

    def test_equality_and_hash(self):
        a = VectorClock({"n1": 1, "n2": 2})
        b = VectorClock({"n2": 2, "n1": 1})
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))


if __name__ == "__main__":
    unittest.main()
