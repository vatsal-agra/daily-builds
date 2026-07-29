"""Tree-walking reference interpreter.

This is the ground-truth semantics oracle: the JIT backend (codegen_x64)
and the C transpiler (transpile_c) are both checked against whatever this
module computes. Its int64 arithmetic wraps exactly the way a real CPU's
64-bit registers do (see wrap64) so that "the interpreter disagrees with
the JIT because Python ints don't overflow" is never a valid excuse for a
mismatch -- both sides implement the same 64-bit machine.
"""

from .ast_nodes import (
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)
from .errors import EmberRuntimeError
from .semcheck import check_program

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1
MASK64 = (1 << 64) - 1


def wrap64(x: int) -> int:
    x &= MASK64
    if x >= 0x8000000000000000:
        x -= 1 << 64
    return x


def c_div(a: int, b: int) -> int:
    """Truncating (toward zero) integer division, matching x86 IDIV."""
    if b == 0:
        raise EmberRuntimeError("division by zero")
    if a == INT64_MIN and b == -1:
        raise EmberRuntimeError("integer overflow: INT64_MIN / -1")
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return wrap64(q)


def c_mod(a: int, b: int) -> int:
    if b == 0:
        raise EmberRuntimeError("division by zero")
    if a == INT64_MIN and b == -1:
        raise EmberRuntimeError("integer overflow: INT64_MIN / -1")
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return wrap64(a - q * b)


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class Interpreter:
    def __init__(self, program):
        check_program(program)
        self.functions = {fn.name: fn for fn in program.functions}

    def call(self, name: str, args):
        if name not in self.functions:
            available = ", ".join(sorted(self.functions)) or "(none)"
            raise EmberRuntimeError(f"call to undefined function {name!r}; defined: {available}")
        fn = self.functions[name]
        if len(args) != len(fn.params):
            raise EmberRuntimeError(
                f"function {name!r} expects {len(fn.params)} argument(s), got {len(args)}"
            )
        env = {p: wrap64(a) for p, a in zip(fn.params, args)}
        try:
            self._exec_block(fn.body, env)
        except _Return as r:
            return wrap64(r.value)
        # Falling off the end of a function with no `return` yields 0,
        # matching the JIT (whose epilogue leaves rax at its last-written
        # value, defaulted to 0 at function entry) -- documented, not a bug.
        return 0

    def _exec_block(self, block, env):
        for stmt in block.stmts:
            self._exec_stmt(stmt, env)

    def _exec_stmt(self, stmt, env):
        if isinstance(stmt, LetStmt):
            env[stmt.name] = self._eval(stmt.expr, env)
        elif isinstance(stmt, AssignStmt):
            if stmt.name not in env:
                raise EmberRuntimeError(f"line {stmt.line}: assignment to undeclared variable {stmt.name!r}")
            env[stmt.name] = self._eval(stmt.expr, env)
        elif isinstance(stmt, IfStmt):
            if self._eval(stmt.cond, env) != 0:
                self._exec_block(stmt.then_block, env)
            elif stmt.else_block is not None:
                self._exec_block(stmt.else_block, env)
        elif isinstance(stmt, WhileStmt):
            while self._eval(stmt.cond, env) != 0:
                self._exec_block(stmt.body, env)
        elif isinstance(stmt, ReturnStmt):
            value = self._eval(stmt.expr, env) if stmt.expr is not None else 0
            raise _Return(value)
        elif isinstance(stmt, ExprStmt):
            self._eval(stmt.expr, env)
        elif hasattr(stmt, "stmts"):  # a bare nested Block
            self._exec_block(stmt, env)
        else:
            raise EmberRuntimeError(f"interpreter: unhandled statement {stmt!r}")

    def _eval(self, expr, env):
        if isinstance(expr, IntLit):
            return wrap64(expr.value)
        if isinstance(expr, BoolLit):
            return 1 if expr.value else 0
        if isinstance(expr, VarRef):
            if expr.name not in env:
                raise EmberRuntimeError(f"line {expr.line}: undefined variable {expr.name!r}")
            return env[expr.name]
        if isinstance(expr, UnaryOp):
            v = self._eval(expr.operand, env)
            if expr.op == "-":
                return wrap64(-v)
            if expr.op == "!":
                return 1 if v == 0 else 0
            raise EmberRuntimeError(f"interpreter: unknown unary op {expr.op!r}")
        if isinstance(expr, BinOp):
            return self._eval_binop(expr, env)
        if isinstance(expr, Call):
            args = [self._eval(a, env) for a in expr.args]
            return self.call(expr.name, args)
        raise EmberRuntimeError(f"interpreter: unhandled expression {expr!r}")

    def _eval_binop(self, expr, env):
        op = expr.op
        if op == "&&":
            left = self._eval(expr.left, env)
            if left == 0:
                return 0
            return 1 if self._eval(expr.right, env) != 0 else 0
        if op == "||":
            left = self._eval(expr.left, env)
            if left != 0:
                return 1
            return 1 if self._eval(expr.right, env) != 0 else 0

        a = self._eval(expr.left, env)
        b = self._eval(expr.right, env)
        if op == "+":
            return wrap64(a + b)
        if op == "-":
            return wrap64(a - b)
        if op == "*":
            return wrap64(a * b)
        if op == "/":
            return c_div(a, b)
        if op == "%":
            return c_mod(a, b)
        if op == "<":
            return 1 if a < b else 0
        if op == "<=":
            return 1 if a <= b else 0
        if op == ">":
            return 1 if a > b else 0
        if op == ">=":
            return 1 if a >= b else 0
        if op == "==":
            return 1 if a == b else 0
        if op == "!=":
            return 1 if a != b else 0
        raise EmberRuntimeError(f"interpreter: unknown binary op {op!r}")
