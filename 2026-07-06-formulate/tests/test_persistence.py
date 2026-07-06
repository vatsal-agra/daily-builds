import unittest

from engine import persistence
from engine.workbook import Workbook, a1_to_ref


class TestPersistence(unittest.TestCase):
    def build(self):
        wb = Workbook()
        wb.add_sheet("Sheet1")
        wb.add_sheet("Sheet2")

        def setc(sheet, a1, text):
            r, c = a1_to_ref(a1)
            wb.edit([(sheet, r, c, text)])

        setc("Sheet1", "A1", "5")
        setc("Sheet1", "A2", "=A1*2")
        setc("Sheet1", "B1", "hello")
        setc("Sheet2", "A1", "=Sheet1!A2+1")
        return wb

    def test_round_trip_preserves_formulas_and_recomputes(self):
        wb = self.build()
        text = persistence.to_json(wb)
        wb2 = persistence.from_json(text)

        self.assertEqual(wb2.sheet_order, ["Sheet1", "Sheet2"])
        self.assertEqual(wb2.sheets["Sheet1"].get_raw(*a1_to_ref("A2")), "=A1*2")
        self.assertEqual(wb2.sheets["Sheet1"].get_computed(*a1_to_ref("A2")), 10.0)
        self.assertEqual(wb2.sheets["Sheet2"].get_computed(*a1_to_ref("A1")), 11.0)

    def test_loaded_workbook_reacts_to_new_edits(self):
        wb = self.build()
        wb2 = persistence.from_json(persistence.to_json(wb))
        wb2.edit([("Sheet1", *a1_to_ref("A1"), "100")])
        self.assertEqual(wb2.sheets["Sheet1"].get_computed(*a1_to_ref("A2")), 200.0)
        self.assertEqual(wb2.sheets["Sheet2"].get_computed(*a1_to_ref("A1")), 201.0)

    def test_forward_reference_order_independent(self):
        # A2 references B2 which is defined *later* in iteration order; a naive
        # one-cell-at-a-time loader could compute A2 before B2 exists.
        # A1 (row0,col0) depends on B1 (row0,col1), which appears later in the dict.
        data = {"sheet_order": ["S"], "sheets": {"S": {"0,0": "=B1+1", "0,1": "9"}}}
        wb2 = persistence.from_dict(data)
        self.assertEqual(wb2.sheets["S"].get_computed(0, 0), 10.0)


if __name__ == "__main__":
    unittest.main()
