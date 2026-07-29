"""A constant-folding optimization pass -- Phase 4's stretch feature.

`fold_constants(program)` returns a *new* Program (the input is never
mutated) where every subexpression built entirely out of literals is
folded down to a single literal at compile time: `2 + 3 * 4` becomes
`14` before codegen ever sees it, so the JIT emits one `movabs rax, 14`
instead of a chain of loads, pushes, and arithmetic. `&&`/`||` fold too,
and do so consistently with their runtime short-circuit semantics: when
the left side is a known-constant that already decides the result
(`0 && anything`, `nonzero || anything`), the right subexpression is
dropped entirely rather than folded, matching the fact that the real
short-circuit codegen never evaluates it either -- dropping it is not a
behavior change, just doing at compile time what would happen at runtime
anyway.

Deliberately NOT folded: `/` and `%` where the divisor is a known-zero
constant, or where the operands are the INT64_MIN / -1 overflow case.
Folding those away would silently turn a program that's supposed to
raise a clean EmberRuntimeError at runtime into either a compile-time
Python exception or (worse) a wrong baked-in answer. Left as ordinary
runtime BinOps so the existing division-guard machinery still fires
exactly the way un-optimized code would.

The interpreter is deliberately never run against optimizer output --
it's the ground-truth oracle constant folding is checked against
(see tests/test_optimize.py and `ember demo`'s optimizer section), so it
always evaluates the original, unmodified AST.
"""

from dataclasses import replace

from .ast_nodes import (
    Program, FnDef, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)
from .interpreter import wrap64, c_div, c_mod
from .errors import EmberRuntimeError

_ARITH = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b}
_CMP = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _as_const(expr):
    """Returns the folded int64 value if expr is a literal, else None."""
    if isinstance(expr, IntLit):
        return wrap64(expr.value)
    if isinstance(expr, BoolLit):
        return 1 if expr.value else 0
    return None


def fold_constants(program: Program) -> Program:
    return Program([_fold_fn(fn) for fn in program.functions])


def _fold_fn(fn: FnDef) -> FnDef:
    return replace(fn, body=_fold_block(fn.body))


def _fold_block(block: Block) -> Block:
    return Block([_fold_stmt(s) for s in block.stmts])


def _fold_stmt(stmt):
    if isinstance(stmt, LetStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr))
    if isinstance(stmt, AssignStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr))
    if isinstance(stmt, IfStmt):
        return replace(
            stmt,
            cond=_fold_expr(stmt.cond),
            then_block=_fold_block(stmt.then_block),
            else_block=_fold_block(stmt.else_block) if stmt.else_block is not None else None,
        )
    if isinstance(stmt, WhileStmt):
        return replace(stmt, cond=_fold_expr(stmt.cond), body=_fold_block(stmt.body))
    if isinstance(stmt, ReturnStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr) if stmt.expr is not None else None)
    if isinstance(stmt, ExprStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr))
    if hasattr(stmt, "stmts"):
        return _fold_block(stmt)
    raise EmberRuntimeError(f"optimize: unhandled statement {stmt!r}")


def _fold_expr(expr):
    if isinstance(expr, (IntLit, BoolLit, VarRef)):
        return expr
    if isinstance(expr, UnaryOp):
        operand = _fold_expr(expr.operand)
        c = _as_const(operand)
        if c is not None:
            if expr.op == "-":
                return IntLit(wrap64(-c), expr.line)
            if expr.op == "!":
                return IntLit(1 if c == 0 else 0, expr.line)
        return replace(expr, operand=operand)
    if isinstance(expr, BinOp):
        return _fold_binop(expr)
    if isinstance(expr, Call):
        return replace(expr, args=[_fold_expr(a) for a in expr.args])
    raise EmberRuntimeError(f"optimize: unhandled expression {expr!r}")


def _fold_binop(expr: BinOp):
    op = expr.op
    left = _fold_expr(expr.left)

    if op == "&&":
        lc = _as_const(left)
        if lc == 0:
            return IntLit(0, expr.line)
        right = _fold_expr(expr.right)
        if lc == 1:
            rc = _as_const(right)
            return IntLit(1 if rc != 0 else 0, expr.line) if rc is not None else \
                BinOp("!=", right, IntLit(0, expr.line), expr.line)
        return replace(expr, left=left, right=right)
    if op == "||":
        lc = _as_const(left)
        if lc is not None and lc != 0:
            return IntLit(1, expr.line)
        right = _fold_expr(expr.right)
        if lc == 0:
            rc = _as_const(right)
            return IntLit(1 if rc != 0 else 0, expr.line) if rc is not None else \
                BinOp("!=", right, IntLit(0, expr.line), expr.line)
        return replace(expr, left=left, right=right)

    right = _fold_expr(expr.right)
    lc, rc = _as_const(left), _as_const(right)
    if lc is None or rc is None:
        return replace(expr, left=left, right=right)

    if op in _ARITH:
        return IntLit(wrap64(_ARITH[op](lc, rc)), expr.line)
    if op in _CMP:
        return IntLit(1 if _CMP[op](lc, rc) else 0, expr.line)
    if op in ("/", "%"):
        if rc == 0 or (lc == -(2 ** 63) and rc == -1):
            return replace(expr, left=left, right=right)  # let the runtime guard raise
        return IntLit(c_div(lc, rc) if op == "/" else c_mod(lc, rc), expr.line)
    raise EmberRuntimeError(f"optimize: unknown binary op {op!r}")
