import unittest

from skein.simulate import Simulation


class TestUndoRedo(unittest.TestCase):
    def test_undo_under_remote_interleaving_removes_only_the_local_op(self):
        """The whole point of undo.py: undo must remove *this site's*
        specific character, addressed by id, even when a remote edit
        landed at a position that would confuse a naive index-based
        undo."""
        sim = Simulation(["a", "b"], seed=1)
        sim.type_str("a", 0, "ab")  # a's own two edits: insert 'a', insert 'b'
        sim.drain()

        sim.type_at("b", 1, "X")  # b inserts between a's 'a' and 'b'
        sim.drain()
        self.assertEqual(sim.sites["a"].text, "aXb")

        sim.undo("a")  # undo a's *last local op*: inserting 'b' — not whatever sits at index 2 now
        sim.drain()

        self.assertTrue(sim.converged())
        self.assertEqual(sim.sites["a"].text, "aX")
        self.assertIn("X", sim.sites["a"].text, "the remote edit must survive a's undo")

    def test_redo_after_undo(self):
        sim = Simulation(["a", "b"], seed=2)
        sim.type_str("a", 0, "hi")
        sim.drain()
        sim.undo("a")
        sim.drain()
        self.assertEqual(sim.sites["a"].text, "h")
        sim.redo("a")
        sim.drain()
        self.assertEqual(sim.sites["a"].text, "hi")
        self.assertTrue(sim.converged())

    def test_fresh_edit_clears_redo_history(self):
        sim = Simulation(["a", "b"], seed=3)
        sim.type_str("a", 0, "hi")
        sim.drain()
        sim.undo("a")
        self.assertTrue(sim.sites["a"].can_redo())
        sim.type_at("a", 1, "X")  # a fresh edit
        self.assertFalse(sim.sites["a"].can_redo(), "a new edit must invalidate the old redo history")

    def test_undo_of_a_char_already_deleted_remotely_is_a_harmless_noop(self):
        sim = Simulation(["a", "b"], seed=4)
        sim.type_str("a", 0, "cat")
        sim.drain()
        sim.delete_at("b", 2)  # b deletes the 't' concurrently
        sim.undo("a")  # a undoes inserting the 't' — already gone
        sim.drain()
        self.assertTrue(sim.converged())
        self.assertEqual(sim.sites["a"].text, "ca")

    def test_undo_nothing_returns_none_and_sends_nothing(self):
        sim = Simulation(["a", "b"], seed=5)
        self.assertIsNone(sim.undo("a"))
        self.assertEqual(sim.all_ops, [])

    def test_multiple_undo_then_multiple_redo(self):
        sim = Simulation(["a"], seed=6)
        sim.type_str("a", 0, "abcd")
        for _ in range(3):
            sim.undo("a")
        self.assertEqual(sim.sites["a"].text, "a")
        for _ in range(3):
            sim.redo("a")
        self.assertEqual(sim.sites["a"].text, "abcd")


if __name__ == "__main__":
    unittest.main()
