"""Top-level database: open a file, run SQL statements, manage transactions."""

from __future__ import annotations

from typing import List, Optional

from . import ast_nodes as A
from .btree import BTree
from .catalog import Catalog, Column, TableSchema
from .executor import Result, eval_expr, run_select
from .parser import parse
from .planner import build_source
from .pager import Pager
from .types import coerce, encode_row, TypeError_


class DBError(Exception):
    pass


class ExecResult:
    """Unified statement result."""

    def __init__(self, columns=None, rows=None, message=None, rowcount=None):
        self.columns = columns
        self.rows = rows
        self.message = message
        self.rowcount = rowcount

    @property
    def is_select(self):
        return self.columns is not None


class Database:
    def __init__(self, path: str = ":memory:"):
        if path == ":memory:":
            import tempfile, os
            self._tmp = tempfile.NamedTemporaryFile(suffix=".picodb", delete=False)
            self._tmp.close()
            self._tmp_path = self._tmp.name
            os.remove(self._tmp_path)  # start fresh
            path = self._tmp_path
            self._is_memory = True
        else:
            self._is_memory = False
        self.path = path
        self.pager = Pager(path)
        self.catalog = Catalog(self.pager)
        self.in_txn = False

    def close(self):
        self.pager.close()
        if self._is_memory:
            import os
            for p in (self._tmp_path, self._tmp_path + "-journal"):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ---- helpers ---------------------------------------------------------
    def require_table(self, name: str) -> TableSchema:
        s = self.catalog.get_by_name(name)
        if s is None:
            raise DBError(f"no such table: {name}")
        return s

    def _tree(self, schema: TableSchema) -> BTree:
        return BTree(self.pager, schema.root_page)

    # ---- public API ------------------------------------------------------
    def execute(self, sql: str) -> ExecResult:
        stmt = parse(sql)
        return self._dispatch(stmt)

    def execute_script(self, sql: str) -> List[ExecResult]:
        """Run multiple ';'-separated statements; returns one result each."""
        results = []
        for piece in _split_statements(sql):
            if piece.strip():
                results.append(self.execute(piece))
        return results

    def _dispatch(self, stmt) -> ExecResult:
        if isinstance(stmt, A.Begin):
            if self.in_txn:
                raise DBError("already inside a transaction")
            self.pager.begin()
            self.in_txn = True
            return ExecResult(message="BEGIN")
        if isinstance(stmt, A.Commit):
            if not self.in_txn:
                raise DBError("no transaction to commit")
            self.pager.commit()
            self.in_txn = False
            return ExecResult(message="COMMIT")
        if isinstance(stmt, A.Rollback):
            if not self.in_txn:
                raise DBError("no transaction to roll back")
            self.pager.rollback()
            self.catalog.reload()
            self.in_txn = False
            return ExecResult(message="ROLLBACK")
        if isinstance(stmt, A.Explain):
            return self._explain(stmt.statement)

        # data statements run inside an (auto)transaction
        if self.in_txn:
            return self._run(stmt)
        self.pager.begin()
        try:
            res = self._run(stmt)
            self.pager.commit()
            return res
        except Exception:
            self.pager.rollback()
            self.catalog.reload()
            raise

    def _run(self, stmt) -> ExecResult:
        if isinstance(stmt, A.Select):
            return self._select(stmt)
        if isinstance(stmt, A.CreateTable):
            return self._create(stmt)
        if isinstance(stmt, A.DropTable):
            return self._drop(stmt)
        if isinstance(stmt, A.Insert):
            return self._insert(stmt)
        if isinstance(stmt, A.Update):
            return self._update(stmt)
        if isinstance(stmt, A.Delete):
            return self._delete(stmt)
        raise DBError(f"cannot execute {type(stmt).__name__}")

    # ---- DDL -------------------------------------------------------------
    def _create(self, stmt: A.CreateTable) -> ExecResult:
        if self.catalog.get_by_name(stmt.name) is not None:
            if stmt.if_not_exists:
                return ExecResult(message=f"table {stmt.name} already exists")
            raise DBError(f"table {stmt.name} already exists")
        cols = [Column(c.name, c.type) for c in stmt.columns]
        names = [c.name.lower() for c in cols]
        if len(set(names)) != len(names):
            raise DBError("duplicate column name in CREATE TABLE")
        pk_col = None
        for i, c in enumerate(stmt.columns):
            if c.primary_key:
                pk_col = i
                break
        self.catalog.create_table(stmt.name, cols, pk_col)
        return ExecResult(message=f"CREATE TABLE {stmt.name}")

    def _drop(self, stmt: A.DropTable) -> ExecResult:
        if self.catalog.get_by_name(stmt.name) is None:
            if stmt.if_exists:
                return ExecResult(message=f"no such table: {stmt.name}")
            raise DBError(f"no such table: {stmt.name}")
        self.catalog.drop_table(stmt.name)
        return ExecResult(message=f"DROP TABLE {stmt.name}")

    # ---- DML -------------------------------------------------------------
    def _resolve_insert_columns(self, schema, stmt) -> List[int]:
        if stmt.columns is None:
            return list(range(len(schema.columns)))
        idxs = []
        for cn in stmt.columns:
            idx = schema.col_index(cn)
            if idx is None:
                raise DBError(f"no column {cn!r} in {schema.name}")
            idxs.append(idx)
        return idxs

    def _insert(self, stmt: A.Insert) -> ExecResult:
        schema = self.require_table(stmt.table)
        target_idxs = self._resolve_insert_columns(schema, stmt)
        tree = self._tree(schema)
        count = 0
        for row_exprs in stmt.rows:
            if len(row_exprs) != len(target_idxs):
                raise DBError(
                    f"INSERT has {len(row_exprs)} values but "
                    f"{len(target_idxs)} target columns"
                )
            values = [None] * len(schema.columns)
            for slot, expr in zip(target_idxs, row_exprs):
                values[slot] = eval_expr(expr, [])
            # determine rowid
            if schema.pk_col is not None:
                pkv = values[schema.pk_col]
                if pkv is None:
                    rowid = schema.next_rowid
                    values[schema.pk_col] = rowid
                else:
                    if not isinstance(pkv, int) or isinstance(pkv, bool):
                        raise DBError("PRIMARY KEY value must be an integer")
                    rowid = pkv
                    if tree.search(rowid) is not None:
                        raise DBError(f"duplicate PRIMARY KEY value {rowid}")
            else:
                rowid = schema.next_rowid
            # coerce to declared types
            try:
                coerced = [coerce(v, schema.columns[i].type) for i, v in enumerate(values)]
            except TypeError_ as e:
                raise DBError(str(e))
            tree.insert(rowid, encode_row(coerced))
            schema.next_rowid = max(schema.next_rowid, rowid + 1)
            count += 1
        schema.root_page = tree.root
        self.catalog.save(schema)
        return ExecResult(message=f"INSERT {count}", rowcount=count)

    def _update(self, stmt: A.Update) -> ExecResult:
        schema = self.require_table(stmt.table)
        tree = self._tree(schema)
        alias = schema.name.lower()
        assigns = []
        for col, expr in stmt.assignments:
            idx = schema.col_index(col)
            if idx is None:
                raise DBError(f"no column {col!r} in {schema.name}")
            assigns.append((idx, expr))

        mods = []  # (old_key, new_key, blob)
        for key, blob in list(tree.scan()):
            from .types import decode_row
            values = list(decode_row(blob))
            bindings = [(alias, schema, tuple(values))]
            if stmt.where is not None and eval_expr(stmt.where, bindings) is not True:
                continue
            for idx, expr in assigns:
                values[idx] = eval_expr(expr, bindings)
            try:
                coerced = [coerce(v, schema.columns[i].type) for i, v in enumerate(values)]
            except TypeError_ as e:
                raise DBError(str(e))
            new_key = coerced[schema.pk_col] if schema.pk_col is not None else key
            if not isinstance(new_key, int) or isinstance(new_key, bool):
                raise DBError("PRIMARY KEY value must be an integer")
            mods.append((key, new_key, encode_row(coerced)))

        # detect duplicate target pks among moves / collisions
        for old_key, new_key, blob in mods:
            if new_key != old_key:
                if tree.search(new_key) is not None and new_key not in [m[0] for m in mods]:
                    raise DBError(f"duplicate PRIMARY KEY value {new_key}")
        for old_key, new_key, blob in mods:
            if new_key != old_key:
                tree.delete(old_key)
            tree.insert(new_key, blob)
            schema.next_rowid = max(schema.next_rowid, new_key + 1)
        schema.root_page = tree.root
        self.catalog.save(schema)
        return ExecResult(message=f"UPDATE {len(mods)}", rowcount=len(mods))

    def _delete(self, stmt: A.Delete) -> ExecResult:
        schema = self.require_table(stmt.table)
        tree = self._tree(schema)
        alias = schema.name.lower()
        from .types import decode_row
        keys = []
        for key, blob in list(tree.scan()):
            if stmt.where is None:
                keys.append(key)
            else:
                bindings = [(alias, schema, decode_row(blob))]
                if eval_expr(stmt.where, bindings) is True:
                    keys.append(key)
        for k in keys:
            tree.delete(k)
        schema.root_page = tree.root
        self.catalog.save(schema)
        return ExecResult(message=f"DELETE {len(keys)}", rowcount=len(keys))

    # ---- SELECT / EXPLAIN ------------------------------------------------
    def _select(self, stmt: A.Select) -> ExecResult:
        source, relations = build_source(self, stmt)
        result: Result = run_select(self, stmt, source, relations)
        return ExecResult(columns=result.columns, rows=result.rows)

    def _explain(self, stmt) -> ExecResult:
        if not isinstance(stmt, A.Select):
            return ExecResult(message=f"(no plan for {type(stmt).__name__})")
        source, relations = build_source(self, stmt)
        lines = []
        # describe the post-source pipeline top-down
        proj = "Project " + ", ".join(
            (a or _label(e)) for e, a in stmt.projections
        )
        lines.append(proj)
        indent = 1
        if stmt.distinct:
            lines.append("  " * indent + "Distinct"); indent += 1
        if stmt.limit is not None or stmt.offset:
            lim = stmt.limit if stmt.limit is not None else "all"
            off = stmt.offset or 0
            lines.append("  " * indent + f"Limit {lim} Offset {off}"); indent += 1
        if stmt.order_by:
            keys = ", ".join(
                _label(e) + (" DESC" if d else " ASC") for e, d in stmt.order_by
            )
            lines.append("  " * indent + f"Sort {keys}"); indent += 1
        if stmt.group_by or _has_aggregates(stmt):
            gb = ", ".join(_label(e) for e in stmt.group_by) or "(whole table)"
            lines.append("  " * indent + f"Aggregate group by {gb}"); indent += 1
        if stmt.having is not None:
            lines.append("  " * indent + "Having"); indent += 1
        lines.append(source.explain(indent))
        return ExecResult(message="\n".join(lines))


def _label(expr):
    from .executor import _expr_label
    if isinstance(expr, A.Star):
        return (expr.table + ".*") if expr.table else "*"
    return _expr_label(expr)


def _has_aggregates(stmt) -> bool:
    from .executor import _collect_aggregates
    found = []
    for e, _ in stmt.projections:
        if not isinstance(e, A.Star):
            _collect_aggregates(e, found)
    if stmt.having is not None:
        _collect_aggregates(stmt.having, found)
    return bool(found)


def _split_statements(sql: str) -> List[str]:
    """Split on ';' that are not inside string literals or comments."""
    out = []
    buf = []
    i = 0
    n = len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            buf.append(c)
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                buf.append(sql[i])
                i += 1
            continue
        if c == ";":
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if "".join(buf).strip():
        out.append("".join(buf))
    return out
