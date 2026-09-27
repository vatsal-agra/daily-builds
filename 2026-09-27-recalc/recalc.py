#!/usr/bin/env python3
"""Recalc CLI: `serve` the browser UI, `run` a sheet in batch mode, or
`demo` a scripted walkthrough of every feature."""

import argparse
import sys

from engine import csvio
from engine.sheet import Sheet


def cmd_serve(args):
    import server
    server.serve(host=args.host, port=args.port)


def cmd_run(args):
    sheet = Sheet()
    with open(args.file, "r") as f:
        text = f.read()
    if args.file.endswith(".json"):
        csvio.load_workbook(sheet, text)
    else:
        csvio.import_csv(sheet, text)

    if args.export:
        out = csvio.export_csv(sheet)
        with open(args.export, "w") as f:
            f.write(out)
        print(f"Wrote computed values to {args.export}")
    else:
        sys.stdout.write(csvio.export_csv(sheet))
    return 0


def cmd_demo(args):
    from demo import run_demo
    return run_demo()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="recalc")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="start the browser grid UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_run = sub.add_parser("run", help="batch-evaluate a CSV or saved workbook and print/export the computed values")
    p_run.add_argument("file")
    p_run.add_argument("--export", help="write computed values to this CSV path instead of stdout")
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="run a scripted walkthrough of every feature")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
