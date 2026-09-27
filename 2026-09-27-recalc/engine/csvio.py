"""CSV import (raw cells, formulas included verbatim) and export (computed
display values), plus a plain-JSON workbook save/load format."""

import csv
import io
import json

from . import refs


def import_csv(sheet, text, origin=(1, 1)):
    """Parse CSV text and load it into `sheet` starting at `origin`
    (col, row), 1-based. A cell beginning with '=' is loaded as a live
    formula, exactly like typing it into the grid. Returns the set of
    (col, row) touched, as one recompute batch."""
    reader = csv.reader(io.StringIO(text))
    origin_col, origin_row = origin
    edits = {}
    for r, row in enumerate(reader):
        for c, raw in enumerate(row):
            edits[(origin_col + c, origin_row + r)] = raw
    return sheet.set_cells(edits)


def export_csv(sheet):
    """Serialize the sheet's used range as computed display values."""
    max_col, max_row = sheet.used_bounds()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in range(1, max_row + 1):
        writer.writerow([sheet.get_display(col, row) for col in range(1, max_col + 1)])
    return out.getvalue()


def save_workbook(sheet):
    """A plain JSON snapshot of raw cell contents (A1 address -> raw
    text) — enough to fully reconstruct the sheet via recompute_all()."""
    data = {}
    for (col, row), cell in sheet.cells.items():
        addr = refs.col_to_letters(col) + str(row)
        data[addr] = cell.raw
    return json.dumps({"cells": data}, indent=2)


def load_workbook(sheet, text):
    """Replace `sheet`'s contents with a saved JSON snapshot and fully
    recompute."""
    data = json.loads(text)
    sheet.cells.clear()
    sheet.dependents.clear()
    sheet.undo_stack.clear()
    sheet.redo_stack.clear()
    edits = {}
    for addr, raw in data.get("cells", {}).items():
        ref = refs.parse_cell_ref(addr)
        edits[(ref.col, ref.row)] = raw
    for key, raw in edits.items():
        sheet._set_raw(*key, raw)
    return sheet.recompute_all()
