"""A small static semantic-check pass, run by both the interpreter and
the JIT codegen before either does anything else.

Why this exists (found during Phase 3 adversarial review): the JIT
backend necessarily walks every statement in a function body to emit
code for it, including branches that never execute at runtime -- so an
assignment to an undeclared variable inside an `if` branch that happens
not to be taken made the *interpreter* return a perfectly normal result
(Python only walks the taken branch) while the *JIT* raised, for the
exact same program and the exact same input. Two backends disagreeing
about whether a program is even valid is worse than either of them being
wrong about a computed value -- it means "does this program work" has no
single answer. This module gives both backends one shared, eager
(control-flow-independent) notion of validity, checked once up front:

  * every function name is unique
  * every variable an expression reads, or a plain assignment writes, is
    either a parameter or `let`-declared *somewhere* in the function
    (matching the flat, non-block-scoped namespace both the interpreter
    and codegen already implement -- see codegen_x64._collect_locals)
  * every call target exists and is called with the right number of
    arguments
  * no expression/statement nests deeper than a safe bound, so a
    pathological (likely generated, not hand-written) program gets one
    clean error instead of each backend crashing on its own recursive
    walk with a raw Python RecursionError somewhere different
"""

from .ast_nodes import (
    Program, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)
from .errors import EmberRuntimeError

MAX_NESTING_DEPTH = 400


class SemanticError(EmberRuntimeError):
    pass


def _known_names(fn):
    names = set(fn.params)

    def walk_block(block: Block):
        for stmt in block.stmts:
            walk_stmt(stmt)

    def walk_stmt(stmt):
        if isinstance(stmt, LetStmt):
            names.add(stmt.name)
        elif isinstance(stmt, IfStmt):
            walk_block(stmt.then_block)
            if stmt.else_block is not None:
                walk_block(stmt.else_block)
        elif isinstance(stmt, WhileStmt):
            walk_block(stmt.body)
        elif hasattr(stmt, "stmts"):
            walk_block(stmt)

    walk_block(fn.body)
    return names


def check_program(program: Program):
    seen_names = set()
    for fn in program.functions:
        if fn.name in seen_names:
            raise SemanticError(f"line {fn.line}: function {fn.name!r} is defined more than once")
        seen_names.add(fn.name)

    by_name = {fn.name: fn for fn in program.functions}

    for fn in program.functions:
        known = _known_names(fn)
        _check_block(fn.body, fn, known, by_name, depth=0)


def _check_block(block: Block, fn, known, by_name, depth):
    depth += 1
    _check_depth(depth, fn)
    for stmt in block.stmts:
        _check_stmt(stmt, fn, known, by_name, depth)


def _check_depth(depth, fn):
    if depth > MAX_NESTING_DEPTH:
        raise SemanticError(
            f"function {fn.name!r} nests statements/expressions more than "
            f"{MAX_NESTING_DEPTH} levels deep; Ember enforces this bound so an "
            f"extreme (almost certainly generated, not hand-written) program "
            f"gets one clean error instead of an interpreter-stack crash"
        )


def _check_stmt(stmt, fn, known, by_name, depth):
    _check_depth(depth, fn)
    if isinstance(stmt, LetStmt):
        _check_expr(stmt.expr, fn, known, by_name, depth)
    elif isinstance(stmt, AssignStmt):
        if stmt.name not in known:
            raise SemanticError(
                f"line {stmt.line}: assignment to undeclared variable {stmt.name!r} "
                f"in function {fn.name!r}"
            )
        _check_expr(stmt.expr, fn, known, by_name, depth)
    elif isinstance(stmt, IfStmt):
        _check_expr(stmt.cond, fn, known, by_name, depth)
        _check_block(stmt.then_block, fn, known, by_name, depth)
        if stmt.else_block is not None:
            _check_block(stmt.else_block, fn, known, by_name, depth)
    elif isinstance(stmt, WhileStmt):
        _check_expr(stmt.cond, fn, known, by_name, depth)
        _check_block(stmt.body, fn, known, by_name, depth)
    elif isinstance(stmt, ReturnStmt):
        if stmt.expr is not None:
            _check_expr(stmt.expr, fn, known, by_name, depth)
    elif isinstance(stmt, ExprStmt):
        _check_expr(stmt.expr, fn, known, by_name, depth)
    elif hasattr(stmt, "stmts"):
        _check_block(stmt, fn, known, by_name, depth)


def _check_expr(expr, fn, known, by_name, depth):
    depth += 1
    _check_depth(depth, fn)
    if isinstance(expr, (IntLit, BoolLit)):
        return
    if isinstance(expr, VarRef):
        if expr.name not in known:
            raise SemanticError(
                f"line {expr.line}: undefined variable {expr.name!r} in function {fn.name!r}"
            )
        return
    if isinstance(expr, UnaryOp):
        _check_expr(expr.operand, fn, known, by_name, depth)
        return
    if isinstance(expr, BinOp):
        _check_expr(expr.left, fn, known, by_name, depth)
        _check_expr(expr.right, fn, known, by_name, depth)
        return
    if isinstance(expr, Call):
        target = by_name.get(expr.name)
        if target is None:
            available = ", ".join(sorted(by_name)) or "(none)"
            raise SemanticError(
                f"line {expr.line}: call to undefined function {expr.name!r}; defined: {available}"
            )
        if len(expr.args) != len(target.params):
            raise SemanticError(
                f"line {expr.line}: {expr.name!r} expects {len(target.params)} "
                f"argument(s), got {len(expr.args)}"
            )
        for a in expr.args:
            _check_expr(a, fn, known, by_name, depth)
        return
    raise SemanticError(f"semcheck: unhandled expression {expr!r}")
