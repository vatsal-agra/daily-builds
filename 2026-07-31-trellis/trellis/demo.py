"""`trellis demo` -- a scripted, narrated walkthrough of every feature,
runnable non-interactively (used by demo.sh in CI/verification)."""

from .sheet import Workbook
from .csvio import import_csv, export_csv
from .history import History
from .chart import render_chart_svg
from .functions import to_display_str
from .errors import TrellisError


def _fmt(cell):
    if cell is None or cell.raw is None:
        return "(empty)"
    v = cell.value
    return v.code if isinstance(v, TrellisError) else to_display_str(v)


def _check(label, condition):
    status = "OK" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise SystemExit(f"demo assertion failed: {label}")


def run():
    print("=== Trellis demo ===\n")

    print("1. Formula parsing + evaluation")
    wb = Workbook()
    wb.set_cell("Sheet1", 1, 1, "5")
    wb.set_cell("Sheet1", 1, 2, "10")
    wb.set_cell("Sheet1", 1, 3, "=A1+B1*2")
    wb.set_cell("Sheet1", 2, 1, '=IF(A1>3,"big","small")')
    wb.set_cell("Sheet1", 2, 2, "=SUM(A1:B1)")
    wb.set_cell("Sheet1", 2, 3, "=A1/0")
    _check("C1 = A1+B1*2 -> 25", _fmt(wb.get_cell("Sheet1", 1, 3)) == "25")
    _check('A2 = IF(A1>3,"big","small") -> big', _fmt(wb.get_cell("Sheet1", 2, 1)) == "big")
    _check("B2 = SUM(A1:B1) -> 15", _fmt(wb.get_cell("Sheet1", 2, 2)) == "15")
    _check("C2 = A1/0 -> #DIV/0!", _fmt(wb.get_cell("Sheet1", 2, 3)) == "#DIV/0!")

    print("\n2. Dependency graph + incremental recalculation")
    wb2 = Workbook()
    for r in range(1, 501):
        wb2.set_cell("Sheet1", r, 1, str(r))
    wb2.set_cell("Sheet1", 1, 2, "=A1*10")
    before = wb2.eval_count
    wb2.set_cell("Sheet1", 250, 1, "999")  # unrelated leaf edit
    unrelated_evals = wb2.eval_count - before
    _check("editing an unrelated leaf cell triggers 0 recomputations", unrelated_evals == 0)
    before2 = wb2.eval_count
    wb2.set_cell("Sheet1", 1, 1, "7")
    related_evals = wb2.eval_count - before2
    _check("editing A1 recomputes exactly its 1 dependent (B1)", related_evals == 1)
    _check("B1 recomputed to 70", _fmt(wb2.get_cell("Sheet1", 1, 2)) == "70")

    wb3 = Workbook()
    wb3.set_cell("Sheet1", 1, 1, "=A2+1")
    wb3.set_cell("Sheet1", 2, 1, "=A3+1")
    wb3.set_cell("Sheet1", 3, 1, "=A1+1")
    wb3.set_cell("Sheet1", 4, 1, "=A1+100")
    _check("A1/A2/A3 circular chain -> #CIRCULAR!",
           all(_fmt(wb3.get_cell("Sheet1", r, 1)) == "#CIRCULAR!" for r in (1, 2, 3)))
    _check("A4 (reads circular A1) propagates the error, doesn't crash",
           _fmt(wb3.get_cell("Sheet1", 4, 1)) == "#CIRCULAR!")

    print("\n3. Grid data model + CSV import/export")
    csv_text = "Item,Qty,Price,Total\nWidget,3,9.5,=B2*C2\nGadget,2,19,=B3*C3\n"
    wb4 = Workbook()
    n, skipped = import_csv(wb4, "Sheet1", csv_text)
    _check(f"imported {n} cells from CSV", n > 0)
    _check("no cells skipped (small CSV fits the grid)", skipped == 0)
    _check("D2 formula (=B2*C2) computed to 28.5", _fmt(wb4.get_cell("Sheet1", 2, 4)) == "28.5")
    out_csv = export_csv(wb4.sheets["Sheet1"])
    _check("exported CSV contains computed value, not formula text", "28.5" in out_csv and "B2*C2" not in out_csv)

    print("\n4. Server-backed UI (exercised live by demo.sh via curl)")
    print("   (see demo.sh for the real HTTP walkthrough)")

    print("\n5. Undo/redo")
    wb5 = Workbook()
    hist = History(wb5)
    hist.set_cell("Sheet1", 1, 1, "1")
    hist.set_cell("Sheet1", 1, 1, "2")
    hist.set_cell("Sheet1", 1, 1, "3")
    _check("A1 = 3 after 3 edits", _fmt(wb5.get_cell("Sheet1", 1, 1)) == "3")
    hist.undo()
    hist.undo()
    _check("A1 = 1 after 2 undos", _fmt(wb5.get_cell("Sheet1", 1, 1)) == "1")
    hist.redo()
    _check("A1 = 2 after 1 redo", _fmt(wb5.get_cell("Sheet1", 1, 1)) == "2")

    print("\n6. Charts (SVG)")
    wb6 = Workbook()
    for i, (label, val) in enumerate([("a", 3), ("b", 7), ("c", 2)], start=1):
        wb6.set_cell("Sheet1", i, 1, label)
        wb6.set_cell("Sheet1", i, 2, str(val))
    svg = render_chart_svg(wb6, "Sheet1", "A1:B3", "bar")
    _check("chart SVG contains <svg> root and 3 bars", svg.startswith("<svg") and svg.count("<rect") >= 3)

    print("\n7. Multi-sheet workbook + cross-sheet references")
    wb7 = Workbook()
    wb7.add_sheet("Data")
    wb7.set_cell("Data", 1, 1, "42")
    wb7.set_cell("Sheet1", 1, 1, "=Data!A1*2")
    _check("Sheet1!A1 reading Data!A1 -> 84", _fmt(wb7.get_cell("Sheet1", 1, 1)) == "84")
    wb7.set_cell("Data", 1, 1, "10")
    _check("cross-sheet dependency recalculates -> 20", _fmt(wb7.get_cell("Sheet1", 1, 1)) == "20")

    print("\nAll demo checks passed.")
