import unittest

from trellis import Workbook
from trellis.errors import TrellisError


def val(wb, sheet, row, col):
    cell = wb.get_cell(sheet, row, col)
    if cell is None:
        return None
    v = cell.value
    return v.code if isinstance(v, TrellisError) else v


class TestIncrementalRecalculation(unittest.TestCase):
    def test_unrelated_edit_triggers_zero_recomputation(self):
        wb = Workbook()
        for r in range(1, 501):
            wb.set_cell("Sheet1", r, 1, str(r))
        wb.set_cell("Sheet1", 1, 2, "=A1*10")
        before = wb.eval_count
        wb.set_cell("Sheet1", 250, 1, "999")
        self.assertEqual(wb.eval_count - before, 0)

    def test_related_edit_recomputes_exactly_its_dependents(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "1")
        wb.set_cell("Sheet1", 1, 2, "=A1*10")
        wb.set_cell("Sheet1", 1, 3, "=B1+1")
        before = wb.eval_count
        wb.set_cell("Sheet1", 1, 1, "5")
        self.assertEqual(wb.eval_count - before, 2)  # B1 and C1, not A1 itself
        self.assertEqual(val(wb, "Sheet1", 1, 2), 50)
        self.assertEqual(val(wb, "Sheet1", 1, 3), 51)

    def test_diamond_dependency_recomputes_each_cell_once(self):
        # D1 depends on both B1 and C1, which both depend on A1.
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "1")
        wb.set_cell("Sheet1", 1, 2, "=A1+1")
        wb.set_cell("Sheet1", 1, 3, "=A1+2")
        wb.set_cell("Sheet1", 1, 4, "=B1+C1")
        before = wb.eval_count
        wb.set_cell("Sheet1", 1, 1, "10")
        self.assertEqual(wb.eval_count - before, 3)  # B1, C1, D1 -- not double-counted
        self.assertEqual(val(wb, "Sheet1", 1, 4), 23)


class TestCircularReferences(unittest.TestCase):
    def test_direct_self_reference(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=A1+1")
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#CIRCULAR!")

    def test_multi_cell_cycle(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=A2+1")
        wb.set_cell("Sheet1", 2, 1, "=A3+1")
        wb.set_cell("Sheet1", 3, 1, "=A1+1")
        for r in (1, 2, 3):
            self.assertEqual(val(wb, "Sheet1", r, 1), "#CIRCULAR!")

    def test_downstream_of_cycle_propagates_without_crashing(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=A2+1")
        wb.set_cell("Sheet1", 2, 1, "=A1+1")
        wb.set_cell("Sheet1", 3, 1, "=A1+100")
        self.assertEqual(val(wb, "Sheet1", 3, 1), "#CIRCULAR!")

    def test_breaking_a_cycle_recovers(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=A2+1")
        wb.set_cell("Sheet1", 2, 1, "=A1+1")
        wb.set_cell("Sheet1", 3, 1, "=A1+100")
        wb.set_cell("Sheet1", 2, 1, "5")  # break the cycle
        self.assertEqual(val(wb, "Sheet1", 1, 1), 6)
        self.assertEqual(val(wb, "Sheet1", 2, 1), 5)
        self.assertEqual(val(wb, "Sheet1", 3, 1), 106)

    def test_range_self_reference_is_circular(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "1")
        wb.set_cell("Sheet1", 2, 1, "2")
        wb.set_cell("Sheet1", 3, 1, "=SUM(A1:A3)")  # includes itself
        self.assertEqual(val(wb, "Sheet1", 3, 1), "#CIRCULAR!")


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    def test_clearing_a_cell_makes_it_blank(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "5")
        wb.set_cell("Sheet1", 2, 1, "=A1+1")
        wb.set_cell("Sheet1", 1, 1, "")
        self.assertIsNone(wb.get_cell("Sheet1", 1, 1).raw)
        self.assertEqual(val(wb, "Sheet1", 2, 1), 1)  # blank reads as 0

    def test_malformed_formula_is_value_error_not_crash(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=1+")
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#VALUE!")

    def test_deep_paren_formula_is_value_error_not_crash(self):
        wb = Workbook()
        formula = "=" + "(" * 500 + "1" + ")" * 500
        wb.set_cell("Sheet1", 1, 1, formula)  # must not raise RecursionError
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#VALUE!")

    def test_long_flat_chain_is_value_error_not_crash(self):
        wb = Workbook()
        formula = "=" + "+".join(["1"] * 3000)
        wb.set_cell("Sheet1", 1, 1, formula)  # must not raise RecursionError
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#VALUE!")

    def test_reasonable_formula_still_works_after_recursion_guard(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=" + "+".join(["1"] * 40))
        self.assertEqual(val(wb, "Sheet1", 1, 1), 40)


class TestMultiSheet(unittest.TestCase):
    def test_cross_sheet_reference(self):
        wb = Workbook()
        wb.add_sheet("Data")
        wb.set_cell("Data", 1, 1, "42")
        wb.set_cell("Sheet1", 1, 1, "=Data!A1*2")
        self.assertEqual(val(wb, "Sheet1", 1, 1), 84)

    def test_cross_sheet_dependency_recalculates(self):
        wb = Workbook()
        wb.add_sheet("Data")
        wb.set_cell("Data", 1, 1, "10")
        wb.set_cell("Sheet1", 1, 1, "=Data!A1*2")
        wb.set_cell("Data", 1, 1, "20")
        self.assertEqual(val(wb, "Sheet1", 1, 1), 40)

    def test_reference_to_missing_sheet_is_ref_error(self):
        wb = Workbook()
        wb.set_cell("Sheet1", 1, 1, "=NoSuchSheet!A1")
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#REF!")

    def test_rename_sheet_preserves_cross_sheet_formulas(self):
        wb = Workbook()
        wb.add_sheet("Data")
        wb.set_cell("Data", 1, 1, "10")
        wb.set_cell("Sheet1", 1, 1, "=Data!A1*2")
        wb.rename_sheet("Data", "Source")
        self.assertEqual(val(wb, "Sheet1", 1, 1), 20)
        self.assertIn("Source!A1", wb.get_cell("Sheet1", 1, 1).raw)
        wb.set_cell("Source", 1, 1, "100")
        self.assertEqual(val(wb, "Sheet1", 1, 1), 200)

    def test_rename_rejects_bang_in_name(self):
        wb = Workbook()
        with self.assertRaises(ValueError):
            wb.rename_sheet("Sheet1", "Bad!Name")

    def test_remove_sheet_breaks_references_as_ref_error(self):
        wb = Workbook()
        wb.add_sheet("Data")
        wb.set_cell("Data", 1, 1, "10")
        wb.set_cell("Sheet1", 1, 1, "=Data!A1*2")
        wb.remove_sheet("Data")
        self.assertEqual(val(wb, "Sheet1", 1, 1), "#REF!")

    def test_cannot_remove_last_sheet(self):
        wb = Workbook()
        with self.assertRaises(ValueError):
            wb.remove_sheet("Sheet1")

    def test_add_sheet_rejects_bang(self):
        wb = Workbook()
        with self.assertRaises(ValueError):
            wb.add_sheet("Bad!Sheet")

    def test_add_sheet_rejects_duplicate(self):
        wb = Workbook()
        wb.add_sheet("Data")
        with self.assertRaises(ValueError):
            wb.add_sheet("Data")


if __name__ == "__main__":
    unittest.main()
