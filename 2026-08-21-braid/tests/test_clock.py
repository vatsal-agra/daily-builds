import unittest

from crdt.clock import CausalDeliveryBuffer, LamportClock, VectorClock


class TestLamportClock(unittest.TestCase):
    def test_tick_increments(self):
        c = LamportClock("p")
        self.assertEqual(c.tick(), 1)
        self.assertEqual(c.tick(), 2)

    def test_observe_advances_past_remote(self):
        c = LamportClock("p")
        c.tick()  # 1
        c.observe(10)
        self.assertEqual(c.counter, 10)
        self.assertEqual(c.tick(), 11)

    def test_observe_does_not_rewind(self):
        c = LamportClock("p")
        c.observe(10)
        c.observe(3)
        self.assertEqual(c.counter, 10)


class TestVectorClock(unittest.TestCase):
    def test_merge_and_leq(self):
        a = VectorClock()
        a.increment("x")
        b = VectorClock()
        b.increment("x")
        b.increment("y")
        self.assertTrue(a.leq(b))
        self.assertFalse(b.leq(a))

    def test_concurrent(self):
        a = VectorClock()
        a.increment("x")
        b = VectorClock()
        b.increment("y")
        self.assertTrue(a.concurrent_with(b))
        self.assertTrue(b.concurrent_with(a))

    def test_merge_takes_max(self):
        a = VectorClock()
        a.observe("x", 5)
        b = VectorClock()
        b.observe("x", 2)
        b.observe("y", 9)
        a.merge(b)
        self.assertEqual(a.get("x"), 5)
        self.assertEqual(a.get("y"), 9)


class TestCausalDeliveryBuffer(unittest.TestCase):
    def test_releases_in_dependency_order_regardless_of_arrival_order(self):
        applied = []
        known = set()
        buf = CausalDeliveryBuffer(lambda i: i is None or i in known)

        def apply_fn(op):
            applied.append(op["id"])
            known.add(op["id"])

        op_c = {"id": "c", "deps": ("b",)}
        op_b = {"id": "b", "deps": ("a",)}
        op_a = {"id": "a", "deps": ()}

        # deliver in reverse dependency order
        buf.submit(op_c, apply_fn)
        self.assertEqual(applied, [])  # nothing deliverable yet
        buf.submit(op_b, apply_fn)
        self.assertEqual(applied, [])
        buf.submit(op_a, apply_fn)
        # a's arrival should cascade-release b then c in one call
        self.assertEqual(applied, ["a", "b", "c"])
        self.assertEqual(len(buf), 0)

    def test_stays_pending_forever_if_dependency_never_arrives(self):
        buf = CausalDeliveryBuffer(lambda i: False)
        buf.submit({"id": "x", "deps": ("missing",)}, lambda op: None)
        self.assertEqual(len(buf), 1)


if __name__ == "__main__":
    unittest.main()
