import unittest

from crdt.clock import CausalDeliveryBuffer
from crdt.rga import RGA
from crdt.undo import UndoManager


class TestUndoManager(unittest.TestCase):
    def test_undo_insert_then_redo(self):
        doc = RGA("a")
        um = UndoManager(doc)
        for ch in "hi":
            um.record_local_op(doc.local_insert(len(doc), ch))
        self.assertEqual(doc.text(), "hi")
        um.undo()
        self.assertEqual(doc.text(), "h")
        um.redo()
        self.assertEqual(doc.text(), "hi")

    def test_undo_delete_restores_character(self):
        doc = RGA("a")
        um = UndoManager(doc)
        for ch in "abc":
            um.record_local_op(doc.local_insert(len(doc), ch))
        um.record_local_op(doc.local_delete(1))
        self.assertEqual(doc.text(), "ac")
        um.undo()
        self.assertEqual(doc.text(), "abc")

    def test_fresh_local_edit_clears_redo_stack(self):
        doc = RGA("a")
        um = UndoManager(doc)
        um.record_local_op(doc.local_insert(0, "x"))
        um.undo()
        self.assertTrue(um.can_redo())
        um.record_local_op(doc.local_insert(0, "y"))  # a fresh edit
        self.assertFalse(um.can_redo(), "a new edit should clear the redo stack")

    def test_undo_only_touches_own_ops_never_remote(self):
        a = RGA("a")
        b = RGA("b")
        um_a = UndoManager(a)
        op1 = a.local_insert(0, "A")
        um_a.record_local_op(op1)
        b.apply_remote(op1)

        # b concurrently inserts its own character
        op2 = b.local_insert(1, "B")
        a.apply_remote(op2)

        self.assertEqual(a.text(), "AB")
        um_a.undo()  # undo A's own insert -- must NOT touch B's remote insert
        self.assertEqual(a.text(), "B")

    def test_undo_composes_with_concurrent_remote_delete_of_same_char(self):
        """If someone else deletes the same character you're about to
        undo-restore, your undo must not blindly resurrect it against
        their concurrent, independent decision — this is exactly why
        undelete needs LWW semantics, not a bare flag flip."""
        a = RGA("a")
        b = RGA("b")
        buf_b = CausalDeliveryBuffer(b.has_id)
        op_insert = a.local_insert(0, "X")
        buf_b.submit(op_insert, b.apply_remote)

        um_a = UndoManager(a)
        op_delete_a = a.local_delete(0)  # a deletes it
        um_a.record_local_op(op_delete_a)
        buf_b.submit(op_delete_a, b.apply_remote)
        self.assertEqual(b.text(), "")

        # b ALSO independently deletes it around the same time (already
        # gone locally, so b's own local_delete isn't applicable -- model
        # the "someone else's delete raced and won" case directly: b's
        # delete op has a fresher id than a's undo will mint next only if
        # it truly arrives later in real Lamport-time; construct that by
        # having b's clock tick past a's before undoing
        b.clock.observe(1000)
        redo_like_delete_from_b = b._local_tombstone_op(op_insert["id"], True)

        # now a undoes its own delete (an "undelete" op with a levels-behind id)
        inverse_op = um_a.undo()
        self.assertIsNotNone(inverse_op)
        # deliver both peers' ops to each other and confirm convergence,
        # with B's fresher delete winning the LWW race
        buf_a = CausalDeliveryBuffer(a.has_id)
        buf_a.submit(redo_like_delete_from_b, a.apply_remote)
        buf_b.submit(inverse_op, b.apply_remote)
        self.assertEqual(a.text(), b.text())


if __name__ == "__main__":
    unittest.main()
