import unittest

from trellis import Workbook
from trellis.history import History


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.hist = History(self.wb)

    def test_undo_redo_basic(self):
        self.hist.set_cell("Sheet1", 1, 1, "1")
        self.hist.set_cell("Sheet1", 1, 1, "2")
        self.hist.set_cell("Sheet1", 1, 1, "3")
        self.assertEqual(self.wb.get_cell("Sheet1", 1, 1).value, 3)
        self.hist.undo()
        self.hist.undo()
        self.assertEqual(self.wb.get_cell("Sheet1", 1, 1).value, 1)
        self.hist.redo()
        self.assertEqual(self.wb.get_cell("Sheet1", 1, 1).value, 2)

    def test_undo_to_never_set_restores_blank(self):
        self.hist.set_cell("Sheet1", 1, 1, "5")
        self.hist.undo()
        self.assertIsNone(self.wb.get_cell("Sheet1", 1, 1).raw)

    def test_undo_restores_downstream_recalculation(self):
        self.hist.set_cell("Sheet1", 1, 1, "5")
        self.hist.set_cell("Sheet1", 1, 2, "=A1*10")
        self.hist.set_cell("Sheet1", 1, 1, "7")
        self.assertEqual(self.wb.get_cell("Sheet1", 1, 2).value, 70)
        self.hist.undo()
        self.assertEqual(self.wb.get_cell("Sheet1", 1, 2).value, 50)

    def test_new_edit_after_undo_clears_redo_stack(self):
        self.hist.set_cell("Sheet1", 1, 1, "1")
        self.hist.set_cell("Sheet1", 1, 1, "2")
        self.hist.undo()
        self.assertTrue(self.hist.can_redo())
        self.hist.set_cell("Sheet1", 1, 1, "99")
        self.assertFalse(self.hist.can_redo())

    def test_undo_with_empty_stack_returns_none(self):
        self.assertIsNone(self.hist.undo())

    def test_redo_with_empty_stack_returns_none(self):
        self.assertIsNone(self.hist.redo())

    def test_can_undo_can_redo_flags(self):
        self.assertFalse(self.hist.can_undo())
        self.hist.set_cell("Sheet1", 1, 1, "1")
        self.assertTrue(self.hist.can_undo())
        self.assertFalse(self.hist.can_redo())
        self.hist.undo()
        self.assertFalse(self.hist.can_undo())
        self.assertTrue(self.hist.can_redo())

    def test_clear(self):
        self.hist.set_cell("Sheet1", 1, 1, "1")
        self.hist.clear()
        self.assertFalse(self.hist.can_undo())
        self.assertFalse(self.hist.can_redo())


if __name__ == "__main__":
    unittest.main()
