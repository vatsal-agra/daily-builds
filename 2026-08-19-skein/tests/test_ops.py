import unittest

from skein.ids import CharId
from skein.ops import DeleteOp, InsertOp


class TestOps(unittest.TestCase):
    def test_insert_op_rejects_non_single_char(self):
        with self.assertRaises(ValueError):
            InsertOp(id=CharId(1, "a"), char="ab", origin=None)
        with self.assertRaises(ValueError):
            InsertOp(id=CharId(1, "a"), char="", origin=None)

    def test_insert_op_accepts_single_char(self):
        op = InsertOp(id=CharId(1, "a"), char="x", origin=None)
        self.assertEqual(op.char, "x")

    def test_ops_are_frozen_and_equal_by_value(self):
        op1 = InsertOp(id=CharId(1, "a"), char="x", origin=None)
        op2 = InsertOp(id=CharId(1, "a"), char="x", origin=None)
        self.assertEqual(op1, op2)
        with self.assertRaises(Exception):
            op1.char = "y"

    def test_delete_op_equality(self):
        self.assertEqual(DeleteOp(id=CharId(1, "a")), DeleteOp(id=CharId(1, "a")))
        self.assertNotEqual(DeleteOp(id=CharId(1, "a")), DeleteOp(id=CharId(2, "a")))


if __name__ == "__main__":
    unittest.main()
