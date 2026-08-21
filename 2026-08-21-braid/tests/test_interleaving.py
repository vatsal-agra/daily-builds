"""Keeps REVIEW.md #1's claim checked, not just asserted in prose: two
peers each typing a genuine contiguous run from a shared position
converge as clean, unsplit blocks; a narrower case (several independent
peers each anchoring inside an already-formed run) can still fragment it."""

import random
import unittest

from crdt.clock import CausalDeliveryBuffer
from crdt.rga import Node, RGA


def fork(name, seed_ops):
    r = RGA(name)
    buf = CausalDeliveryBuffer(r.has_id)
    for op in seed_ops:
        buf.submit(op, r.apply_remote)
    return r


class TestInterleaving(unittest.TestCase):
    def setUp(self):
        base = RGA("base")
        for ch in "ye":
            base.local_insert(len(base), ch)
        self.seed_ops = list(base.op_log)

    def test_two_peers_typing_contiguous_runs_do_not_interleave(self):
        peer1 = fork("peer1", self.seed_ops)
        peer2 = fork("peer2", self.seed_ops)
        for i, ch in enumerate("ABC"):
            peer1.local_insert(1 + i, ch)
        for i, ch in enumerate("XYZ"):
            peer2.local_insert(1 + i, ch)

        self.assertEqual(peer1.text(), "yABCe")
        self.assertEqual(peer2.text(), "yXYZe")

        results = set()
        all_ops = list(peer1.op_log) + list(peer2.op_log)
        for trial_seed in range(50):
            rng = random.Random(trial_seed)
            merged = fork(f"merged{trial_seed}", self.seed_ops)
            buf = CausalDeliveryBuffer(merged.has_id)
            ops = list(all_ops)
            rng.shuffle(ops)
            for op in ops:
                buf.submit(op, merged.apply_remote)
            results.add(merged.text())

        self.assertEqual(results, {"yXYZABCe"}, "runs should stay intact blocks, never interleaved")

    def test_independent_peers_anchoring_inside_a_run_can_fragment_it(self):
        peer1 = fork("peer1", self.seed_ops)
        for i, ch in enumerate("ABC"):
            peer1.local_insert(1 + i, ch)
        insert_ids = [op["id"] for op in peer1.op_log if op["type"] == "insert"][-3:]
        a_id, b_id, c_id = insert_ids

        def insert_after(name, after_id, value):
            r = fork(name, self.seed_ops)
            buf = CausalDeliveryBuffer(r.has_id)
            for op in peer1.op_log:
                buf.submit(op, r.apply_remote)
            node_id = (r.clock.tick(), r.peer_id)
            node = Node(node_id, value, after_id)
            r._integrate(node)
            op = {"type": "insert", "id": node_id, "parent": after_id, "value": value,
                  "deps": (after_id,) if after_id else ()}
            r._log(op)
            return op

        op_x = insert_after("peerX", a_id, "X")
        op_y = insert_after("peerY", b_id, "Y")
        op_z = insert_after("peerZ", c_id, "Z")

        all_ops = list(peer1.op_log) + [op_x, op_y, op_z]
        results = set()
        for trial in range(30):
            rng = random.Random(trial)
            m = fork(f"m{trial}", self.seed_ops)
            buf = CausalDeliveryBuffer(m.has_id)
            ops = list(all_ops)
            rng.shuffle(ops)
            for op in ops:
                buf.submit(op, m.apply_remote)
            results.add(m.text())

        self.assertEqual(results, {"yAXBYCZe"})
        self.assertNotIn("ABC", list(results)[0], "the narrow case really does fragment the run")


if __name__ == "__main__":
    unittest.main()
