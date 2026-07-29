"""AST -> C, so the box's real `gcc` can serve as a second, fully
independent semantic oracle: the same source program, translated to C
by a from-scratch transpiler sharing no code with either the
interpreter or the x86-64 codegen, compiled by a production compiler,
and run as a subprocess. Its printed answer has to match both the
interpreter's and the JIT's for every test program.

Two things intentionally are NOT cross-checked against gcc:
  * division by zero and INT64_MIN / -1 are undefined behavior in C, so
    those inputs are only checked against the interpreter/JIT (which
    both define them as a clean EmberRuntimeError -- a stronger
    contract than C gives you, not a weaker one).
  * integer overflow of `+`/`-`/`*` on *signed* types is technically UB
    in C too, even though every real compiler on this box wraps it the
    same two's-complement way x86 hardware does; the C harness compiles
    with `-fwrapv`, which pins GCC to defined wraparound semantics
    instead of relying on the platform default, so the oracle is exact
    rather than "usually agrees".
"""

import subprocess
import tempfile
import os

from .ast_nodes import (
    Program, FnDef, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)
from .errors import EmberRuntimeError
from .interpreter import wrap64

_OP_MAP = {
    "+": "+", "-": "-", "*": "*", "/": "/", "%": "%",
    "<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "==", "!=": "!=",
    "&&": "&&", "||": "||",
}


def _expr_to_c(expr) -> str:
    if isinstance(expr, IntLit):
        return f"INT64_C({wrap64(expr.value)})"
    if isinstance(expr, BoolLit):
        return "1" if expr.value else "0"
    if isinstance(expr, VarRef):
        return expr.name
    if isinstance(expr, UnaryOp):
        inner = _expr_to_c(expr.operand)
        return f"(-({inner}))" if expr.op == "-" else f"(!({inner}))"
    if isinstance(expr, BinOp):
        l, r = _expr_to_c(expr.left), _expr_to_c(expr.right)
        return f"({l} {_OP_MAP[expr.op]} {r})"
    if isinstance(expr, Call):
        args = ", ".join(_expr_to_c(a) for a in expr.args)
        return f"{expr.name}({args})"
    raise EmberRuntimeError(f"transpile_c: unhandled expression {expr!r}")


def _block_to_c(block: Block, indent: str) -> str:
    lines = []
    for stmt in block.stmts:
        lines.append(_stmt_to_c(stmt, indent))
    return "\n".join(lines)


def _stmt_to_c(stmt, indent: str) -> str:
    if isinstance(stmt, LetStmt):
        return f"{indent}int64_t {stmt.name} = {_expr_to_c(stmt.expr)};"
    if isinstance(stmt, AssignStmt):
        return f"{indent}{stmt.name} = {_expr_to_c(stmt.expr)};"
    if isinstance(stmt, IfStmt):
        out = f"{indent}if ({_expr_to_c(stmt.cond)}) {{\n"
        out += _block_to_c(stmt.then_block, indent + "    ") + "\n"
        out += f"{indent}}}"
        if stmt.else_block is not None:
            out += f" else {{\n" + _block_to_c(stmt.else_block, indent + "    ") + f"\n{indent}}}"
        return out
    if isinstance(stmt, WhileStmt):
        out = f"{indent}while ({_expr_to_c(stmt.cond)}) {{\n"
        out += _block_to_c(stmt.body, indent + "    ") + "\n"
        out += f"{indent}}}"
        return out
    if isinstance(stmt, ReturnStmt):
        if stmt.expr is not None:
            return f"{indent}return {_expr_to_c(stmt.expr)};"
        return f"{indent}return 0;"
    if isinstance(stmt, ExprStmt):
        return f"{indent}(void)({_expr_to_c(stmt.expr)});"
    if hasattr(stmt, "stmts"):
        return f"{indent}{{\n" + _block_to_c(stmt, indent + '    ') + f"\n{indent}}}"
    raise EmberRuntimeError(f"transpile_c: unhandled statement {stmt!r}")


def _fn_signature(fn: FnDef) -> str:
    params = ", ".join(f"int64_t {p}" for p in fn.params) or "void"
    return f"int64_t {fn.name}({params})"


def transpile(program: Program) -> str:
    """AST -> a compilable C translation unit (prototypes + definitions,
    no main() -- see emit_c_source for the runnable harness version)."""
    parts = [
        "#include <stdint.h>",
        "",
        "// Falls off the end of a function with no `return` -> 0, matching",
        "// both Ember's interpreter and its JIT.",
        "",
    ]
    for fn in program.functions:
        parts.append(_fn_signature(fn) + ";")
    parts.append("")
    for fn in program.functions:
        parts.append(_fn_signature(fn) + " {")
        parts.append(_block_to_c(fn.body, "    "))
        parts.append("    return 0;")
        parts.append("}")
        parts.append("")
    return "\n".join(parts)


def emit_c_source(program: Program, entry_name: str, args) -> str:
    fn = next((f for f in program.functions if f.name == entry_name), None)
    if fn is None:
        raise EmberRuntimeError(f"transpile_c: no function named {entry_name!r}")
    if len(fn.params) != len(args):
        raise EmberRuntimeError(
            f"transpile_c: {entry_name!r} expects {len(fn.params)} argument(s), got {len(args)}"
        )
    body = transpile(program)
    arg_list = ", ".join(f"INT64_C({a})" for a in args)
    main_src = (
        "\n#include <stdio.h>\n"
        "#include <inttypes.h>\n"
        "int main(void) {\n"
        f"    int64_t result = {entry_name}({arg_list});\n"
        '    printf("%" PRId64 "\\n", result);\n'
        "    return 0;\n"
        "}\n"
    )
    return body + main_src


def gcc_available() -> bool:
    try:
        subprocess.run(["gcc", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def run_via_gcc(program: Program, entry_name: str, args) -> int:
    """Transpile, compile with the box's real gcc (-fwrapv for defined
    signed-overflow wraparound), run the binary, and return the int64 it
    printed."""
    source = emit_c_source(program, entry_name, args)
    with tempfile.TemporaryDirectory() as tmp:
        c_path = os.path.join(tmp, "prog.c")
        bin_path = os.path.join(tmp, "prog")
        with open(c_path, "w") as f:
            f.write(source)
        compile_proc = subprocess.run(
            ["gcc", "-O2", "-fwrapv", "-o", bin_path, c_path],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            raise EmberRuntimeError(f"gcc compile failed:\n{compile_proc.stderr}")
        run_proc = subprocess.run([bin_path], capture_output=True, text=True, timeout=30)
        if run_proc.returncode != 0:
            raise EmberRuntimeError(f"gcc-compiled program exited {run_proc.returncode}: {run_proc.stderr}")
        return int(run_proc.stdout.strip())
