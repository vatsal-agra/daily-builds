"""CSV import (raw cell content, including formulas) and export (computed
display values) for a single sheet."""

import csv
import io

from .functions import to_display_str
from .errors import TrellisError


def import_csv(workbook, sheet_name, text, start_row=1, start_col=1, max_row=None, max_col=None):
    """Load CSV text into `sheet_name` starting at (start_row, start_col).
    A cell whose text begins with '=' is imported as a live formula;
    everything else is imported as a literal (same rule as typing into the
    UI). `max_row`/`max_col`, if given, cap how far the import writes (the
    interactive UI's grid has a fixed visible size, and silently writing
    cells past it -- still "imported" but never rendered -- would look like
    data loss with no explanation). Returns `(imported, skipped)` counts."""
    reader = csv.reader(io.StringIO(text))
    imported = 0
    skipped = 0
    for r_off, row in enumerate(reader):
        r = start_row + r_off
        if max_row is not None and r > max_row:
            skipped += sum(1 for cell in row if cell != "")
            continue
        for c_off, raw in enumerate(row):
            if raw == "":
                continue
            c = start_col + c_off
            if max_col is not None and c > max_col:
                skipped += 1
                continue
            workbook.set_cell(sheet_name, r, c, raw)
            imported += 1
    workbook.recalc_all_cells()
    return imported, skipped


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
