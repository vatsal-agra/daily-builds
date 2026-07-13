"""Compiles a Pebble AST (parser.py) into a real WASM Module IR. Every
Pebble value is i32; every function takes N i32 params and returns one i32.
`print(expr)` lowers to a call into an imported host function
(`env.print`), so a compiled Pebble program only produces observable
output through a real WASM import — exercising the same linking path a
production embedder would use."""

from ..wasm.types import Module, FuncType, Import, Export, Function
from ..wasm.decoder import Instr
from . import parser as ast

I32 = 0x7F


class PebbleCompileError(Exception):
    pass


def compile_program(funcdecls, entry_export=None):
    m = Module()
    m.types.append(FuncType((I32,), ()))
    m.imports.append(Import("env", "print", "func", type_index=0))
    n_imported = 1

    func_index = {}
    for i, f in enumerate(funcdecls):
        func_index[f.name] = n_imported + i

    for f in funcdecls:
        ftype = FuncType(tuple(I32 for _ in f.params), (I32,))
        m.types.append(ftype)

    compiled = []
    for i, f in enumerate(funcdecls):
        type_index = 1 + i
        body, nlocals = _compile_func(f, func_index)
        compiled.append(Function(type_index, [I32] * nlocals, body))
    m.functions = compiled

    for f in funcdecls:
        m.exports.append(Export(f.name, "func", func_index[f.name]))
    if entry_export and entry_export not in func_index:
        raise PebbleCompileError(f"no such function to export as entry point: {entry_export}")

    return m, func_index


class _FuncCtx:
    def __init__(self, params, func_index):
        self.locals = {name: i for i, name in enumerate(params)}
        self.next_local = len(params)
        self.func_index = func_index

    def declare(self, name):
        if name in self.locals:
            raise PebbleCompileError(f"redeclaration of {name!r}")
        idx = self.next_local
        self.locals[name] = idx
        self.next_local += 1
        return idx

    def lookup(self, name):
        if name not in self.locals:
            raise PebbleCompileError(f"undefined variable {name!r}")
        return self.locals[name]


def _compile_func(f, func_index):
    ctx = _FuncCtx(f.params, func_index)
    body = []
    for stmt in f.body:
        body.extend(_compile_stmt(stmt, ctx))
    body.append(Instr("i32.const", 0x41, 0))  # implicit fallthrough result
    return body, ctx.next_local - len(f.params)


def _compile_block(stmts, ctx):
    out = []
    for s in stmts:
        out.extend(_compile_stmt(s, ctx))
    return out


def _compile_stmt(s, ctx):
    if isinstance(s, ast.Let):
        idx = ctx.declare(s.name)
        return _compile_expr(s.expr, ctx) + [Instr("local.set", 0x21, idx)]
    if isinstance(s, ast.Assign):
        idx = ctx.lookup(s.name)
        return _compile_expr(s.expr, ctx) + [Instr("local.set", 0x21, idx)]
    if isinstance(s, ast.Return):
        return _compile_expr(s.expr, ctx) + [Instr("return", 0x0F)]
    if isinstance(s, ast.Print):
        return _compile_expr(s.expr, ctx) + [Instr("call", 0x10, 0)]
    if isinstance(s, ast.ExprStmt):
        return _compile_expr(s.expr, ctx) + [Instr("drop", 0x1A)]
    if isinstance(s, ast.If):
        cond = _compile_expr(s.cond, ctx)
        then_body = _compile_block(s.then_body, ctx)
        else_body = _compile_block(s.else_body, ctx) if s.else_body else None
        return cond + [Instr("if", 0x04, None, then_body, else_body)]
    if isinstance(s, ast.While):
        cond = _compile_expr(s.cond, ctx)
        body = _compile_block(s.body, ctx)
        loop_body = cond + [Instr("i32.eqz", 0x45), Instr("br_if", 0x0D, 1)] + body + [Instr("br", 0x0C, 0)]
        loop_instr = Instr("loop", 0x03, None, loop_body)
        return [Instr("block", 0x02, None, [loop_instr])]
    raise PebbleCompileError(f"unhandled statement {s!r}")


_CMP_OPS = {
    "==": "i32.eq", "!=": "i32.ne", "<": "i32.lt_s", ">": "i32.gt_s",
    "<=": "i32.le_s", ">=": "i32.ge_s",
}
_ARITH_OPS = {
    "+": "i32.add", "-": "i32.sub", "*": "i32.mul", "/": "i32.div_s", "%": "i32.rem_s",
}


def _op_instr(name):
    from ..wasm import opcodes as ops
    opcode, _ = ops.BY_NAME[name]
    return Instr(name, opcode)


def _compile_expr(e, ctx):
    if isinstance(e, ast.IntLit):
        return [Instr("i32.const", 0x41, e.value & 0xFFFFFFFF)]
    if isinstance(e, ast.Var):
        return [Instr("local.get", 0x20, ctx.lookup(e.name))]
    if isinstance(e, ast.UnaryOp) and e.op == "-":
        return [Instr("i32.const", 0x41, 0)] + _compile_expr(e.expr, ctx) + [_op_instr("i32.sub")]
    if isinstance(e, ast.Call):
        if e.name not in ctx.func_index:
            raise PebbleCompileError(f"call to undefined function {e.name!r}")
        args = []
        for a in e.args:
            args.extend(_compile_expr(a, ctx))
        return args + [Instr("call", 0x10, ctx.func_index[e.name])]
    if isinstance(e, ast.BinOp):
        if e.op == "&&":
            left = _compile_expr(e.left, ctx)
            right = _compile_expr(e.right, ctx)
            return left + [Instr("if", 0x04, I32,
                                  right + _bool_normalize(),
                                  [Instr("i32.const", 0x41, 0)])]
        if e.op == "||":
            left = _compile_expr(e.left, ctx)
            right = _compile_expr(e.right, ctx)
            return left + [Instr("if", 0x04, I32,
                                  [Instr("i32.const", 0x41, 1)],
                                  right + _bool_normalize())]
        left = _compile_expr(e.left, ctx)
        right = _compile_expr(e.right, ctx)
        if e.op in _ARITH_OPS:
            return left + right + [_op_instr(_ARITH_OPS[e.op])]
        if e.op in _CMP_OPS:
            return left + right + [_op_instr(_CMP_OPS[e.op])]
        raise PebbleCompileError(f"unknown operator {e.op!r}")
    raise PebbleCompileError(f"unhandled expression {e!r}")


def _bool_normalize():
    # Coerces any nonzero i32 to canonical 1, so `&&`/`||` results are
    # always exactly 0 or 1 regardless of the sub-expression's magnitude.
    return [Instr("i32.const", 0x41, 0), _op_instr("i32.ne")]
