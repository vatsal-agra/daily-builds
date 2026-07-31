import unittest

from trellis import Workbook
from trellis.csvio import import_csv, export_csv


class TestCsvImport(unittest.TestCase):
    def test_basic_import(self):
        wb = Workbook()
        n, skipped = import_csv(wb, "Sheet1", "a,b\n1,2\n")
        self.assertEqual((n, skipped), (4, 0))
        self.assertEqual(wb.get_cell("Sheet1", 1, 1).value, "a")
        self.assertEqual(wb.get_cell("Sheet1", 2, 2).value, 2)

    def test_import_with_formula(self):
        wb = Workbook()
        import_csv(wb, "Sheet1", "1,2,=A1+B1\n")
        self.assertEqual(wb.get_cell("Sheet1", 1, 3).value, 3)

    def test_empty_csv(self):
        wb = Workbook()
        n, skipped = import_csv(wb, "Sheet1", "")
        self.assertEqual((n, skipped), (0, 0))

    def test_quoted_comma_and_newline(self):
        wb = Workbook()
        text = 'Name,Note\n"Smith, John","Line1\nLine2"\n'
        import_csv(wb, "Sheet1", text)
        self.assertEqual(wb.get_cell("Sheet1", 2, 1).value, "Smith, John")
        self.assertEqual(wb.get_cell("Sheet1", 2, 2).value, "Line1\nLine2")

    def test_import_respects_max_bounds_and_reports_skipped(self):
        wb = Workbook()
        text = "\n".join(f"r{i},{i}" for i in range(1, 11))  # 10 rows, 2 cols = 20 cells
        n, skipped = import_csv(wb, "Sheet1", text, max_row=5, max_col=2)
        self.assertEqual(n, 10)  # rows 1-5, 2 cols each
        self.assertEqual(skipped, 10)  # rows 6-10
        self.assertIsNone(wb.get_cell("Sheet1", 6, 1))

    def test_import_respects_max_col(self):
        wb = Workbook()
        n, skipped = import_csv(wb, "Sheet1", "1,2,3,4\n", max_col=2)
        self.assertEqual(n, 2)
        self.assertEqual(skipped, 2)


class TestCsvExport(unittest.TestCase):
    def test_export_values_not_formulas(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "3")
        wb.set_cell("Sheet1", 1, 2, "4")
        wb.set_cell("Sheet1", 1, 3, "=A1*B1")
        out = export_csv(wb.sheets["Sheet1"])
        self.assertIn("12", out)
        self.assertNotIn("A1*B1", out)

    def test_export_empty_sheet(self):
        wb = Workbook()
        self.assertEqual(export_csv(wb.sheets["Sheet1"]), "")

    def test_round_trip(self):
        wb = Workbook()
        import_csv(wb, "Sheet1", "Item,Qty,Price,Total\nWidget,3,9.5,=B2*C2\n")
        out = export_csv(wb.sheets["Sheet1"])
        wb2 = Workbook()
        import_csv(wb2, "Sheet1", out)
        self.assertEqual(wb2.get_cell("Sheet1", 2, 4).value, 28.5)


if __name__ == "__main__":
    unittest.main()
