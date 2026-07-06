"""JSON workbook save/load. Only formula/literal *text* is persisted —
computed values and the dependency graph are rebuilt from scratch on load,
which doubles as a full-recalculation integrity check on every load.
"""

import json

from .workbook import Workbook


def to_dict(workbook):
    return {
        "sheet_order": list(workbook.sheet_order),
        "sheets": {
            name: {
                f"{row},{col}": cell.raw
                for (row, col), cell in sheet.cells.items()
            }
            for name, sheet in workbook.sheets.items()
        },
    }


def to_json(workbook):
    return json.dumps(to_dict(workbook), indent=2, sort_keys=True)


def from_dict(data):
    wb = Workbook()
    for name in data.get("sheet_order") or sorted(data.get("sheets", {})):
        wb.add_sheet(name)
    edits = []
    for name, cells in data.get("sheets", {}).items():
        wb.get_or_create_sheet(name)
        for key, raw in cells.items():
            row_s, col_s = key.split(",")
            edits.append((name, int(row_s), int(col_s), raw))
    if edits:
        wb.edit(edits)
    return wb


def from_json(text):
    return from_dict(json.loads(text))
