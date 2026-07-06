"""Evaluates a parsed formula AST against a workbook context."""

import math

from .ast_nodes import Number, String, Bool, CellRef, RangeRef, FuncCall, UnaryOp, PostfixOp, BinOp
from .errors import ErrorValue, FormulaError, DIV0, VALUE, NUM, REF, NAME as NAME_ERR, to_number, to_string, to_bool
from .functions import EAGER_FUNCTIONS, LAZY_FUNCTION_NAMES
from .values import RangeValue, flatten_args


class EvalContext:
    """Supplies cell/range lookups for the sheet a formula lives in."""

    def __init__(self, workbook, sheet_name):
        self.workbook = workbook
        self.sheet_name = sheet_name

    def get_value(self, sheet, row, col):
        name = sheet or self.sheet_name
        target = self.workbook.sheets.get(name)
        if target is None:
            raise FormulaError(REF)
        if row < 0 or col < 0:
            raise FormulaError(REF)
        return target.get_computed(row, col)

    def get_range(self, sheet, r1, c1, r2, c2):
        name = sheet or self.sheet_name
        target = self.workbook.sheets.get(name)
        if target is None:
            raise FormulaError(REF)
        if r1 < 0 or c1 < 0 or r2 < 0 or c2 < 0:
            raise FormulaError(REF)
        lo_r, hi_r = min(r1, r2), max(r1, r2)
        lo_c, hi_c = min(c1, c2), max(c1, c2)
        rows = []
        for r in range(lo_r, hi_r + 1):
            rows.append([target.get_computed(r, c) for c in range(lo_c, hi_c + 1)])
        return RangeValue(rows)


def evaluate(node, ctx):
    """Evaluate an AST node to a scalar value or ErrorValue (never raises FormulaError)."""
    try:
        return _eval(node, ctx)
    except FormulaError as e:
        return ErrorValue(e.code)


def _eval(node, ctx):
    if isinstance(node, Number):
        return node.value
    if isinstance(node, String):
        return node.value
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, CellRef):
        return ctx.get_value(node.sheet, node.row, node.col)
    if isinstance(node, RangeRef):
        return ctx.get_range(node.sheet, node.start.row, node.start.col, node.end.row, node.end.col)
    if isinstance(node, UnaryOp):
        v = to_number(_eval(node.operand, ctx))
        return -v
    if isinstance(node, PostfixOp):
        v = to_number(_eval(node.operand, ctx))
        return v / 100.0
    if isinstance(node, BinOp):
        return _eval_binop(node, ctx)
    if isinstance(node, FuncCall):
        return _eval_funccall(node, ctx)
    raise TypeError(f"unknown AST node {node!r}")


def _eval_binop(node, ctx):
    op = node.op
    if op in ("=", "<>", "<", "<=", ">", ">="):
        left = _eval(node.left, ctx)
        right = _eval(node.right, ctx)
        return _compare(op, left, right)
    if op == "&":
        left = to_string(_eval(node.left, ctx))
        right = to_string(_eval(node.right, ctx))
        return left + right
    left = to_number(_eval(node.left, ctx))
    right = to_number(_eval(node.right, ctx))
    if op == "+":
        result = left + right
    elif op == "-":
        result = left - right
    elif op == "*":
        result = left * right
    elif op == "/":
        if right == 0:
            raise FormulaError(DIV0)
        result = left / right
    elif op == "^":
        try:
            result = left ** right
        except (ValueError, OverflowError):
            raise FormulaError(NUM)
    else:
        raise TypeError(f"unknown operator {op!r}")
    if isinstance(result, complex) or not math.isfinite(result):
        raise FormulaError(NUM)
    return result


def _compare(op, left, right):
    if isinstance(left, ErrorValue):
        raise FormulaError(left.code)
    if isinstance(right, ErrorValue):
        raise FormulaError(right.code)
    lk, lv = _compare_key(left)
    rk, rv = _compare_key(right)
    if lk != rk:
        # Excel's total order across types: numbers < text < booleans (blank treated as its peer type)
        result = lk < rk
        if op == "=":
            return False
        if op == "<>":
            return True
        if op == "<":
            return result
        if op == "<=":
            return result
        if op == ">":
            return not result
        if op == ">=":
            return not result
    if op == "=":
        return lv == rv
    if op == "<>":
        return lv != rv
    if op == "<":
        return lv < rv
    if op == "<=":
        return lv <= rv
    if op == ">":
        return lv > rv
    if op == ">=":
        return lv >= rv
    raise TypeError(op)


def _compare_key(v):
    if v is None:
        return (0, 0.0)
    if isinstance(v, bool):
        return (2, v)
    if isinstance(v, (int, float)):
        return (0, float(v))
    return (1, str(v).upper())


def _eval_funccall(node, ctx):
    name = node.name.upper()
    if name in LAZY_FUNCTION_NAMES:
        return _eval_lazy(name, node.args, ctx)
    if name not in EAGER_FUNCTIONS:
        raise FormulaError(NAME_ERR)
    args = [_eval(a, ctx) for a in node.args]
    for a in args:
        if isinstance(a, ErrorValue) and name not in ("ISERROR",):
            raise FormulaError(a.code)
    return EAGER_FUNCTIONS[name](args)


def _eval_lazy(name, arg_nodes, ctx):
    if name == "IF":
        if len(arg_nodes) not in (2, 3):
            raise FormulaError(VALUE)
        cond = to_bool(_eval(arg_nodes[0], ctx))
        if cond:
            return _eval(arg_nodes[1], ctx)
        if len(arg_nodes) == 3:
            return _eval(arg_nodes[2], ctx)
        return False
    if name == "IFERROR":
        if len(arg_nodes) != 2:
            raise FormulaError(VALUE)
        try:
            v = _eval(arg_nodes[0], ctx)
        except FormulaError:
            return _eval(arg_nodes[1], ctx)
        if isinstance(v, ErrorValue):
            return _eval(arg_nodes[1], ctx)
        return v
    raise TypeError(name)
