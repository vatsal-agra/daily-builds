import random
import unittest

from engine.errors import ErrorValue
from engine.workbook import Workbook, a1_to_ref, ref_to_a1


def setc(wb, sheet, a1, text):
    r, c = a1_to_ref(a1)
    return wb.edit([(sheet, r, c, text)])


def getc(wb, sheet, a1):
    r, c = a1_to_ref(a1)
    return wb.sheets[sheet].get_computed(r, c)


class TestDependencyGraph(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.wb.add_sheet("S")

    def test_edit_propagates_to_dependents(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A2", "=A1+1")
        setc(self.wb, "S", "A3", "=A2+1")
        self.assertEqual(getc(self.wb, "S", "A3"), 3.0)
        setc(self.wb, "S", "A1", "10")
        self.assertEqual(getc(self.wb, "S", "A2"), 11.0)
        self.assertEqual(getc(self.wb, "S", "A3"), 12.0)

    def test_changing_formula_drops_old_edges(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "B1", "1")
        setc(self.wb, "S", "C1", "=A1")
        self.assertIn(("S", 0, 2), self.wb.dependents[("S", 0, 0)])
        setc(self.wb, "S", "C1", "=B1")
        self.assertNotIn(("S", 0, 2), self.wb.dependents.get(("S", 0, 0), set()))
        self.assertIn(("S", 0, 2), self.wb.dependents[("S", 0, 1)])
        setc(self.wb, "S", "A1", "999")
        self.assertEqual(getc(self.wb, "S", "C1"), 1.0)  # no longer depends on A1

    def test_self_cycle_marks_circ(self):
        setc(self.wb, "S", "A1", "=A1+1")
        self.assertEqual(getc(self.wb, "S", "A1"), ErrorValue("#CIRC!"))

    def test_mutual_cycle_marks_both(self):
        setc(self.wb, "S", "A1", "=B1+1")
        setc(self.wb, "S", "B1", "=A1+1")
        self.assertEqual(getc(self.wb, "S", "A1"), ErrorValue("#CIRC!"))
        self.assertEqual(getc(self.wb, "S", "B1"), ErrorValue("#CIRC!"))

    def test_breaking_a_cycle_recovers(self):
        setc(self.wb, "S", "A1", "=B1+1")
        setc(self.wb, "S", "B1", "=A1+1")
        setc(self.wb, "S", "B1", "5")
        self.assertEqual(getc(self.wb, "S", "A1"), 6.0)
        self.assertEqual(getc(self.wb, "S", "B1"), 5.0)

    def test_clearing_a_cell_updates_dependents(self):
        setc(self.wb, "S", "A1", "5")
        setc(self.wb, "S", "A2", "=A1*2")
        setc(self.wb, "S", "A1", "")
        self.assertEqual(getc(self.wb, "S", "A2"), 0.0)  # blank coerces to 0 in arithmetic

    def test_cross_sheet_reference(self):
        self.wb.add_sheet("T")
        setc(self.wb, "T", "A1", "42")
        setc(self.wb, "S", "A1", "=T!A1+1")
        self.assertEqual(getc(self.wb, "S", "A1"), 43.0)
        setc(self.wb, "T", "A1", "100")
        self.assertEqual(getc(self.wb, "S", "A1"), 101.0)


class TestUndoRedo(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.wb.add_sheet("S")

    def test_undo_redo_single_edit(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A1", "2")
        self.wb.undo()
        self.assertEqual(getc(self.wb, "S", "A1"), 1.0)
        self.wb.redo()
        self.assertEqual(getc(self.wb, "S", "A1"), 2.0)

    def test_undo_restores_dependents_too(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A2", "=A1*10")
        setc(self.wb, "S", "A1", "5")
        self.assertEqual(getc(self.wb, "S", "A2"), 50.0)
        self.wb.undo()
        self.assertEqual(getc(self.wb, "S", "A2"), 10.0)

    def test_undo_on_empty_history_returns_none(self):
        self.assertIsNone(self.wb.undo())

    def test_redo_cleared_by_new_edit(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A1", "2")
        self.wb.undo()
        setc(self.wb, "S", "A1", "3")
        self.assertIsNone(self.wb.redo())
        self.assertEqual(getc(self.wb, "S", "A1"), 3.0)

    def test_undo_of_clear_restores_cell(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A1", "")
        self.assertIsNone(getc(self.wb, "S", "A1"))
        self.wb.undo()
        self.assertEqual(getc(self.wb, "S", "A1"), 1.0)


class TestAutofill(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.wb.add_sheet("S")

    def test_relative_ref_shifts(self):
        setc(self.wb, "S", "B1", "=A1+1")
        raw = self.wb.autofill("S", *a1_to_ref("B1"), *a1_to_ref("B3"))
        self.assertEqual(raw, "=A3+1")

    def test_absolute_ref_pinned(self):
        setc(self.wb, "S", "B1", "=$A$1+1")
        raw = self.wb.autofill("S", *a1_to_ref("B1"), *a1_to_ref("D5"))
        self.assertEqual(raw, "=$A$1+1")

    def test_mixed_absolute_relative(self):
        setc(self.wb, "S", "B1", "=$A1+A$1")
        raw = self.wb.autofill("S", *a1_to_ref("B1"), *a1_to_ref("C2"))
        self.assertEqual(raw, "=$A2+B$1")

    def test_autofill_literal_copies_as_is(self):
        setc(self.wb, "S", "A1", "hello")
        raw = self.wb.autofill("S", *a1_to_ref("A1"), *a1_to_ref("A2"))
        self.assertEqual(raw, "hello")

    def test_autofill_applies_and_recalculates(self):
        setc(self.wb, "S", "A1", "1")
        setc(self.wb, "S", "A2", "2")
        setc(self.wb, "S", "B1", "=A1*10")
        raw = self.wb.autofill("S", *a1_to_ref("B1"), *a1_to_ref("B2"))
        self.wb.edit([("S", *a1_to_ref("B2"), raw)])
        self.assertEqual(getc(self.wb, "S", "B2"), 20.0)


class TestFullRecalcOracle(unittest.TestCase):
    """The incremental engine must always agree with a full from-scratch recompute."""

    def test_fuzzed_edit_sequences_match_full_recompute(self):
        random.seed(1234)
        for trial in range(30):
            wb = Workbook()
            wb.add_sheet("S")
            cells = [ref_to_a1(r, c) for r in range(6) for c in range(4)]
            for _ in range(60):
                target = random.choice(cells)
                kind = random.random()
                if kind < 0.4:
                    text = str(random.randint(-20, 20))
                elif kind < 0.7:
                    other = random.choice(cells)  # may equal target -- exercises self-cycles too
                    op = random.choice(["+", "-", "*"])
                    text = f"={other}{op}1"
                elif kind < 0.85:
                    text = f"=SUM({random.choice(cells)}:{random.choice(cells)})"
                else:
                    text = ""
                wb.edit([("S", *a1_to_ref(target), text)])

            incremental_snapshot = wb.snapshot_values()
            full = wb.full_recalculate()
            self.assertEqual(
                incremental_snapshot, full,
                f"trial {trial}: incremental recalculation diverged from full recompute",
            )

    def test_fuzz_never_crashes_and_cycles_stay_consistent(self):
        random.seed(99)
        for _ in range(20):
            wb = Workbook()
            wb.add_sheet("S")
            cells = [ref_to_a1(r, c) for r in range(4) for c in range(4)]
            for _ in range(40):
                target = random.choice(cells)
                other = random.choice(cells)
                text = random.choice([
                    str(random.randint(-9, 9)),
                    f"={other}+1",
                    f"=SUM({other}:{target})",
                    "",
                ])
                wb.edit([("S", *a1_to_ref(target), text)])
            # every cell that is part of a genuine cycle must be exactly #CIRC!,
            # and the graph must never hang (bounded loop above proves termination).
            snap = wb.snapshot_values()
            full = wb.full_recalculate()
            self.assertEqual(snap, full)


if __name__ == "__main__":
    unittest.main()
