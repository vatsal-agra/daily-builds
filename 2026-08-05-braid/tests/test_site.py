"""Tests for crdt/site.py — causal buffering through the *public*
`receive()` API (REVIEW.md #2's regression), undo/redo (including
grouped multi-char actions and interaction with concurrent remote
edits), and anti-entropy gossip bookkeeping."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crdt.site import Site


def sync(a, b):
    for op in a.op_log:
        b.receive(op)
    for op in b.op_log:
        a.receive(op)


class TestReceiveBuffersOutOfOrderOps(unittest.TestCase):
    """Regression for REVIEW.md #2: Site.receive()'s docstring promises
    buffering; earlier code silently dropped the op instead."""

    def test_receive_buffers_and_drains_via_public_api_only(self):
        a = Site("A")
        op1 = a.type_insert(0, "h")
        op2 = a.type_insert(1, "i")
        op3 = a.type_insert(2, "!")

        b = Site("B")
        b.receive(op3)  # depends on op2 -- not present yet
        b.receive(op1)  # no dependency -- applies immediately
        self.assertEqual(b.text(), "h")
        b.receive(op2)  # satisfies op3's dependency -- draining must pick op3 up too
        self.assertEqual(b.text(), "hi!")
        self.assertTrue(b.is_settled())

    def test_duplicate_and_out_of_order_mixed(self):
        a = Site("A")
        ops = [a.type_insert(i, ch) for i, ch in enumerate("abcde")]
        b = Site("B")
        order = [ops[2], ops[0], ops[2], ops[4], ops[1], ops[3], ops[0]]
        for op in order:
            b.receive(op)
        self.assertEqual(b.text(), "abcde")
        self.assertTrue(b.is_settled())


class TestUndoRedo(unittest.TestCase):
    def test_undo_redo_round_trip(self):
        a = Site("A")
        a.type_insert(0, "h")
        a.type_insert(1, "i")
        self.assertEqual(a.text(), "hi")
        a.undo()
        self.assertEqual(a.text(), "h")
        a.undo()
        self.assertEqual(a.text(), "")
        a.redo()
        self.assertEqual(a.text(), "h")
        a.redo()
        self.assertEqual(a.text(), "hi")

    def test_undo_on_empty_stack_is_none_not_an_error(self):
        a = Site("A")
        self.assertIsNone(a.undo())
        self.assertIsNone(a.redo())

    def test_new_local_edit_clears_redo_stack(self):
        a = Site("A")
        a.type_insert(0, "x")
        a.undo()
        self.assertTrue(a.can_redo())
        a.type_insert(0, "y")
        self.assertFalse(a.can_redo())

    def test_undo_survives_concurrent_remote_edit(self):
        """The headline undo/redo guarantee: undoing MY OWN edit always
        removes exactly that edit, never whatever the Nth character
        happens to be after someone else's edit landed in between."""
        a = Site("A")
        b = Site("B")
        a.type_insert(0, "h")
        a.type_insert(1, "i")
        sync(a, b)

        a.type_insert(2, "!")  # local only
        b.type_insert(1, "o")  # concurrent, local only, unseen by A

        a.undo()  # must remove exactly '!' -- A hasn't even seen B's edit
        self.assertNotIn("!", a.text())

        sync(a, b)
        self.assertEqual(a.text(), b.text())
        self.assertNotIn("!", a.text())
        self.assertIn("o", a.text())

    def test_grouped_paste_undoes_as_one_action(self):
        a = Site("A")
        a.type_text(0, "hello")
        self.assertEqual(a.text(), "hello")
        a.undo()
        self.assertEqual(a.text(), "")  # the whole paste, not one character
        a.redo()
        self.assertEqual(a.text(), "hello")

    def test_grouped_delete_range_undoes_as_one_action(self):
        a = Site("A")
        a.type_text(0, "hello world")
        a.type_delete_range(5, 6)  # remove " world"
        self.assertEqual(a.text(), "hello")
        a.undo()
        self.assertEqual(a.text(), "hello world")


class TestGossip(unittest.TestCase):
    def test_missing_ops_for_computes_the_right_delta(self):
        a = Site("A")
        a.type_insert(0, "x")
        a.type_insert(1, "y")
        b = Site("B")
        b.receive(a.op_log[0])
        missing = a.missing_ops_for(b.applied_ids)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["id"], a.op_log[1]["id"])


if __name__ == "__main__":
    unittest.main()
