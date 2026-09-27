"""AST -> runtime Value, given a cell-lookup callback."""

from . import parser as P
from . import values as V
from .functions import FUNCTIONS


class EvalContext:
    """`lookup(col, row) -> Value` resolves a single cell's current cached
    value. The evaluator never recurses into recomputing other cells
    itself — dependency-ordered recomputation is `sheet.py`'s job; by the
    time a formula is evaluated, every cell it can legally read is assumed
    already resolved (or correctly marked #CYCLE!)."""

    __slots__ = ("lookup",)

    def __init__(self, lookup):
        self.lookup = lookup


def evaluate(node, ctx):
    if isinstance(node, P.Number):
        return node.value
    if isinstance(node, P.Text):
        return node.value
    if isinstance(node, P.Bool):
        return node.value
    if isinstance(node, P.ErrorLit):
        return node.value
    if isinstance(node, P.CellRefNode):
        return ctx.lookup(node.ref.col, node.ref.row)
    if isinstance(node, P.RangeRefNode):
        return _resolve_range(node.range, ctx)
    if isinstance(node, P.UnaryOp):
        return _eval_unary(node, ctx)
    if isinstance(node, P.BinOp):
        return _eval_binop(node, ctx)
    if isinstance(node, P.FuncCall):
        return _eval_funccall(node, ctx)
    raise TypeError(f"unknown AST node {node!r}")


def _resolve_range(range_ref, ctx):
    """A range resolves to a 2D list of rows, each a list of scalar
    values — the shape VLOOKUP's table argument needs; aggregate functions
    flatten it via values.flatten()."""
    min_c, min_r, max_c, max_r = range_ref.normalized_bounds()
    rows = []
    for r in range(min_r, max_r + 1):
        rows.append([ctx.lookup(c, r) for c in range(min_c, max_c + 1)])
    return rows


def _as_scalar(v, op_name="operator"):
    """Binary/unary operators only accept scalars; a bare range used
    outside a function call (e.g. `=A1:A2+1`) is only meaningful if it
    happens to be exactly one cell, matching Excel's implicit-intersection
    fallback in the simple cases; anything wider is #VALUE!."""
    if isinstance(v, list):
        flat = V.flatten(v)
        if len(flat) == 1:
            return flat[0]
        return V.VALUE
    return v


def _eval_unary(node, ctx):
    operand = _as_scalar(evaluate(node.operand, ctx))
    if V.is_error(operand):
        return operand
    n = V.to_number(operand)
    if V.is_error(n):
        return n
    if node.op == "-":
        return -n
    return n  # unary '+'


_ARITH = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "^": lambda a, b: _power(a, b),
}


def _power(a, b):
    try:
        result = a ** b
    except (OverflowError, ValueError):
        return V.NUM
    if isinstance(result, complex):
        return V.NUM
    if isinstance(result, float) and (result != result or result in (float("inf"), float("-inf"))):
        return V.NUM
    return result


def _eval_binop(node, ctx):
    left = _as_scalar(evaluate(node.left, ctx))
    if V.is_error(left):
        return left
    right = _as_scalar(evaluate(node.right, ctx))
    if V.is_error(right):
        return right

    op = node.op
    if op in ("=", "<>", "<", "<=", ">", ">="):
        return _compare(op, left, right)
    if op == "&":
        lt = V.to_text(left)
        if V.is_error(lt):
            return lt
        rt = V.to_text(right)
        if V.is_error(rt):
            return rt
        return lt + rt
    if op == "/":
        ln = V.to_number(left)
        if V.is_error(ln):
            return ln
        rn = V.to_number(right)
        if V.is_error(rn):
            return rn
        if rn == 0:
            return V.DIV0
        return ln / rn
    # + - * ^
    ln = V.to_number(left)
    if V.is_error(ln):
        return ln
    rn = V.to_number(right)
    if V.is_error(rn):
        return rn
    return _ARITH[op](ln, rn)


def _type_rank(v):
    """Excel's cross-type ordering: blank < number < text < boolean, so
    e.g. `="abc">5` is TRUE (any text outranks any number) and
    `=TRUE>"abc"` is also TRUE (any boolean outranks any text)."""
    if v is None:
        return -1
    if isinstance(v, bool):
        return 2
    if isinstance(v, float):
        return 0
    return 1


def _compare(op, a, b):
    """Excel compares within a type (numbers numerically, text
    case-insensitively) and ranks blank < number < text < boolean across
    types."""
    ra, rb = _type_rank(a), _type_rank(b)
    if ra == rb:
        if ra == 0:  # both numbers
            x, y = a, b
        elif ra == 1:  # both text
            x, y = a.upper(), b.upper()
        elif ra == 2:  # both bool
            x, y = a, b
        else:  # both blank
            x, y = 0, 0
    else:
        x, y = ra, rb
    if op == "=":
        result = x == y
    elif op == "<>":
        result = x != y
    elif op == "<":
        result = x < y
    elif op == "<=":
        result = x <= y
    elif op == ">":
        result = x > y
    else:
        result = x >= y
    return result


def _eval_funccall(node, ctx):
    fn = FUNCTIONS.get(node.name)
    if fn is None:
        return V.NAME
    args = [evaluate(a, ctx) for a in node.args]
    err = V.first_error(*args)
    # Most functions should short-circuit on an errored argument, except
    # IFERROR/IF, which are explicitly designed to inspect/consume one.
    if err is not None and node.name not in ("IFERROR", "IF", "ISERROR"):
        return err
    return fn(args)
