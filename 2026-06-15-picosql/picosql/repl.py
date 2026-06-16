"""Interactive SQL shell for PicoSQL.

Features: box-drawn result tables (numbers right-aligned, NULLs shown), multi-line
statement entry (keep typing until ';'), positioned syntax-error carets, and
dot-commands (.help .tables .schema .import .dump .exit). Designed to also work
with piped input for scripted demos/tests.
"""

from __future__ import annotations

import csv
import sys
from typing import List, Optional

from .database import Database, DBError
from .parser import ParseError, format_error
from .tokenizer import TokenizeError

PROMPT = "picosql> "
CONT = "    ...> "


# ---- pretty table rendering --------------------------------------------
def _cell(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        # show integral floats without trailing zeros noise but keep precision
        if v == int(v) and abs(v) < 1e15:
            return f"{v:.1f}"
        return repr(v)
    return str(v)


def render_table(columns: List[str], rows: List[tuple]) -> str:
    cells = [[_cell(v) for v in row] for row in rows]
    ncol = len(columns)
    widths = [len(c) for c in columns]
    for row in cells:
        for i in range(ncol):
            widths[i] = max(widths[i], len(row[i]))
    # column is numeric if every non-null value is int/float
    numeric = [True] * ncol
    for row in rows:
        for i, v in enumerate(row):
            if v is not None and not isinstance(v, (int, float)):
                numeric[i] = False

    def hline(l, m, r):
        return l + m.join("─" * (w + 2) for w in widths) + r

    def fmt_row(values):
        parts = []
        for i, val in enumerate(values):
            if numeric[i] and val != "NULL":
                parts.append(" " + val.rjust(widths[i]) + " ")
            else:
                parts.append(" " + val.ljust(widths[i]) + " ")
        return "│" + "│".join(parts) + "│"

    out = [hline("┌", "┬", "┐"), fmt_row(columns), hline("├", "┼", "┤")]
    for row in cells:
        out.append(fmt_row(row))
    out.append(hline("└", "┴", "┘"))
    n = len(rows)
    out.append(f"({n} row{'s' if n != 1 else ''})")
    return "\n".join(out)


# ---- the shell ----------------------------------------------------------
class Repl:
    def __init__(self, db: Database, out=None, color: bool = True):
        self.db = db
        self.out = out or sys.stdout
        self.color = color and self.out.isatty()

    def _print(self, *a):
        print(*a, file=self.out)

    def _err(self, msg):
        if self.color:
            self._print(f"\033[31m{msg}\033[0m")
        else:
            self._print(msg)

    # ---- result display -------------------------------------------------
    def show_result(self, res):
        if res.is_select:
            self._print(render_table(res.columns, res.rows))
        elif res.message is not None:
            self._print(res.message)

    # ---- statement execution -------------------------------------------
    def run_sql(self, sql: str):
        try:
            res = self.db.execute(sql)
            self.show_result(res)
        except (ParseError, TokenizeError) as e:
            self._err(format_error(sql, e.message, e.pos))
        except DBError as e:
            self._err(f"error: {e}")
        except Exception as e:  # executor / storage errors
            self._err(f"error: {e}")

    # ---- dot-commands ---------------------------------------------------
    def dot(self, line: str) -> bool:
        parts = line.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd in (".exit", ".quit", ".q"):
            return False
        if cmd == ".help":
            self._help()
        elif cmd == ".tables":
            names = [t.name for t in self.db.catalog.list_tables()]
            self._print("  ".join(names) if names else "(no tables)")
        elif cmd == ".schema":
            self._schema(args[0] if args else None)
        elif cmd == ".import":
            if len(args) != 2:
                self._err("usage: .import FILE.csv TABLE")
            else:
                self._import_csv(args[0], args[1])
        elif cmd == ".dump":
            self._dump()
        else:
            self._err(f"unknown command {cmd!r} (try .help)")
        return True

    def _help(self):
        self._print(
            "Dot-commands:\n"
            "  .tables              list tables\n"
            "  .schema [TABLE]      show table definition(s)\n"
            "  .import FILE.csv T   load a CSV (with header row) into table T\n"
            "  .dump                print SQL to recreate the whole database\n"
            "  .help                this help\n"
            "  .exit / .quit        leave\n"
            "Statements end with ';' and may span multiple lines.\n"
            "Transactions: BEGIN; ... COMMIT; / ROLLBACK;  EXPLAIN <query>; shows the plan."
        )

    def _schema(self, table: Optional[str]):
        tables = self.db.catalog.list_tables()
        if table is not None:
            tables = [t for t in tables if t.name.lower() == table.lower()]
            if not tables:
                self._err(f"no such table: {table}")
                return
        for t in tables:
            self._print(self._create_sql(t))

    def _create_sql(self, t) -> str:
        cols = []
        for i, c in enumerate(t.columns):
            pk = " PRIMARY KEY" if t.pk_col == i else ""
            cols.append(f"{c.name} {c.type}{pk}")
        return f"CREATE TABLE {t.name} ({', '.join(cols)});"

    def _dump(self):
        for t in self.db.catalog.list_tables():
            self._print(self._create_sql(t))
            res = self.db.execute(f"SELECT * FROM {t.name}")
            colnames = ", ".join(c.name for c in t.columns)
            for row in res.rows:
                vals = ", ".join(_sql_literal(v) for v in row)
                self._print(f"INSERT INTO {t.name} ({colnames}) VALUES ({vals});")

    def _import_csv(self, path: str, table: str):
        schema = self.db.catalog.get_by_name(table)
        if schema is None:
            self._err(f"no such table: {table}")
            return
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except OSError as e:
            self._err(f"cannot read {path}: {e}")
            return
        if not rows:
            self._print("(empty file)")
            return
        header = [h.strip() for h in rows[0]]
        body = rows[1:]
        count = 0
        try:
            self.db.execute("BEGIN")
            for r in body:
                if not any(cell.strip() for cell in r):
                    continue
                vals = ", ".join(_sql_literal(_parse_cell(c)) for c in r)
                self.db.execute(
                    f"INSERT INTO {table} ({', '.join(header)}) VALUES ({vals})"
                )
                count += 1
            self.db.execute("COMMIT")
        except Exception as e:
            self.db.execute("ROLLBACK")
            self._err(f"import failed (rolled back): {e}")
            return
        self._print(f"imported {count} rows into {table}")

    # ---- main loop ------------------------------------------------------
    def loop(self):
        interactive = sys.stdin.isatty()
        buffer = ""
        while True:
            try:
                prompt = (PROMPT if not buffer else CONT) if interactive else ""
                line = input(prompt)
            except EOFError:
                if interactive:
                    self._print("")
                break
            except KeyboardInterrupt:
                buffer = ""
                self._print("^C")
                continue
            if not buffer.strip() and line.strip().startswith("."):
                buffer = ""
                if not self.dot(line):
                    break
                continue
            buffer += line + "\n"
            # execute complete (';'-terminated) statements
            stmts, buffer = _take_complete(buffer)
            for s in stmts:
                if s.strip():
                    self.run_sql(s)
            if not buffer.strip():
                buffer = ""
        # auto-commit any open transaction by rolling back (safer default)
        if self.db.in_txn:
            self.db.execute("ROLLBACK")


def _take_complete(buffer: str):
    """Return (complete_statements, remainder) splitting on top-level ';'."""
    stmts = []
    buf = []
    i = 0
    n = len(buffer)
    in_str = False
    last_cut = 0
    while i < n:
        c = buffer[i]
        if in_str:
            if c == "'":
                if i + 1 < n and buffer[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            i += 1
            continue
        if c == "-" and i + 1 < n and buffer[i + 1] == "-":
            while i < n and buffer[i] != "\n":
                i += 1
            continue
        if c == ";":
            stmts.append(buffer[last_cut:i])
            last_cut = i + 1
        i += 1
    remainder = buffer[last_cut:]
    return stmts, remainder


def _parse_cell(s: str):
    s = s.strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"
