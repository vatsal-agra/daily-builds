"""Walks a formula AST to a value, given a `Context` that resolves cell and
range references against already-computed cell values (the caller -- the
dependency graph / recalculation engine -- guarantees precedents are
computed before dependents, so every lookup here is safe)."""

from .ast_nodes import (
    NumberLit, StringLit, BoolLit, CellRef, RangeRef, UnaryOp, BinOp, FuncCall,
)
from .parser import NameRef
from .errors import TrellisError, DIV0, VALUE, REF, NAME
from .functions import FUNCTIONS, RangeValue, to_number, to_bool, to_display_str, is_number


class Context:
    """Abstract resolver the evaluator queries for cell/range values.

    `get_value(sheet_name_or_None, row, col)` must return the *already
    computed* value of that cell, or raise TrellisError(REF) if the sheet
    or address doesn't exist.
    """

    def get_value(self, sheet_name, row, col):
        raise NotImplementedError

    def get_range(self, sheet_name, r1, c1, r2, c2):
        rows = []
        for r in range(min(r1, r2), max(r1, r2) + 1):
            row = []
            for c in range(min(c1, c2), max(c1, c2) + 1):
                row.append(self.get_value(sheet_name, r, c))
            rows.append(row)
        return RangeValue(rows)


def evaluate(node, ctx):
    return _eval(node, ctx)


def _eval(node, ctx):
    if isinstance(node, NumberLit):
        return node.value
    if isinstance(node, StringLit):
        return node.value
    if isinstance(node, BoolLit):
        return node.value
    if isinstance(node, NameRef):
        raise TrellisError(NAME)
    if isinstance(node, CellRef):
        return ctx.get_value(node.sheet, node.row, node.col)
    if isinstance(node, RangeRef):
        return ctx.get_range(node.sheet, node.start.row, node.start.col, node.end.row, node.end.col)
    if isinstance(node, UnaryOp):
        return _eval_unary(node, ctx)
    if isinstance(node, BinOp):
        return _eval_binop(node, ctx)
    if isinstance(node, FuncCall):
        return _eval_funccall(node, ctx)
    raise AssertionError(f"unhandled AST node {node!r}")


def _eval_unary(node, ctx):
    if node.op == "%":
        v = _eval(node.operand, ctx)
        return to_number(v) / 100.0
    v = _eval(node.operand, ctx)
    n = to_number(v)
    return n if node.op == "+" else -n


def _eval_binop(node, ctx):
    op = node.op
    if op in ("=", "<>", "<", "<=", ">", ">="):
        left = _eval(node.left, ctx)
        right = _eval(node.right, ctx)
        return _compare(op, left, right)
    if op == "&":
        left = _eval(node.left, ctx)
        right = _eval(node.right, ctx)
        return to_display_str(left) + to_display_str(right)

    left = to_number(_eval(node.left, ctx))
    right = to_number(_eval(node.right, ctx))
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise TrellisError(DIV0)
        return left / right
    if op == "^":
        try:
            return left ** right
        except (ValueError, OverflowError, ZeroDivisionError):
            from .errors import NUM
            raise TrellisError(NUM)
    raise AssertionError(f"unhandled binop {op!r}")


def _compare(op, left, right):
    if isinstance(left, TrellisError):
        raise left
    if isinstance(right, TrellisError):
        raise right
    lk, lv = _order_key(left)
    rk, rv = _order_key(right)
    if lk != rk:
        result_lt = lk < rk
        eq = False
    else:
        eq = lv == rv
        result_lt = lv < rv if not eq else False
    if op == "=":
        return eq
    if op == "<>":
        return not eq
    if op == "<":
        return result_lt
    if op == ">":
        return (not result_lt) and (not eq)
    if op == "<=":
        return result_lt or eq
    if op == ">=":
        return (not result_lt) or eq
    raise AssertionError(op)


def _order_key(v):
    """Excel's cross-type ordering: numbers < text < booleans < blank
    is a common convention (blank sorts lowest in comparisons here since
    it's most often compared against 0/""); we use empty < number < text
    < boolean, consistent within a single evaluator rather than chasing
    every Excel edge case."""
    if v is None:
        return (0, 0)
    if is_number(v):
        return (1, v)
    if isinstance(v, str):
        return (2, v.upper())
    if isinstance(v, bool):
        return (3, v)
    return (4, str(v))


def _eval_funccall(node, ctx):
    name = node.name

    if name == "IF":
        if not (2 <= len(node.args) <= 3):
            raise TrellisError(VALUE)
        cond = to_bool(_eval(node.args[0], ctx))
        if cond:
            return _eval(node.args[1], ctx)
        if len(node.args) == 3:
            return _eval(node.args[2], ctx)
        return False

    if name == "IFERROR":
        if len(node.args) != 2:
            raise TrellisError(VALUE)
        try:
            return _eval(node.args[0], ctx)
        except TrellisError:
            return _eval(node.args[1], ctx)

    func = FUNCTIONS.get(name)
    if func is None:
        raise TrellisError(NAME)
    args = [_eval(a, ctx) for a in node.args]
    return func(args)
