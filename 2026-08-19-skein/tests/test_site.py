import unittest

from skein.site import Site


class TestSite(unittest.TestCase):
    def test_type_and_delete(self):
        s = Site("a")
        s.type_str(0, "hello")
        self.assertEqual(s.text, "hello")
        s.delete_at(0)
        self.assertEqual(s.text, "ello")

    def test_log_records_every_local_op(self):
        s = Site("a")
        s.type_str(0, "ab")
        s.delete_at(0)
        self.assertEqual(len(s.log), 3)

    def test_receive_applies_remote_op(self):
        a = Site("a")
        b = Site("b")
        op = a.type_at(0, "x")
        self.assertEqual(b.text, "")
        b.receive(op)
        self.assertEqual(b.text, "x")

    def test_has_pending_reflects_rga(self):
        a = Site("a")
        ops = a.type_str(0, "ab")
        b = Site("b")
        b.receive(ops[1])  # depends on ops[0], not yet delivered
        self.assertTrue(b.has_pending())
        b.receive(ops[0])
        self.assertFalse(b.has_pending())

    def test_undo_redo_roundtrip(self):
        s = Site("a")
        s.type_str(0, "hi")
        self.assertFalse(s.can_redo())
        self.assertTrue(s.can_undo())
        s.undo()
        self.assertEqual(s.text, "h")
        self.assertTrue(s.can_redo())
        s.redo()
        self.assertEqual(s.text, "hi")

    def test_undo_on_empty_history_returns_none(self):
        s = Site("a")
        self.assertIsNone(s.undo())
        self.assertIsNone(s.redo())


if __name__ == "__main__":
    unittest.main()
