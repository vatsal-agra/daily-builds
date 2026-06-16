"""Command-line entry point: `python3 -m picosql [DBFILE] [-c SQL]`."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .database import Database, DBError
from .parser import ParseError, format_error
from .repl import Repl, render_table
from .tokenizer import TokenizeError


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser(
        prog="picosql",
        description="A from-scratch SQL database engine on a durable B+tree.",
    )
    ap.add_argument("dbfile", nargs="?", default=":memory:",
                    help="database file (default: in-memory, discarded on exit)")
    ap.add_argument("-c", "--command", help="run one or more ';'-separated statements and exit")
    ap.add_argument("--version", action="version", version=f"picosql {__version__}")
    args = ap.parse_args(argv)

    db = Database(args.dbfile)
    try:
        if args.command is not None:
            _run_batch(db, args.command)
        else:
            if sys.stdin.isatty():
                print(f"PicoSQL {__version__} — type .help for commands, .exit to quit")
                print(f"database: {args.dbfile}")
            Repl(db).loop()
    finally:
        db.close()
    return 0


def _run_batch(db: Database, script: str):
    from .database import _split_statements
    for stmt in _split_statements(script):
        if not stmt.strip():
            continue
        try:
            res = db.execute(stmt)
            if res.is_select:
                print(render_table(res.columns, res.rows))
            elif res.message is not None:
                print(res.message)
        except (ParseError, TokenizeError) as e:
            print(format_error(stmt, e.message, e.pos), file=sys.stderr)
            sys.exit(1)
        except DBError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
