"""Indented-tree AST pretty-printer, used by the `ember ast` CLI command
and the HTML report (viz)."""

from .ast_nodes import (
    Program, FnDef, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)


def _fmt_expr(expr) -> str:
    if isinstance(expr, IntLit):
        return str(expr.value)
    if isinstance(expr, BoolLit):
        return "true" if expr.value else "false"
    if isinstance(expr, VarRef):
        return expr.name
    if isinstance(expr, UnaryOp):
        return f"{expr.op}{_fmt_expr(expr.operand)}"
    if isinstance(expr, BinOp):
        return f"({_fmt_expr(expr.left)} {expr.op} {_fmt_expr(expr.right)})"
    if isinstance(expr, Call):
        return f"{expr.name}({', '.join(_fmt_expr(a) for a in expr.args)})"
    return repr(expr)


def _lines_for_stmt(stmt, prefix):
    if isinstance(stmt, LetStmt):
        yield f"{prefix}Let {stmt.name} = {_fmt_expr(stmt.expr)}"
    elif isinstance(stmt, AssignStmt):
        yield f"{prefix}Assign {stmt.name} = {_fmt_expr(stmt.expr)}"
    elif isinstance(stmt, IfStmt):
        yield f"{prefix}If {_fmt_expr(stmt.cond)}"
        yield f"{prefix}  then:"
        for s in stmt.then_block.stmts:
            yield from _lines_for_stmt(s, prefix + "    ")
        if stmt.else_block is not None:
            yield f"{prefix}  else:"
            for s in stmt.else_block.stmts:
                yield from _lines_for_stmt(s, prefix + "    ")
    elif isinstance(stmt, WhileStmt):
        yield f"{prefix}While {_fmt_expr(stmt.cond)}"
        for s in stmt.body.stmts:
            yield from _lines_for_stmt(s, prefix + "    ")
    elif isinstance(stmt, ReturnStmt):
        yield f"{prefix}Return {_fmt_expr(stmt.expr) if stmt.expr is not None else ''}"
    elif isinstance(stmt, ExprStmt):
        yield f"{prefix}ExprStmt {_fmt_expr(stmt.expr)}"
    elif hasattr(stmt, "stmts"):
        yield f"{prefix}Block"
        for s in stmt.stmts:
            yield from _lines_for_stmt(s, prefix + "    ")


def format_program(program: Program) -> str:
    lines = []
    for fn in program.functions:
        lines.append(f"fn {fn.name}({', '.join(fn.params)})")
        for stmt in fn.body.stmts:
            lines.extend(_lines_for_stmt(stmt, "  "))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_fn(fn: FnDef) -> str:
    lines = [f"fn {fn.name}({', '.join(fn.params)})"]
    for stmt in fn.body.stmts:
        lines.extend(_lines_for_stmt(stmt, "  "))
    return "\n".join(lines)
