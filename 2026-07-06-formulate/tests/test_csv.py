import unittest

from engine import csvio
from engine.workbook import Workbook, a1_to_ref


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.wb.add_sheet("S")

    def setc(self, a1, text):
        r, c = a1_to_ref(a1)
        self.wb.edit([("S", r, c, text)])

    def test_export_reflects_computed_values_not_formulas(self):
        self.setc("A1", "2")
        self.setc("B1", "=A1*5")
        self.setc("A2", "hello, world")  # contains a comma -- must be quoted
        text = csvio.export_csv(self.wb.sheets["S"])
        lines = text.strip("\r\n").split("\r\n")
        self.assertEqual(lines[0], "2,10")
        self.assertIn('"hello, world"', lines[1])

    def test_import_creates_literal_edits(self):
        edits = csvio.parse_csv_to_edits("S", "1,2,3\n4,5,6\n")
        self.wb.edit(edits)
        self.assertEqual(self.wb.sheets["S"].get_computed(0, 0), 1.0)
        self.assertEqual(self.wb.sheets["S"].get_computed(1, 2), 6.0)

    def test_import_skips_empty_cells(self):
        edits = csvio.parse_csv_to_edits("S", "1,,3\n")
        refs = {(e[1], e[2]) for e in edits}
        self.assertNotIn((0, 1), refs)

    def test_import_at_offset(self):
        edits = csvio.parse_csv_to_edits("S", "9\n", start_row=2, start_col=3)
        self.assertEqual(edits, [("S", 2, 3, "9")])

    def test_round_trip_values(self):
        self.setc("A1", "3.5")
        self.setc("B1", "TRUE")
        self.setc("C1", "text")
        text = csvio.export_csv(self.wb.sheets["S"])
        wb2 = Workbook()
        wb2.add_sheet("S")
        wb2.edit(csvio.parse_csv_to_edits("S", text))
        self.assertEqual(wb2.sheets["S"].get_computed(0, 0), 3.5)
        self.assertEqual(wb2.sheets["S"].get_computed(0, 1), True)
        self.assertEqual(wb2.sheets["S"].get_computed(0, 2), "text")


if __name__ == "__main__":
    unittest.main()
