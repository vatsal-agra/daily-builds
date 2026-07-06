#!/usr/bin/env python3
"""Formulate CLI: serve the interactive UI, run a scripted demo, or run tests."""

import argparse
import sys
from pathlib import Path

from engine import csvio, persistence
from engine.workbook import Workbook, a1_to_ref, display_value


def cmd_serve(args):
    import server
    workbook = None
    if args.load:
        path = Path(args.load)
        workbook = persistence.from_json(path.read_text())
    server.run(workbook=workbook, host=args.host, port=args.port)


def cmd_demo(args):
    wb = build_demo_workbook()
    sheet = wb.sheets["Budget"]
    rows, cols = sheet.used_bounds()
    col_widths = [8] * cols
    for (r, c), cell in sheet.cells.items():
        col_widths[c] = max(col_widths[c], len(display_value(cell.computed)))
    for r in range(rows):
        parts = []
        for c in range(cols):
            text = display_value(sheet.get_computed(r, c))
            parts.append(text.rjust(col_widths[c]))
        print(" | ".join(parts))
    print()
    print("Total (D-column SUM formula) =", display_value(sheet.get_computed(*a1_to_ref("D8"))))


def build_demo_workbook():
    wb = Workbook()
    wb.add_sheet("Budget")

    def setc(a1, text):
        r, c = a1_to_ref(a1)
        wb.edit([("Budget", r, c, text)])

    rows = [
        ("Item", "Qty", "Price", "Subtotal"),
        ("Coffee", "12", "3.5", "=B2*C2"),
        ("Notebooks", "5", "2.25", "=B3*C3"),
        ("Pens", "20", "0.4", "=B4*C4"),
        ("Monitor", "1", "199.99", "=B5*C5"),
    ]
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            setc(chr(ord("A") + j) + str(i + 1), val)
    setc("A7", "Total")
    setc("D7", "=SUM(D2:D5)")
    setc("A8", "Average item cost")
    setc("D8", "=ROUND(AVERAGE(D2:D5),2)")
    return wb


def cmd_export(args):
    if args.load:
        wb = persistence.from_json(Path(args.load).read_text())
    else:
        wb = build_demo_workbook()
    sheet_name = args.sheet or wb.sheet_order[0]
    sheet = wb.get_or_create_sheet(sheet_name)
    text = csvio.export_csv(sheet)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)


def cmd_test(args):
    import subprocess
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(prog="formulate")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the interactive spreadsheet server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--load", help="load a saved workbook JSON file on startup")
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="build and print a demo budget workbook to the terminal")
    p_demo.set_defaults(func=cmd_demo)

    p_export = sub.add_parser("export", help="export a workbook's sheet to CSV")
    p_export.add_argument("--load", help="workbook JSON to load (default: built-in demo)")
    p_export.add_argument("--sheet")
    p_export.add_argument("--out")
    p_export.set_defaults(func=cmd_export)

    p_test = sub.add_parser("test", help="run the test suite")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
