"""
AST -> WASM instruction-list codegen.

Instructions are represented as (opname, immediate) tuples using the opcode
names from wasm.OPCODES; encoder.py turns these into real binary bytes, and
interpreter.py's disassembler/decoder round-trips real binary back into the
same shape. Control flow (if/while) is compiled directly to WASM's
structured block/loop/if/br/br_if — Runic has no break/continue/goto, so
every branch target's relative depth is known statically at codegen time
and no separate label-resolution pass is needed.
"""

from . import ast_nodes as A
from .wasm import VALTYPE_I32, BLOCKTYPE_VOID, i32_wrap

BINOP_OPCODE = {
    "+": "i32.add",
    "-": "i32.sub",
    "*": "i32.mul",
    "/": "i32.div_s",
    "%": "i32.rem_s",
    "==": "i32.eq",
    "!=": "i32.ne",
    "<": "i32.lt_s",
    "<=": "i32.le_s",
    ">": "i32.gt_s",
    ">=": "i32.ge_s",
}


class CodegenError(Exception):
    pass


def compile_function(fn, info, checked):
    """Return (num_locals, list of (opname, imm) instructions) for one function."""
    out = []
    _gen_block(fn.body, info, checked, out)
    out.append(("end", None))  # implicit end of function body expr
    return len(info.locals), out


def _gen_block(block, info, checked, out):
    for stmt in block.stmts:
        _gen_stmt(stmt, info, checked, out)


def _gen_stmt(stmt, info, checked, out):
    if isinstance(stmt, A.LetStmt):
        _gen_expr(stmt.expr, info, checked, out)
        out.append(("local.set", info.local_index[stmt.name]))

    elif isinstance(stmt, A.AssignStmt):
        if isinstance(stmt.target, A.Ident):
            _gen_expr(stmt.expr, info, checked, out)
            out.append(("local.set", info.local_index[stmt.target.name]))
        else:  # A.Index
            _gen_array_addr(stmt.target, info, checked, out)
            _gen_expr(stmt.expr, info, checked, out)
            out.append(("i32.store", (2, 0)))

    elif isinstance(stmt, A.IfStmt):
        _gen_expr(stmt.cond, info, checked, out)
        out.append(("if", BLOCKTYPE_VOID))
        _gen_block(stmt.then_block, info, checked, out)
        if stmt.else_block is not None:
            out.append(("else", None))
            _gen_block(stmt.else_block, info, checked, out)
        out.append(("end", None))

    elif isinstance(stmt, A.WhileStmt):
        out.append(("block", BLOCKTYPE_VOID))
        out.append(("loop", BLOCKTYPE_VOID))
        _gen_expr(stmt.cond, info, checked, out)
        out.append(("i32.eqz", None))
        out.append(("br_if", 1))  # condition false -> exit outer block
        _gen_block(stmt.body, info, checked, out)
        out.append(("br", 0))  # loop back
        out.append(("end", None))  # end loop
        out.append(("end", None))  # end block

    elif isinstance(stmt, A.ReturnStmt):
        _gen_expr(stmt.expr, info, checked, out)
        out.append(("return", None))

    elif isinstance(stmt, A.ExprStmt):
        _gen_expr(stmt.expr, info, checked, out)
        out.append(("drop", None))

    elif isinstance(stmt, A.AssertStmt):
        # assert(cond): trap via the spec's own 'unreachable' opcode when
        # the condition is false. This reuses machinery (traps, dual-oracle
        # trap-parity checking) that already exists for div-by-zero, so a
        # failed assertion is verified against Node exactly like any other
        # trap — not a bolted-on, differently-tested code path.
        _gen_expr(stmt.expr, info, checked, out)
        out.append(("i32.eqz", None))
        out.append(("if", BLOCKTYPE_VOID))
        out.append(("unreachable", None))
        out.append(("end", None))

    elif isinstance(stmt, A.Block):
        _gen_block(stmt, info, checked, out)

    else:
        raise CodegenError(f"unhandled statement node {type(stmt)}")


def _gen_array_addr(index_node, info, checked, out):
    arr = checked.arrays_by_name[index_node.array_name]
    out.append(("i32.const", arr.base_offset))
    _gen_expr(index_node.index_expr, info, checked, out)
    out.append(("i32.const", 4))
    out.append(("i32.mul", None))
    out.append(("i32.add", None))


def _gen_truthy(out):
    """Normalize the i32 on top of the stack to a 0/1 boolean (val != 0)."""
    out.append(("i32.const", 0))
    out.append(("i32.ne", None))


def _gen_expr(expr, info, checked, out):
    if isinstance(expr, A.IntLit):
        # Runic source allows the literal to be written in either signed or
        # unsigned i32 range (e.g. both -1 and 4294967295 are legal and mean
        # the same bit pattern) — normalize to canonical signed range before
        # it ever reaches sleb128 encoding, since a raw unsigned value like
        # 4294967295 would otherwise encode as an oversized, non-canonical
        # varint that real WASM engines reject outright.
        out.append(("i32.const", i32_wrap(expr.value)))

    elif isinstance(expr, A.Ident):
        out.append(("local.get", info.local_index[expr.name]))

    elif isinstance(expr, A.Index):
        _gen_array_addr(expr, info, checked, out)
        out.append(("i32.load", (2, 0)))

    elif isinstance(expr, A.Call):
        for a in expr.args:
            _gen_expr(a, info, checked, out)
        callee = checked.funcs_by_name[expr.name]
        out.append(("call", callee.index))

    elif isinstance(expr, A.BinOp):
        if expr.op == "&&":
            _gen_expr(expr.left, info, checked, out)
            _gen_truthy(out)
            out.append(("if", VALTYPE_I32))
            _gen_expr(expr.right, info, checked, out)
            _gen_truthy(out)
            out.append(("else", None))
            out.append(("i32.const", 0))
            out.append(("end", None))
        elif expr.op == "||":
            _gen_expr(expr.left, info, checked, out)
            _gen_truthy(out)
            out.append(("if", VALTYPE_I32))
            out.append(("i32.const", 1))
            out.append(("else", None))
            _gen_expr(expr.right, info, checked, out)
            _gen_truthy(out)
            out.append(("end", None))
        else:
            _gen_expr(expr.left, info, checked, out)
            _gen_expr(expr.right, info, checked, out)
            out.append((BINOP_OPCODE[expr.op], None))

    elif isinstance(expr, A.UnaryOp):
        if expr.op == "-":
            out.append(("i32.const", 0))
            _gen_expr(expr.operand, info, checked, out)
            out.append(("i32.sub", None))
        elif expr.op == "!":
            _gen_expr(expr.operand, info, checked, out)
            out.append(("i32.eqz", None))
        else:
            raise CodegenError(f"unhandled unary op {expr.op!r}")

    else:
        raise CodegenError(f"unhandled expression node {type(expr)}")
