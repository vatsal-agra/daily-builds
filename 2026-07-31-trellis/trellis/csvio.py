"""CSV import (raw cell content, including formulas) and export (computed
display values) for a single sheet."""

import csv
import io

from .functions import to_display_str
from .errors import TrellisError


def import_csv(workbook, sheet_name, text, start_row=1, start_col=1):
    """Load CSV text into `sheet_name` starting at (start_row, start_col).
    A cell whose text begins with '=' is imported as a live formula;
    everything else is imported as a literal (same rule as typing into the
    UI). Returns the number of non-empty cells imported."""
    reader = csv.reader(io.StringIO(text))
    count = 0
    for r_off, row in enumerate(reader):
        for c_off, raw in enumerate(row):
            if raw == "":
                continue
            workbook.set_cell(sheet_name, start_row + r_off, start_col + c_off, raw)
            count += 1
    workbook.recalc_all_cells()
    return count


def export_csv(sheet, values=True):
    """Render a Sheet to CSV text. `values=True` exports computed display
    values; `values=False` exports raw formula text (round-trippable)."""
    max_row, max_col = sheet.dimensions()
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for r in range(1, max_row + 1):
        row_out = []
        for c in range(1, max_col + 1):
            cell = sheet.get(r, c)
            if cell is None or cell.raw is None:
                row_out.append("")
                continue
            if values:
                v = cell.value
                row_out.append(v.code if isinstance(v, TrellisError) else to_display_str(v))
            else:
                row_out.append(cell.raw)
        writer.writerow(row_out)
    return buf.getvalue()
