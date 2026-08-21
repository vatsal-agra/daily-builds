import random
import unittest

from crdt.rga import RGA
from crdt.clock import CausalDeliveryBuffer


def apply_causally(doc, ops, rng):
    buf = CausalDeliveryBuffer(doc.has_id)
    shuffled = list(ops)
    rng.shuffle(shuffled)
    for op in shuffled:
        buf.submit(op, doc.apply_remote)
    assert len(buf) == 0, f"{len(buf)} ops never became deliverable"
    return buf


class TestSinglePeer(unittest.TestCase):
    def test_basic_typing_and_deletion(self):
        doc = RGA("solo")
        for ch in "hello":
            doc.local_insert(len(doc), ch)
        self.assertEqual(doc.text(), "hello")
        doc.local_delete(0)
        self.assertEqual(doc.text(), "ello")
        doc.local_insert(0, "H")
        self.assertEqual(doc.text(), "Hello")

    def test_delete_out_of_range_raises(self):
        doc = RGA("solo")
        with self.assertRaises(IndexError):
            doc.local_delete(0)
        doc.local_insert(0, "x")
        with self.assertRaises(IndexError):
            doc.local_delete(5)

    def test_delete_by_id_unknown_raises(self):
        doc = RGA("solo")
        with self.assertRaises(KeyError):
            doc.local_delete_by_id((999, "ghost"))

    def test_undelete_restores_character(self):
        doc = RGA("solo")
        for ch in "abc":
            doc.local_insert(len(doc), ch)
        op = doc.local_delete(1)
        self.assertEqual(doc.text(), "ac")
        doc.local_undelete_by_id(op["id"])
        self.assertEqual(doc.text(), "abc")


class TestRemoteApplication(unittest.TestCase):
    def test_duplicate_insert_delivery_is_idempotent(self):
        a = RGA("a")
        op = a.local_insert(0, "x")
        b = RGA("b")
        b.apply_remote(op)
        b.apply_remote(op)  # duplicate delivery
        b.apply_remote(op)  # and again
        self.assertEqual(b.text(), "x")

    def test_delete_before_insert_defers_correctly(self):
        a = RGA("a")
        ins = a.local_insert(0, "x")
        dele = a.local_delete(0)
        b = RGA("b")
        # deliver delete BEFORE its target insert -- RGA must defer, not crash
        b.apply_remote(dele)
        self.assertEqual(b.text(), "")
        b.apply_remote(ins)
        self.assertEqual(b.text(), "")  # still deleted once the insert lands

    def test_unknown_op_type_raises(self):
        a = RGA("a")
        with self.assertRaises(ValueError):
            a.apply_remote({"type": "bogus", "id": (1, "a")})


class TestConvergence(unittest.TestCase):
    """Property-based: many random concurrent-editing scenarios must all
    converge to byte-identical text regardless of delivery order."""

    def _random_ops(self, doc, n, rng, alphabet="abcXYZ "):
        ops = []
        for _ in range(n):
            length = len(doc)
            if length == 0 or rng.random() < 0.7:
                ops.append(doc.local_insert(rng.randint(0, length), rng.choice(alphabet)))
            else:
                ops.append(doc.local_delete(rng.randint(0, length - 1)))
        return ops

    def test_concurrent_convergence_many_seeds(self):
        for seed in range(200):
            rng = random.Random(seed)
            peer_ids = [f"P{i}" for i in range(3)]
            all_ops = {}
            for p in peer_ids:
                local = RGA(p)
                all_ops[p] = self._random_ops(local, 25, rng)

            results = set()
            for _trial in range(10):
                doc = RGA("checker")
                streams = {p: list(all_ops[p]) for p in peer_ids}
                merged = []
                active = [p for p in peer_ids if streams[p]]
                while active:
                    p = rng.choice(active)
                    merged.append(streams[p].pop(0))
                    active = [p for p in peer_ids if streams[p]]
                for op in merged:
                    doc.apply_remote(op)
                results.add(doc.text())
            self.assertEqual(len(results), 1, f"seed {seed} diverged: {results}")

    def test_causal_chain_convergence_many_seeds(self):
        for seed in range(80):
            rng = random.Random(seed)
            peer_ids = [f"P{i}" for i in range(3)]
            docs = {p: RGA(p) for p in peer_ids}
            history = []
            for _round in range(4):
                round_ops = {}
                for p in peer_ids:
                    ops = self._random_ops(docs[p], 8, rng)
                    round_ops[p] = ops
                    history.extend(ops)
                for p in peer_ids:
                    others = [op for q in peer_ids if q != p for op in round_ops[q]]
                    apply_causally(docs[p], others, rng)
            for p in peer_ids:
                apply_causally(docs[p], history, rng)
            texts = {p: docs[p].text() for p in peer_ids}
            self.assertEqual(len(set(texts.values())), 1, f"seed {seed} diverged: {texts}")

            fresh = RGA("fresh")
            apply_causally(fresh, history, rng)
            self.assertEqual(fresh.text(), texts[peer_ids[0]], f"seed {seed}: fresh replay diverged")


if __name__ == "__main__":
    unittest.main()
