import random
import unittest

from crdt.counter import PNCounter
from crdt.document import Document
from crdt.orset import ORSet


class TestPNCounter(unittest.TestCase):
    def test_increment_decrement_and_merge(self):
        a = PNCounter("a")
        b = PNCounter("b")
        a.increment(5)
        b.increment(2)
        b.decrement(1)
        a.merge(b.state())
        b.merge(a.state())
        self.assertEqual(a.value(), 6)
        self.assertEqual(b.value(), 6)

    def test_merge_is_idempotent(self):
        a = PNCounter("a")
        a.increment(3)
        b = PNCounter("b")
        b.merge(a.state())
        b.merge(a.state())
        b.merge(a.state())
        self.assertEqual(b.value(), 3)

    def test_rejects_negative_amounts(self):
        c = PNCounter("a")
        with self.assertRaises(ValueError):
            c.increment(-1)
        with self.assertRaises(ValueError):
            c.decrement(-1)


class TestORSet(unittest.TestCase):
    def test_add_wins_over_concurrent_remove(self):
        a = ORSet("A")
        b = ORSet("B")
        a.add("urgent")
        b.merge(a.state())
        self.assertTrue(b.contains("urgent"))

        b.remove("urgent")       # removes the tag B has observed
        a.add("urgent")          # A concurrently mints a FRESH tag, unaware of B's remove

        a.merge(b.state())
        b.merge(a.state())
        self.assertTrue(a.contains("urgent"), "concurrent add should survive the old tag's removal")
        self.assertTrue(b.contains("urgent"))

    def test_uncontested_remove_actually_removes(self):
        c = ORSet("C")
        c.add("x")
        c.remove("x")
        self.assertFalse(c.contains("x"))


class TestDocument(unittest.TestCase):
    def _make_peer(self, peer_id):
        doc = Document(peer_id)
        doc.add_register("title")
        doc.add_counter("views")
        doc.add_set("tags")
        doc.add_text("body")
        return doc

    def test_mixed_field_types_converge(self):
        rng = random.Random(0)

        def random_ops(doc, n):
            for _ in range(n):
                choice = rng.random()
                if choice < 0.25:
                    doc.field("title").set(rng.choice(["Draft", "Final", "v2"]))
                elif choice < 0.5:
                    if rng.random() < 0.7:
                        doc.field("views").increment(rng.randint(1, 5))
                    else:
                        doc.field("views").decrement(rng.randint(1, 2))
                elif choice < 0.75:
                    s = doc.field("tags")
                    (s.add if rng.random() < 0.7 else s.remove)(rng.choice(["urgent", "draft", "reviewed"]))
                else:
                    t = doc.field("body")
                    n_ = len(t)
                    if n_ == 0 or rng.random() < 0.7:
                        t.local_insert(rng.randint(0, n_), rng.choice("abcXYZ "))
                    else:
                        t.local_delete(rng.randint(0, n_ - 1))

        for seed in range(50):
            rng.seed(seed)
            peers = [self._make_peer(f"P{i}") for i in range(4)]
            for p in peers:
                random_ops(p, 20)
            for _round in range(6):
                order = list(range(4))
                rng.shuffle(order)
                for i in order:
                    j = (i + 1) % 4
                    peers[i].merge(peers[j].state())
                    peers[j].merge(peers[i].state())
            snapshots = [p.snapshot() for p in peers]
            self.assertTrue(all(s == snapshots[0] for s in snapshots), f"seed {seed} diverged: {snapshots}")

    def test_schema_conflict_raises(self):
        a = Document("a")
        a.add_text("field1")
        b = Document("b")
        b.add_counter("field1")
        with self.assertRaises(TypeError):
            a.merge(b.state())

    def test_field_created_concurrently_gets_picked_up_by_merge(self):
        a = Document("a")
        b = Document("b")
        b.add_text("notes")
        b.field("notes").local_insert(0, "hi")
        a.merge(b.state())
        self.assertEqual(a.snapshot()["notes"], "hi")


if __name__ == "__main__":
    unittest.main()
