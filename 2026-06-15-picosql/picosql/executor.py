"""Query planning and execution.

Execution rows flow as *binding lists*: a list of `(alias, schema, values)`
tuples, one per table instance contributing to the current row (one for a base
scan, several after joins). Expressions are evaluated against a binding list,
which is how `t.col` / bare `col` / ambiguity resolution all work.

Scans, joins and filters are pull-based ("Volcano") operators that also know how
to print themselves for EXPLAIN. Aggregation, sorting, DISTINCT and LIMIT are
applied on top in `run_select`.
"""

from __future__ import annotations

import re
from typing import Iterator, List, Optional, Tuple

from . import ast_nodes as A
from .btree import BTree
from .catalog import TableSchema
from .types import decode_row

Binding = Tuple[str, TableSchema, tuple]  # (alias_lower, schema, values)
BindingList = List[Binding]

_AGG = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class ExecError(Exception):
    pass


# ---- value helpers ------------------------------------------------------
def _rank(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1
    if isinstance(v, (int, float)):
        return 1
    return 2


def _sortkey(v):
    return (_rank(v), v if v is not None else 0)


def _compare(a, b) -> Optional[int]:
    """SQL three-valued compare: returns -1/0/1, or None if either is NULL."""
    if a is None or b is None:
        return None
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def _like_to_regex(pattern: str) -> "re.Pattern":
    out = ["(?s)^"]
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    out.append("$")
    return re.compile("".join(out))


# ---- expression evaluation ---------------------------------------------
def eval_expr(expr: A.Expr, bindings: BindingList, agg_values=None):
    if isinstance(expr, A.Literal):
        return expr.value
    if isinstance(expr, A.ColumnRef):
        return _lookup_column(expr, bindings)
    if isinstance(expr, A.Star):
        raise ExecError("'*' is not valid here")
    if isinstance(expr, A.IsNull):
        v = eval_expr(expr.operand, bindings, agg_values)
        is_null = v is None
        return is_null != expr.negated
    if isinstance(expr, A.UnaryOp):
        if expr.op == "NOT":
            v = eval_expr(expr.operand, bindings, agg_values)
            if v is None:
                return None
            return not _truthy(v)
        v = eval_expr(expr.operand, bindings, agg_values)
        if v is None:
            return None
        if expr.op == "-":
            return -v
        return +v
    if isinstance(expr, A.InList):
        left = eval_expr(expr.operand, bindings, agg_values)
        if left is None:
            return None
        has_null = False
        matched = False
        for item in expr.items:
            v = eval_expr(item, bindings, agg_values)
            if v is None:
                has_null = True
                continue
            if _compare(left, v) == 0:
                matched = True
                break
        if matched:
            result = True
        elif has_null:
            return None  # unknown
        else:
            result = False
        return (not result) if expr.negated else result
    if isinstance(expr, A.BinaryOp):
        return _eval_binary(expr, bindings, agg_values)
    if isinstance(expr, A.FuncCall):
        if expr.name in _AGG:
            if agg_values is None:
                raise ExecError(f"aggregate {expr.name} used where not allowed")
            return agg_values[id(expr)]
        return _eval_scalar_func(expr, bindings, agg_values)
    raise ExecError(f"cannot evaluate expression {expr!r}")


def _truthy(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v != ""
    return bool(v)


def _eval_binary(expr: A.BinaryOp, bindings, agg_values):
    op = expr.op
    if op == "AND":
        l = eval_expr(expr.left, bindings, agg_values)
        if l is not None and not _truthy(l):
            return False
        r = eval_expr(expr.right, bindings, agg_values)
        if r is not None and not _truthy(r):
            return False
        if l is None or r is None:
            return None
        return True
    if op == "OR":
        l = eval_expr(expr.left, bindings, agg_values)
        if l is not None and _truthy(l):
            return True
        r = eval_expr(expr.right, bindings, agg_values)
        if r is not None and _truthy(r):
            return True
        if l is None or r is None:
            return None
        return False

    l = eval_expr(expr.left, bindings, agg_values)
    r = eval_expr(expr.right, bindings, agg_values)
    if op == "LIKE":
        if l is None or r is None:
            return None
        if not isinstance(l, str) or not isinstance(r, str):
            return False
        return _like_to_regex(r).match(l) is not None
    if op in ("=", "!=", "<", "<=", ">", ">="):
        c = _compare(l, r)
        if c is None:
            return None
        return {
            "=": c == 0, "!=": c != 0, "<": c < 0,
            "<=": c <= 0, ">": c > 0, ">=": c >= 0,
        }[op]
    # arithmetic
    if l is None or r is None:
        return None
    if not isinstance(l, (int, float)) or not isinstance(r, (int, float)):
        raise ExecError(f"arithmetic on non-numeric value ({l!r} {op} {r!r})")
    if op == "+":
        return l + r
    if op == "-":
        return l - r
    if op == "*":
        return l * r
    if op == "/":
        if r == 0:
            return None
        if isinstance(l, int) and isinstance(r, int):
            return l // r if l % r == 0 else l / r
        return l / r
    if op == "%":
        if r == 0:
            return None
        return l % r
    raise ExecError(f"unknown operator {op}")


def _eval_scalar_func(expr: A.FuncCall, bindings, agg_values):
    name = expr.name
    args = [eval_expr(a, bindings, agg_values) for a in expr.args]
    if name == "ABS":
        return None if args[0] is None else abs(args[0])
    if name == "LENGTH":
        return None if args[0] is None else len(str(args[0]))
    if name == "UPPER":
        return None if args[0] is None else str(args[0]).upper()
    if name == "LOWER":
        return None if args[0] is None else str(args[0]).lower()
    if name == "ROUND":
        if args[0] is None:
            return None
        nd = int(args[1]) if len(args) > 1 and args[1] is not None else 0
        return round(args[0], nd)
    if name == "COALESCE":
        for a in args:
            if a is not None:
                return a
        return None
    raise ExecError(f"unknown function {name}")


def _lookup_column(ref: A.ColumnRef, bindings: BindingList):
    name = ref.name.lower()
    if ref.table is not None:
        talias = ref.table.lower()
        for alias, schema, values in bindings:
            if alias == talias:
                idx = schema.col_index(name)
                if idx is None:
                    raise ExecError(f"no column {ref.name!r} in {ref.table!r}")
                return values[idx]
        raise ExecError(f"no table or alias {ref.table!r} in scope")
    found = []
    for alias, schema, values in bindings:
        idx = schema.col_index(name)
        if idx is not None:
            found.append(values[idx])
    if len(found) == 1:
        return found[0]
    if not found:
        raise ExecError(f"no such column {ref.name!r}")
    raise ExecError(f"ambiguous column {ref.name!r} (qualify it with a table name)")


# ---- operators ----------------------------------------------------------
class Op:
    def rows(self) -> Iterator[BindingList]:
        raise NotImplementedError

    def explain(self, indent: int = 0) -> str:
        raise NotImplementedError


class SingleRow(Op):
    """One empty binding (for SELECT with no FROM)."""

    def rows(self):
        yield []

    def explain(self, indent=0):
        return "  " * indent + "SingleRow"


class SeqScan(Op):
    def __init__(self, table: BTree, schema: TableSchema, alias: str):
        self.table = table
        self.schema = schema
        self.alias = alias.lower()

    def rows(self):
        for _key, blob in self.table.scan():
            yield [(self.alias, self.schema, decode_row(blob))]

    def explain(self, indent=0):
        return "  " * indent + f"SeqScan {self.schema.name} (alias {self.alias})"


class IndexSeek(Op):
    def __init__(self, table: BTree, schema: TableSchema, alias: str, key: int):
        self.table = table
        self.schema = schema
        self.alias = alias.lower()
        self.key = key

    def rows(self):
        blob = self.table.search(self.key)
        if blob is not None:
            yield [(self.alias, self.schema, decode_row(blob))]

    def explain(self, indent=0):
        return "  " * indent + (
            f"IndexSeek {self.schema.name} (alias {self.alias}) "
            f"PK = {self.key}"
        )


class IndexRange(Op):
    def __init__(self, table, schema, alias, low, high):
        self.table = table
        self.schema = schema
        self.alias = alias.lower()
        self.low = low
        self.high = high

    def rows(self):
        for _key, blob in self.table.scan(self.low, self.high):
            yield [(self.alias, self.schema, decode_row(blob))]

    def explain(self, indent=0):
        lo = "-inf" if self.low is None else self.low
        hi = "+inf" if self.high is None else self.high
        return "  " * indent + (
            f"IndexRange {self.schema.name} (alias {self.alias}) "
            f"PK in [{lo}, {hi}]"
        )


class NestedLoopJoin(Op):
    def __init__(self, left: Op, right: Op, on: Optional[A.Expr]):
        self.left = left
        self.right = right
        self.on = on

    def rows(self):
        right_rows = list(self.right.rows())  # materialize inner side once
        for l in self.left.rows():
            for r in right_rows:
                combined = l + r
                if self.on is None:
                    yield combined
                else:
                    v = eval_expr(self.on, combined)
                    if v is True:
                        yield combined

    def explain(self, indent=0):
        s = "  " * indent + "NestedLoopJoin"
        s += "\n" + self.left.explain(indent + 1)
        s += "\n" + self.right.explain(indent + 1)
        return s


class Filter(Op):
    def __init__(self, child: Op, predicate: A.Expr):
        self.child = child
        self.predicate = predicate

    def rows(self):
        for row in self.child.rows():
            if eval_expr(self.predicate, row) is True:
                yield row

    def explain(self, indent=0):
        s = "  " * indent + "Filter"
        s += "\n" + self.child.explain(indent + 1)
        return s


# ---- aggregate plumbing -------------------------------------------------
def _collect_aggregates(expr, out):
    if isinstance(expr, A.FuncCall):
        if expr.name in _AGG:
            out.append(expr)
        for a in expr.args:
            _collect_aggregates(a, out)
    elif isinstance(expr, A.BinaryOp):
        _collect_aggregates(expr.left, out)
        _collect_aggregates(expr.right, out)
    elif isinstance(expr, (A.UnaryOp,)):
        _collect_aggregates(expr.operand, out)
    elif isinstance(expr, A.IsNull):
        _collect_aggregates(expr.operand, out)
    elif isinstance(expr, A.InList):
        _collect_aggregates(expr.operand, out)
        for it in expr.items:
            _collect_aggregates(it, out)


def _agg_init(name):
    if name == "COUNT":
        return [0]
    if name == "SUM":
        return [None]
    if name == "AVG":
        return [0.0, 0]  # sum, count
    if name in ("MIN", "MAX"):
        return [None]


def _agg_step(name, state, value):
    if name == "COUNT":
        if value is not None:
            state[0] += 1
    elif name == "SUM":
        if value is not None:
            state[0] = value if state[0] is None else state[0] + value
    elif name == "AVG":
        if value is not None:
            state[0] += value
            state[1] += 1
    elif name == "MIN":
        if value is not None and (state[0] is None or _compare(value, state[0]) < 0):
            state[0] = value
    elif name == "MAX":
        if value is not None and (state[0] is None or _compare(value, state[0]) > 0):
            state[0] = value


def _agg_final(name, state):
    if name == "COUNT":
        return state[0]
    if name == "SUM":
        return state[0]
    if name == "AVG":
        return state[0] / state[1] if state[1] else None
    return state[0]


# ---- top-level SELECT execution ----------------------------------------
class Result:
    def __init__(self, columns: List[str], rows: List[tuple]):
        self.columns = columns
        self.rows = rows


def _output_columns(select: A.Select, relations) -> List[Tuple[A.Expr, str]]:
    """Expand the projection list into concrete (expr, output_name) pairs."""
    specs: List[Tuple[A.Expr, str]] = []
    for expr, alias in select.projections:
        if isinstance(expr, A.Star):
            targets = relations
            if expr.table is not None:
                targets = [r for r in relations if r[0] == expr.table.lower()]
                if not targets:
                    raise ExecError(f"no table or alias {expr.table!r} in scope")
            for ralias, schema in targets:
                for col in schema.columns:
                    specs.append((A.ColumnRef(ralias, col.name), col.name))
        else:
            name = alias or _expr_label(expr)
            specs.append((expr, name))
    return specs


def _expr_label(expr) -> str:
    if isinstance(expr, A.ColumnRef):
        return expr.name
    if isinstance(expr, A.FuncCall):
        if expr.star:
            return f"{expr.name}(*)"
        return f"{expr.name}({', '.join(_expr_label(a) for a in expr.args)})"
    if isinstance(expr, A.Literal):
        return repr(expr.value)
    if isinstance(expr, A.BinaryOp):
        return f"{_expr_label(expr.left)}{expr.op}{_expr_label(expr.right)}"
    if isinstance(expr, A.UnaryOp):
        return f"{expr.op}{_expr_label(expr.operand)}"
    return "expr"


def run_select(db, select: A.Select, source: Op, relations) -> Result:
    has_agg = bool(select.group_by)
    agg_nodes: List[A.FuncCall] = []
    for expr, _ in select.projections:
        if not isinstance(expr, A.Star):
            _collect_aggregates(expr, agg_nodes)
    if select.having is not None:
        _collect_aggregates(select.having, agg_nodes)
    for e, _ in select.order_by:
        _collect_aggregates(e, agg_nodes)
    if agg_nodes:
        has_agg = True

    specs = _output_columns(select, relations)

    # ORDER BY may reference output-column aliases; resolve them to the
    # underlying projection expression (keeping node identity so aggregate
    # values line up).
    alias_map = {name.lower(): expr for expr, name in specs}
    resolved_order = []
    for e, d in select.order_by:
        if isinstance(e, A.Literal) and isinstance(e.value, int) and not isinstance(e.value, bool):
            # positional: ORDER BY N -> N-th output column (1-based)
            n = e.value
            if 1 <= n <= len(specs):
                resolved_order.append((specs[n - 1][0], d))
            else:
                raise ExecError(f"ORDER BY position {n} is out of range")
        elif isinstance(e, A.ColumnRef) and e.table is None and e.name.lower() in alias_map:
            resolved_order.append((alias_map[e.name.lower()], d))
        else:
            resolved_order.append((e, d))

    if has_agg:
        out_rows = _run_aggregated(db, select, source, agg_nodes, specs, resolved_order)
    else:
        out_rows = _run_simple(db, select, source, specs, resolved_order)

    columns = [name for _, name in specs]
    return Result(columns, out_rows)


def _apply_order_offset_limit(rows_with_ctx, select, order):
    """rows_with_ctx: list of (bindings, agg_values)."""
    if order:
        for expr, desc in reversed(order):
            rows_with_ctx.sort(
                key=lambda rc, e=expr: _sortkey(eval_expr(e, rc[0], rc[1])),
                reverse=desc,
            )
    start = select.offset or 0
    if select.limit is not None:
        rows_with_ctx = rows_with_ctx[start : start + select.limit]
    elif start:
        rows_with_ctx = rows_with_ctx[start:]
    return rows_with_ctx


def _run_simple(db, select, source: Op, specs, order):
    rows_with_ctx = [(b, None) for b in source.rows()]
    rows_with_ctx = _apply_order_offset_limit(rows_with_ctx, select, order)
    out = []
    seen = set()
    for bindings, _ in rows_with_ctx:
        row = tuple(eval_expr(e, bindings) for e, _ in specs)
        if select.distinct:
            key = tuple(_sortkey(v) for v in row)
            if key in seen:
                continue
            seen.add(key)
        out.append(row)
    return out


def _run_aggregated(db, select, source: Op, agg_nodes, specs, order):
    groups = {}  # group_key -> [representative_bindings, {id(agg): state}]
    group_order = []
    for bindings in source.rows():
        if select.group_by:
            gkey = tuple(_sortkey(eval_expr(g, bindings)) for g in select.group_by)
        else:
            gkey = ()  # single group
        if gkey not in groups:
            states = {id(n): _agg_init(n.name) for n in agg_nodes}
            groups[gkey] = [bindings, states]
            group_order.append(gkey)
        states = groups[gkey][1]
        for n in agg_nodes:
            if n.star:
                _agg_step(n.name, states[id(n)], 1)
            else:
                val = eval_expr(n.args[0], bindings)
                _agg_step(n.name, states[id(n)], val)

    # Edge case: aggregate over empty input with no GROUP BY -> one row.
    if not groups and not select.group_by:
        states = {id(n): _agg_init(n.name) for n in agg_nodes}
        groups[()] = [[], states]
        group_order.append(())

    rows_with_ctx = []
    for gkey in group_order:
        bindings, states = groups[gkey]
        agg_values = {nid: _agg_final(_name_of(agg_nodes, nid), st) for nid, st in states.items()}
        if select.having is not None:
            hv = eval_expr(select.having, bindings, agg_values)
            if hv is not True:
                continue
        rows_with_ctx.append((bindings, agg_values))

    rows_with_ctx = _apply_order_offset_limit(rows_with_ctx, select, order)

    out = []
    seen = set()
    for bindings, agg_values in rows_with_ctx:
        row = tuple(eval_expr(e, bindings, agg_values) for e, _ in specs)
        if select.distinct:
            key = tuple(_sortkey(v) for v in row)
            if key in seen:
                continue
            seen.add(key)
        out.append(row)
    return out


def _name_of(agg_nodes, nid):
    for n in agg_nodes:
        if id(n) == nid:
            return n.name
    raise KeyError(nid)
