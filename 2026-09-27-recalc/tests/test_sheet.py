import random
import unittest

from engine import refs
from engine import values as V
from engine.sheet import Sheet


def A(addr):
    r = refs.parse_cell_ref(addr)
    return (r.col, r.row)


class TestDependencyRecalc(unittest.TestCase):
    def test_edit_propagates_to_dependents(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("B1"), "=A1*2")
        s.set_cell(*A("C1"), "=B1+1")
        self.assertEqual(s.get_display(*A("C1")), "3")
        s.set_cell(*A("A1"), "10")
        self.assertEqual(s.get_display(*A("B1")), "20")
        self.assertEqual(s.get_display(*A("C1")), "21")

    def test_changed_cells_reported(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("B1"), "=A1*2")
        s.set_cell(*A("C1"), "=999")  # unrelated cell
        changed = s.set_cell(*A("A1"), "5")
        self.assertIn(A("A1"), changed)
        self.assertIn(A("B1"), changed)
        self.assertNotIn(A("C1"), changed)

    def test_no_spurious_change_when_value_unchanged(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("B1"), "=IF(A1>0,1,1)")  # always 1 regardless
        changed = s.set_cell(*A("A1"), "2")
        self.assertIn(A("A1"), changed)
        self.assertNotIn(A("B1"), changed)  # B1's display didn't change

    def test_direct_self_cycle(self):
        s = Sheet()
        s.set_cell(*A("A1"), "=A1+1")
        self.assertEqual(s.get_display(*A("A1")), "#CYCLE!")

    def test_indirect_cycle(self):
        s = Sheet()
        s.set_cell(*A("A1"), "=B1+1")
        s.set_cell(*A("B1"), "=C1+1")
        s.set_cell(*A("C1"), "=A1+1")
        for addr in ("A1", "B1", "C1"):
            self.assertEqual(s.get_display(*A(addr)), "#CYCLE!")

    def test_cycle_broken_recovers(self):
        s = Sheet()
        s.set_cell(*A("A1"), "=B1+1")
        s.set_cell(*A("B1"), "=A1+1")
        self.assertEqual(s.get_display(*A("A1")), "#CYCLE!")
        s.set_cell(*A("B1"), "5")
        self.assertEqual(s.get_display(*A("A1")), "6")
        self.assertEqual(s.get_display(*A("B1")), "5")

    def test_diamond_dependency(self):
        s = Sheet()
        s.set_cell(*A("A1"), "2")
        s.set_cell(*A("B1"), "=A1*2")
        s.set_cell(*A("C1"), "=A1*3")
        s.set_cell(*A("D1"), "=B1+C1")
        self.assertEqual(s.get_display(*A("D1")), "10")
        s.set_cell(*A("A1"), "5")
        self.assertEqual(s.get_display(*A("D1")), "25")

    def test_leading_apostrophe_forces_text(self):
        s = Sheet()
        s.set_cell(*A("A1"), "'5")
        s.set_cell(*A("A2"), "'TRUE")
        s.set_cell(*A("B1"), "=A1+1")  # text "5" still coerces for arithmetic
        self.assertEqual(s.get_display(*A("A1")), "5")
        self.assertEqual(s.get_display(*A("A2")), "TRUE")
        self.assertEqual(s.get_display(*A("B1")), "6")

    def test_clearing_a_precedent_is_blank_not_crash(self):
        s = Sheet()
        s.set_cell(*A("A1"), "5")
        s.set_cell(*A("B1"), "=A1+1")
        s.set_cell(*A("A1"), "")
        self.assertEqual(s.get_display(*A("B1")), "1")  # blank coerces to 0


class TestCopyPasteFill(unittest.TestCase):
    def test_copy_paste_translates_relative_refs(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("A2"), "2")
        s.set_cell(*A("B1"), "=A1*10")
        s.copy_paste(A("B1"), A("B1"), A("B2"))
        self.assertEqual(s.get_raw(*A("B2")), "=A2*10")
        self.assertEqual(s.get_display(*A("B2")), "20")

    def test_copy_paste_respects_absolute_lock(self):
        s = Sheet()
        s.set_cell(*A("A1"), "100")
        s.set_cell(*A("B1"), "=$A$1+1")
        s.copy_paste(A("B1"), A("B1"), A("C5"))
        self.assertEqual(s.get_raw(*A("C5")), "=$A$1+1")
        self.assertEqual(s.get_display(*A("C5")), "101")

    def test_copy_paste_block(self):
        s = Sheet()
        for addr, v in [("A1", "1"), ("A2", "2"), ("B1", "10"), ("B2", "20")]:
            s.set_cell(*A(addr), v)
        s.set_cell(*A("C1"), "=A1+B1")
        s.set_cell(*A("C2"), "=A2+B2")
        s.copy_paste(A("C1"), A("C2"), A("D1"))
        self.assertEqual(s.get_raw(*A("D1")), "=B1+C1")
        self.assertEqual(s.get_raw(*A("D2")), "=B2+C2")
        # D1 = B1 + C1 = 10 + (A1+B1=11) = 21; not a copy of C1's value,
        # since the paste shifted the reference onto a live formula cell.
        self.assertEqual(s.get_display(*A("D1")), "21")
        self.assertEqual(s.get_display(*A("D2")), "42")

    def test_paste_off_grid_is_ref_error(self):
        s = Sheet()
        s.set_cell(*A("B2"), "=A1+1")
        s.copy_paste(A("B2"), A("B2"), A("A1"))  # shifts left by one column -> A1's A ref goes to col 0
        self.assertEqual(s.get_display(*A("A1")), "#REF!")

    def test_fill_down(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("A2"), "2")
        s.set_cell(*A("A3"), "3")
        s.set_cell(*A("B1"), "=A1*10")
        s.fill(*A("B1"), A("B1"), A("B3"))
        self.assertEqual(s.get_display(*A("B2")), "20")
        self.assertEqual(s.get_display(*A("B3")), "30")


class TestUndoRedo(unittest.TestCase):
    def test_undo_redo_single_edit(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("A1"), "2")
        self.assertEqual(s.get_display(*A("A1")), "2")
        s.undo()
        self.assertEqual(s.get_display(*A("A1")), "1")
        s.redo()
        self.assertEqual(s.get_display(*A("A1")), "2")

    def test_undo_recomputes_dependents(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("B1"), "=A1*2")
        s.set_cell(*A("A1"), "5")
        self.assertEqual(s.get_display(*A("B1")), "10")
        s.undo()
        self.assertEqual(s.get_display(*A("B1")), "2")

    def test_undo_paste_is_one_transaction(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("A2"), "1")
        s.set_cell(*A("A3"), "1")
        s.set_cell(*A("B1"), "=A1*10")
        s.copy_paste(A("B1"), A("B1"), A("B2"))
        s.copy_paste(A("B1"), A("B1"), A("B3"))
        self.assertEqual(s.get_display(*A("B3")), "10")
        s.undo()  # undoes only the B3 paste
        self.assertEqual(s.get_raw(*A("B3")), "")
        self.assertEqual(s.get_display(*A("B2")), "10")  # untouched

    def test_redo_cleared_by_new_edit(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("A1"), "2")
        s.undo()
        s.set_cell(*A("A1"), "3")
        self.assertFalse(s.can_redo())


class TestFullVsIncrementalOracle(unittest.TestCase):
    """The load-bearing invariant: after any sequence of random edits, the
    incrementally-maintained cell values must exactly equal what a full
    from-scratch recompute (Kahn's algorithm over every cell) produces.
    """

    def _snapshot(self, sheet):
        return {k: sheet.get_display(*k) for k in sheet.cells}

    def test_random_edit_fuzz_matches_full_recompute(self):
        rng = random.Random(1234)
        cols = list(range(1, 6))
        rows = list(range(1, 6))
        addrs = [(c, r) for c in cols for r in rows]

        def random_formula():
            kind = rng.random()
            if kind < 0.4:
                return str(rng.randint(-10, 10))
            c, r = rng.choice(addrs)
            other = rng.choice(addrs)
            op = rng.choice(["+", "-", "*"])
            return f"={refs.col_to_letters(c)}{r}{op}{refs.col_to_letters(other[0])}{other[1]}"

        s = Sheet()
        for _ in range(400):
            addr = rng.choice(addrs)
            raw = random_formula()
            s.set_cell(addr[0], addr[1], raw)

            incremental = self._snapshot(s)
            s.recompute_all()
            full = self._snapshot(s)
            self.assertEqual(
                incremental, full,
                f"incremental/full mismatch after setting {addr} = {raw!r}",
            )

    def test_random_edit_fuzz_with_clears_and_functions(self):
        rng = random.Random(99)
        addrs = [(c, r) for c in range(1, 5) for r in range(1, 5)]
        funcs = ["SUM", "AVERAGE", "MIN", "MAX"]

        def random_raw():
            kind = rng.random()
            if kind < 0.15:
                return ""
            if kind < 0.4:
                return str(rng.randint(-5, 5))
            a, b = rng.sample(addrs, 2)
            lo_c, hi_c = sorted((a[0], b[0]))
            lo_r, hi_r = sorted((a[1], b[1]))
            rng_text = f"{refs.col_to_letters(lo_c)}{lo_r}:{refs.col_to_letters(hi_c)}{hi_r}"
            fn = rng.choice(funcs)
            return f"={fn}({rng_text})"

        s = Sheet()
        for _ in range(300):
            addr = rng.choice(addrs)
            s.set_cell(addr[0], addr[1], random_raw())
            incremental = self._snapshot(s)
            s.recompute_all()
            full = self._snapshot(s)
            self.assertEqual(incremental, full)

    def test_random_paste_fill_clear_fuzz(self):
        """The riskiest oracle test: mixes set_cell, copy_paste, fill, and
        clear (each its own batched multi-cell recompute path) against
        formulas that frequently create and break cycles, and checks the
        incremental engine agrees with a full recompute after every single
        step, not just after plain single-cell edits."""
        rng = random.Random(42)
        addrs = [(c, r) for c in range(1, 7) for r in range(1, 7)]

        def random_raw():
            kind = rng.random()
            if kind < 0.25:
                return str(rng.randint(-5, 5))
            if kind < 0.35:
                return ""
            c, r = rng.choice(addrs)
            op = rng.choice(["+", "-", "*"])
            c2, r2 = rng.choice(addrs)
            return f"={refs.col_to_letters(c)}{r}{op}{refs.col_to_letters(c2)}{r2}"

        s = Sheet()
        for i in range(300):
            action = rng.random()
            if action < 0.5:
                c, r = rng.choice(addrs)
                s.set_cell(c, r, random_raw())
            elif action < 0.7:
                c1, r1 = rng.choice(addrs)
                c2, r2 = rng.choice(addrs)
                lo_c, hi_c = sorted((c1, c2))
                lo_r, hi_r = sorted((r1, r2))
                dest = rng.choice(addrs)
                s.copy_paste((lo_c, lo_r), (hi_c, hi_r), dest)
            elif action < 0.85:
                src = rng.choice(addrs)
                c1, r1 = rng.choice(addrs)
                c2, r2 = rng.choice(addrs)
                lo_c, hi_c = sorted((c1, c2))
                lo_r, hi_r = sorted((r1, r2))
                s.fill(src[0], src[1], (lo_c, lo_r), (hi_c, hi_r))
            else:
                c1, r1 = rng.choice(addrs)
                c2, r2 = rng.choice(addrs)
                lo_c, hi_c = sorted((c1, c2))
                lo_r, hi_r = sorted((r1, r2))
                s.clear((lo_c, lo_r), (hi_c, hi_r))

            incremental = self._snapshot(s)
            s.recompute_all()
            full = self._snapshot(s)
            self.assertEqual(
                incremental, full,
                f"incremental/full mismatch after step {i} (action={action:.2f})",
            )


if __name__ == "__main__":
    unittest.main()
