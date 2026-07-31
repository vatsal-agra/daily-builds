"""`trellis` command-line entry point: repl / serve / csv-import /
csv-export / demo."""

import argparse
import sys

from .sheet import Workbook
from .csvio import import_csv, export_csv
from .functions import to_display_str
from .errors import TrellisError
from .addr import index_to_col


def _fmt_cell(cell):
    if cell is None or cell.raw is None:
        return ""
    v = cell.value
    return v.code if isinstance(v, TrellisError) else to_display_str(v)


def cmd_repl(args):
    wb = Workbook()
    sheet = wb.active_sheet
    print("Trellis REPL. Commands: A1=<value or =formula> | show | quit")
    print("Example: A1=5  then  B1==A1*2  then  show")
    while True:
        try:
            line = input("trellis> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        if line == "show":
            _print_grid(wb.sheets[sheet])
            continue
        if "=" not in line:
            print("  (expected ADDR=value, e.g. A1=5 or B1==A1*2)")
            continue
        addr_text, _, rhs = line.partition("=")
        try:
            row, col = _parse_addr_upper(addr_text.strip())
        except ValueError as e:
            print(f"  error: {e}")
            continue
        # line.partition splits on the *first* '=', so `B1==A1*2` yields
        # rhs == "=A1*2" -- the formula's leading '=' survives intact.
        wb.set_cell(sheet, row, col, rhs)
        cell = wb.get_cell(sheet, row, col)
        print(f"  {addr_text.strip().upper()} = {_fmt_cell(cell)}")


def _parse_addr_upper(text):
    from .addr import parse_addr
    return parse_addr(text)


def _print_grid(sheet):
    max_row, max_col = sheet.dimensions()
    if max_row == 0:
        print("(empty sheet)")
        return
    widths = [8] * (max_col + 1)
    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            widths[c] = max(widths[c], len(_fmt_cell(sheet.get(r, c))) + 2)
    header = "     " + "".join(index_to_col(c).ljust(widths[c]) for c in range(1, max_col + 1))
    print(header)
    for r in range(1, max_row + 1):
        row_str = f"{r:>4} " + "".join(_fmt_cell(sheet.get(r, c)).ljust(widths[c]) for c in range(1, max_col + 1))
        print(row_str)


def cmd_csv_import(args):
    wb = Workbook()
    with open(args.file, "r", newline="") as f:
        text = f.read()
    n, skipped = import_csv(wb, wb.active_sheet, text)
    print(f"imported {n} cells into {wb.active_sheet!r}" + (f" ({skipped} skipped)" if skipped else ""))
    if args.show:
        _print_grid(wb.sheets[wb.active_sheet])
    if args.out:
        with open(args.out, "w", newline="") as f:
            f.write(export_csv(wb.sheets[wb.active_sheet]))
        print(f"wrote computed values to {args.out}")


def cmd_serve(args):
    from .server import serve
    serve(host=args.host, port=args.port)


def cmd_demo(args):
    from . import demo
    demo.run()


def build_parser():
    p = argparse.ArgumentParser(prog="trellis", description="A from-scratch spreadsheet engine.")
    sub = p.add_subparsers(dest="command", required=True)

    p_repl = sub.add_parser("repl", help="interactive cell-at-a-time REPL")
    p_repl.set_defaults(func=cmd_repl)

    p_csv = sub.add_parser("csv-import", help="import a CSV file and print the resulting grid")
    p_csv.add_argument("file")
    p_csv.add_argument("--show", action="store_true", default=True)
    p_csv.add_argument("--out", help="write computed values back out as CSV")
    p_csv.set_defaults(func=cmd_csv_import)

    p_serve = sub.add_parser("serve", help="run the interactive browser UI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="run a scripted end-to-end feature walkthrough")
    p_demo.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
