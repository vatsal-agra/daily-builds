"""Unit tests for the core RGA engine (crdt/rga.py) — single-replica
behavior, edge cases, and basic two-replica merges. Multi-seed
convergence proofs live in test_network_convergence.py; this file is
about the engine's documented contract in isolation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crdt.rga import RGADocument


class TestSingleReplica(unittest.TestCase):
    def test_sequential_insert(self):
        d = RGADocument("A")
        for i, ch in enumerate("hello"):
            d.local_insert(i, ch)
        self.assertEqual(d.to_string(), "hello")

    def test_insert_in_middle(self):
        d = RGADocument("A")
        d.local_insert(0, "h")
        d.local_insert(1, "o")
        d.local_insert(1, "e")  # h_o -> heo? insert 'e' between h and o
        self.assertEqual(d.to_string(), "heo")

    def test_delete(self):
        d = RGADocument("A")
        for i, ch in enumerate("hello"):
            d.local_insert(i, ch)
        d.local_delete(0)
        self.assertEqual(d.to_string(), "ello")
        d.local_delete(3)
        self.assertEqual(d.to_string(), "ell")

    def test_delete_then_insert_reuses_position(self):
        d = RGADocument("A")
        for i, ch in enumerate("abc"):
            d.local_insert(i, ch)
        d.local_delete(1)  # remove 'b' -> "ac"
        d.local_insert(1, "X")
        self.assertEqual(d.to_string(), "aXc")

    def test_empty_document(self):
        d = RGADocument("A")
        self.assertEqual(d.to_string(), "")
        self.assertEqual(d.visible_length(), 0)

    def test_insert_out_of_range_raises(self):
        d = RGADocument("A")
        with self.assertRaises(IndexError):
            d.local_insert(1, "x")  # doc is empty, only index 0 valid

    def test_delete_out_of_range_raises(self):
        d = RGADocument("A")
        d.local_insert(0, "x")
        with self.assertRaises(IndexError):
            d.local_delete(5)

    def test_multi_char_insert_rejected(self):
        d = RGADocument("A")
        with self.assertRaises(ValueError):
            d.local_insert(0, "ab")

    def test_tombstones_persist_in_by_id(self):
        d = RGADocument("A")
        d.local_insert(0, "x")
        node_id = d.sequence[0]["id"]
        d.local_delete(0)
        self.assertIn(node_id, d.by_id)
        self.assertTrue(d.by_id[node_id]["deleted"])


class TestUndoRedoAtEngineLevel(unittest.TestCase):
    """undo/redo live on Site (see test_site.py) but their primitives
    (delete_by_id/restore_by_id) are engine-level and get their own
    dedicated coverage for the id-separation bug (REVIEW.md #1)."""

    def test_delete_by_id_uses_a_fresh_op_id_not_the_targets(self):
        d = RGADocument("A")
        op_insert = d.local_insert(0, "x")
        op_delete = d.delete_by_id(tuple(op_insert["id"]))
        self.assertNotEqual(op_delete["id"], op_insert["id"])
        self.assertEqual(op_delete["target"], op_insert["id"])

    def test_delete_then_restore_then_delete_again(self):
        d = RGADocument("A")
        op_insert = d.local_insert(0, "x")
        node_id = tuple(op_insert["id"])
        first_delete = d.delete_by_id(node_id)
        self.assertEqual(d.to_string(), "")
        d.restore_by_id(node_id)
        self.assertEqual(d.to_string(), "x")
        second_delete = d.delete_by_id(node_id)
        self.assertEqual(d.to_string(), "")
        # both target the same node, but as *distinct* op identities —
        # this is exactly the separation REVIEW.md bug #1 required
        self.assertEqual(first_delete["target"], second_delete["target"])
        self.assertNotEqual(first_delete["id"], second_delete["id"])


class TestTwoReplicaMerge(unittest.TestCase):
    def test_concurrent_inserts_after_same_origin_converge(self):
        a = RGADocument("A")
        b = RGADocument("B")
        op0 = a.local_insert(0, "x")
        b.apply_remote_op(op0)
        op_a = a.local_insert(1, "y")
        op_b = b.local_insert(1, "z")
        a.apply_remote_op(op_b)
        b.apply_remote_op(op_a)
        self.assertEqual(a.to_string(), b.to_string())
        self.assertEqual(set(a.to_string()), {"x", "y", "z"})

    def test_out_of_order_delivery_buffers_then_applies(self):
        a = RGADocument("A")
        ops = [a.local_insert(i, ch) for i, ch in enumerate("abc")]
        b = RGADocument("B")
        # deliver in reverse order: c's origin (b) and b's origin (a)
        # aren't there yet when 'c' arrives
        self.assertFalse(b.apply_remote_op(ops[2]))  # c depends on b -- buffered by caller
        self.assertFalse(b.apply_remote_op(ops[1]))  # b depends on a -- buffered by caller
        self.assertTrue(b.apply_remote_op(ops[0]))  # a has no dependency
        self.assertTrue(b.apply_remote_op(ops[1]))  # now b's dependency (a) exists
        self.assertTrue(b.apply_remote_op(ops[2]))  # now c's dependency (b) exists
        self.assertEqual(b.to_string(), "abc")

    def test_duplicate_delivery_is_idempotent(self):
        a = RGADocument("A")
        op = a.local_insert(0, "x")
        b = RGADocument("B")
        self.assertTrue(b.apply_remote_op(op))
        self.assertTrue(b.apply_remote_op(op))  # duplicate -- must not double-insert
        self.assertEqual(b.to_string(), "x")
        self.assertEqual(len(b.sequence), 1)

    def test_sequential_non_concurrent_insert_lands_where_expected(self):
        """Regression for REVIEW.md #3 (Lamport clocks): a fully-synced
        replica inserting into already-known content must land exactly
        where the user asked, never displaced by an unrelated tie-break
        against a node it already knew about."""
        a = RGADocument("A")
        for i, ch in enumerate("hab"):
            a.local_insert(i, ch)
        b = RGADocument("B")
        for node in a.sequence:
            op = {"type": "insert", "id": list(node["id"]),
                  "origin": list(node["origin"]) if node["origin"] else None,
                  "value": node["value"]}
            b.apply_remote_op(op)
        self.assertEqual(b.to_string(), "hab")
        b.local_insert(1, "X")  # click right after "h", type "X"
        self.assertEqual(b.to_string(), "hXab")

    def test_delete_and_restore_ops_round_trip_across_replicas(self):
        a = RGADocument("A")
        op1 = a.local_insert(0, "x")
        b = RGADocument("B")
        b.apply_remote_op(op1)
        del_op = a.delete_by_id(tuple(op1["id"]))
        self.assertTrue(b.apply_remote_op(del_op))
        self.assertEqual(b.to_string(), "")
        restore_op = a.restore_by_id(tuple(op1["id"]))
        self.assertTrue(b.apply_remote_op(restore_op))
        self.assertEqual(b.to_string(), "x")


if __name__ == "__main__":
    unittest.main()
