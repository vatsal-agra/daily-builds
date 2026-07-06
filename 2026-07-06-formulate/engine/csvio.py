"""CSV import/export for a sheet's grid (values, not formulas)."""

import csv
import io

from .workbook import display_value


def export_csv(sheet):
    rows_n, cols_n = sheet.used_bounds()
    buf = io.StringIO()
    writer = csv.writer(buf)
    for r in range(rows_n):
        row_out = []
        for c in range(cols_n):
            cell = sheet.cells.get((r, c))
            row_out.append("" if cell is None else display_value(cell.computed))
        writer.writerow(row_out)
    return buf.getvalue()


def parse_csv_to_edits(sheet_name, text, start_row=0, start_col=0):
    """Parse CSV text into a list of (sheet, row, col, raw_text) edits."""
    reader = csv.reader(io.StringIO(text))
    edits = []
    for r, row in enumerate(reader):
        for c, cell_text in enumerate(row):
            if cell_text == "":
                continue
            edits.append((sheet_name, start_row + r, start_col + c, cell_text))
    return edits
