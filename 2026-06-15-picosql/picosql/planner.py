"""Query planner: turns a SELECT AST into an operator tree.

The interesting part is *index selection*: when a query filters the primary-key
column with `=` or range comparisons, the planner plans a B+tree IndexSeek /
IndexRange (O(log n)) instead of a full SeqScan, peeling those conjuncts out of
the WHERE clause and leaving the rest as a residual Filter.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ast_nodes as A
from .btree import BTree
from .catalog import TableSchema
from .executor import (Filter, IndexRange, IndexSeek, NestedLoopJoin, Op,
                       SeqScan, SingleRow)


def _flatten_and(expr: Optional[A.Expr]) -> List[A.Expr]:
    if expr is None:
        return []
    if isinstance(expr, A.BinaryOp) and expr.op == "AND":
        return _flatten_and(expr.left) + _flatten_and(expr.right)
    return [expr]


def _combine_and(conjuncts: List[A.Expr]) -> Optional[A.Expr]:
    if not conjuncts:
        return None
    out = conjuncts[0]
    for c in conjuncts[1:]:
        out = A.BinaryOp("AND", out, c)
    return out


def _is_pk_ref(expr, schema: TableSchema, alias: str) -> bool:
    if not isinstance(expr, A.ColumnRef):
        return False
    if schema.pk_col is None:
        return False
    if expr.name.lower() != schema.columns[schema.pk_col].name.lower():
        return False
    if expr.table is not None and expr.table.lower() != alias.lower():
        return False
    return True


def _const_int(expr) -> Optional[int]:
    if isinstance(expr, A.Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


def _as_pk_predicate(conj, schema, alias):
    """Return (kind, value) where kind in {eq,lt,le,gt,ge}, or None."""
    if not isinstance(conj, A.BinaryOp):
        return None
    op = conj.op
    flip = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
    if op not in ("=", "<", "<=", ">", ">="):
        return None
    # normalize so the pk column is on the left
    if _is_pk_ref(conj.left, schema, alias):
        val = _const_int(conj.right)
        kop = op
    elif _is_pk_ref(conj.right, schema, alias):
        val = _const_int(conj.left)
        kop = flip.get(op, op)
    else:
        return None
    if val is None:
        return None
    return {"=": "eq", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}[kop], val


def _choose_scan(pager, schema: TableSchema, alias: str, where: Optional[A.Expr]):
    """Return (Op, residual_where)."""
    tree = BTree(pager, schema.root_page)
    if where is None or schema.pk_col is None:
        return SeqScan(tree, schema, alias), where

    conjuncts = _flatten_and(where)
    eq_idx = None
    eq_val = None
    low = None
    high = None
    range_idx = []  # conjuncts consumed by a range bound
    for i, c in enumerate(conjuncts):
        pred = _as_pk_predicate(c, schema, alias)
        if pred is None:
            continue
        kind, val = pred
        if kind == "eq":
            if eq_idx is None:
                eq_idx, eq_val = i, val
        elif kind == "ge":
            low = val if low is None else max(low, val)
            range_idx.append(i)
        elif kind == "gt":
            low = val + 1 if low is None else max(low, val + 1)
            range_idx.append(i)
        elif kind == "le":
            high = val if high is None else min(high, val)
            range_idx.append(i)
        elif kind == "lt":
            high = val - 1 if high is None else min(high, val - 1)
            range_idx.append(i)

    if eq_idx is not None:
        residual = [c for j, c in enumerate(conjuncts) if j != eq_idx]
        return IndexSeek(tree, schema, alias, eq_val), _combine_and(residual)

    if low is not None or high is not None:
        residual = [c for i, c in enumerate(conjuncts) if i not in range_idx]
        return IndexRange(tree, schema, alias, low, high), _combine_and(residual)

    return SeqScan(tree, schema, alias), where


def build_source(db, select: A.Select) -> Tuple[Op, List[Tuple[str, TableSchema]]]:
    relations: List[Tuple[str, TableSchema]] = []
    if select.from_table is None:
        return SingleRow(), relations

    schema = db.require_table(select.from_table)
    alias = (select.from_alias or select.from_table)
    relations.append((alias.lower(), schema))

    if not select.joins:
        op, residual = _choose_scan(db.pager, schema, alias, select.where)
        if residual is not None:
            op = Filter(op, residual)
        return op, relations

    # With joins, scan everything and filter at the top (honest, simple).
    op: Op = SeqScan(BTree(db.pager, schema.root_page), schema, alias)
    for j in select.joins:
        jschema = db.require_table(j.table)
        jalias = (j.alias or j.table)
        relations.append((jalias.lower(), jschema))
        right = SeqScan(BTree(db.pager, jschema.root_page), jschema, jalias)
        op = NestedLoopJoin(op, right, j.on)
    if select.where is not None:
        op = Filter(op, select.where)
    return op, relations
