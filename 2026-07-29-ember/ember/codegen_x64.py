"""AST -> real x86-64 machine code.

One Assembler buffer holds every function in the program back to back;
`call` targets are resolved via the label/fixup mechanism in asm.py so
forward calls (a function calling one defined later in the source --
needed for mutual recursion) just work.

Locals (parameters + every `let`-declared name) get a fixed, rbp-relative
stack slot, exactly like an unoptimizing `-O0` C compiler would emit --
no register allocator, no SSA, on purpose: the interesting, checkable
part of this build is that the *encoding* and the *calling convention*
are right, not that the codegen is clever.

Stack-alignment bookkeeping: the System V AMD64 ABI requires rsp % 16 == 0
at the instant a `call` instruction executes. After this module's
prologue (`push rbp; mov rbp,rsp; sub rsp,frame_size` with frame_size a
multiple of 16), rsp is 16-aligned. Every `push` after that shifts parity;
`self.depth` tracks how many words are currently pushed at any point
during expression codegen, and `_gen_call` pads with a dummy 8 bytes
whenever depth is odd at the point of the call -- otherwise a callee that
assumed 16-byte alignment (this one doesn't touch SSE, but real-world
calling-convention bugs are exactly this class of "works until it
doesn't") would corrupt memory instead of erroring.
"""

import ctypes
import itertools
import mmap as mmap_mod

from .asm import (
    Assembler, RAX, RCX, RDX, RBP, RSP, ARG_REGS, R11,
    CC_E, CC_NE, CC_L, CC_GE, CC_LE, CC_G,
)
from .ast_nodes import (
    FnDef, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)
from .errors import EmberRuntimeError

_CC = {"==": CC_E, "!=": CC_NE, "<": CC_L, ">=": CC_GE, "<=": CC_LE, ">": CC_G}
_label_counter = itertools.count()

ERR_DIV_ZERO = 1
ERR_DIV_OVERFLOW = 2


def _new_label(tag):
    return f"L_{tag}_{next(_label_counter)}"


class CompiledProgram:
    """Owns the executable buffer and the ctypes error-flag cell for the
    lifetime of any callable built from it -- the mmap must outlive every
    CFUNCTYPE wrapper pointing into it, so both are kept alive here."""

    def __init__(self, mmap_obj, entry_offsets, error_flag, code_bytes, param_counts):
        self.mmap_obj = mmap_obj
        self.entry_offsets = entry_offsets
        self.error_flag = error_flag
        self.code_bytes = code_bytes  # kept for objdump/inspection tooling
        self.param_counts = param_counts

    def base_addr(self):
        return ctypes.addressof(ctypes.c_char.from_buffer(self.mmap_obj))

    def function(self, name, argc):
        if name not in self.entry_offsets:
            available = ", ".join(sorted(self.entry_offsets)) or "(none)"
            raise EmberRuntimeError(f"no compiled function named {name!r}; defined: {available}")
        addr = self.base_addr() + self.entry_offsets[name]
        functype = ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_int64] * argc))
        return functype(addr)

    def call(self, name, args):
        if name not in self.param_counts:
            available = ", ".join(sorted(self.param_counts)) or "(none)"
            raise EmberRuntimeError(f"no compiled function named {name!r}; defined: {available}")
        expected = self.param_counts[name]
        if len(args) != expected:
            raise EmberRuntimeError(
                f"function {name!r} expects {expected} argument(s), got {len(args)}"
            )
        fn = self.function(name, len(args))
        self.error_flag.value = 0
        result = fn(*args)
        code = self.error_flag.value
        if code != 0:
            self.error_flag.value = 0
            if code == ERR_DIV_ZERO:
                raise EmberRuntimeError("division by zero")
            if code == ERR_DIV_OVERFLOW:
                raise EmberRuntimeError("integer overflow: INT64_MIN / -1")
            raise EmberRuntimeError(f"unknown JIT runtime error code {code}")
        return int(result)


def _collect_locals(fn: FnDef):
    """Params first (in declared order), then every `let` name in
    first-occurrence order. A name that's `let`-declared more than once
    (e.g. inside both branches of an `if`, or re-declared each loop
    iteration) reuses the same slot -- Ember has one flat variable
    namespace per function, matching the interpreter exactly."""
    names = list(fn.params)
    seen = set(names)

    def walk_block(block: Block):
        for stmt in block.stmts:
            walk_stmt(stmt)

    def walk_stmt(stmt):
        if isinstance(stmt, LetStmt):
            if stmt.name not in seen:
                seen.add(stmt.name)
                names.append(stmt.name)
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


class FunctionCodeGen:
    def __init__(self, asm: Assembler, fn: FnDef, error_flag_addr: int):
        self.asm = asm
        self.fn = fn
        self.error_flag_addr = error_flag_addr
        self.locals = _collect_locals(fn)
        self.slot = {name: i + 1 for i, name in enumerate(self.locals)}
        self.frame_size = ((len(self.locals) * 8 + 15) // 16) * 16
        self.epilogue_label = _new_label("epilogue")
        self.depth = 0  # compile-time count of outstanding pushed temporaries
        self._error_tails = {}  # code -> label, allocated on first use

    def _offset(self, name):
        if name not in self.slot:
            raise EmberRuntimeError(f"undefined variable {name!r} in function {self.fn.name!r}")
        return -8 * self.slot[name]

    def compile(self):
        asm = self.asm
        asm.define_label(f"fn__{self.fn.name}")
        asm.push(RBP)
        asm.mov_rr(RBP, RSP)
        if self.frame_size:
            asm.sub_rsp_imm32(self.frame_size)
        for i, pname in enumerate(self.fn.params):
            asm.store_slot(self._offset(pname), ARG_REGS[i])
        self._gen_block(self.fn.body)
        # Fall off the end with no explicit `return` -> return 0, same as
        # the interpreter.
        asm.xor_eax_eax()
        asm.define_label(self.epilogue_label)
        asm.mov_rsp_rbp()
        asm.pop(RBP)
        asm.ret()
        self._emit_error_tails()

    # ---- error tails (division by zero / INT64_MIN // -1) ----
    #
    # Both conditions would otherwise make the CPU raise SIGFPE inside
    # `idiv`. Instead, the guard in _gen_div_guard jumps here, which
    # writes a nonzero code into a shared ctypes cell and returns 0 --
    # CompiledProgram.call() checks that cell after every invocation and
    # raises a clean EmberRuntimeError, so a malicious/buggy Ember program
    # can never crash the host Python process.

    def _error_label(self, code):
        if code not in self._error_tails:
            self._error_tails[code] = _new_label(f"err{code}")
        return self._error_tails[code]

    def _emit_error_tails(self):
        asm = self.asm
        for code, label in self._error_tails.items():
            asm.define_label(label)
            asm.movabs(R11, self.error_flag_addr)
            asm.store_slot_abs_ptr(R11, code)
            asm.xor_eax_eax()
            asm.jmp(self.epilogue_label)

    # ---- statements ----

    def _gen_block(self, block: Block):
        for stmt in block.stmts:
            self._gen_stmt(stmt)

    def _gen_stmt(self, stmt):
        asm = self.asm
        if isinstance(stmt, LetStmt):
            self._gen_expr(stmt.expr)
            asm.store_slot(self._offset(stmt.name), RAX)
        elif isinstance(stmt, AssignStmt):
            self._gen_expr(stmt.expr)
            asm.store_slot(self._offset(stmt.name), RAX)
        elif isinstance(stmt, IfStmt):
            self._gen_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._gen_while(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                self._gen_expr(stmt.expr)
            else:
                asm.xor_eax_eax()
            asm.jmp(self.epilogue_label)
        elif isinstance(stmt, ExprStmt):
            self._gen_expr(stmt.expr)
        elif hasattr(stmt, "stmts"):
            self._gen_block(stmt)
        else:
            raise EmberRuntimeError(f"codegen: unhandled statement {stmt!r}")

    def _gen_if(self, stmt: IfStmt):
        asm = self.asm
        else_label = _new_label("else")
        end_label = _new_label("endif")
        self._gen_expr(stmt.cond)
        self._emit_cmp_zero()
        asm.jcc(CC_E, else_label)
        self._gen_block(stmt.then_block)
        asm.jmp(end_label)
        asm.define_label(else_label)
        if stmt.else_block is not None:
            self._gen_block(stmt.else_block)
        asm.define_label(end_label)

    def _gen_while(self, stmt: WhileStmt):
        asm = self.asm
        top_label = _new_label("wtop")
        end_label = _new_label("wend")
        asm.define_label(top_label)
        self._gen_expr(stmt.cond)
        self._emit_cmp_zero()
        asm.jcc(CC_E, end_label)
        self._gen_block(stmt.body)
        asm.jmp(top_label)
        asm.define_label(end_label)

    def _emit_cmp_zero(self):
        """test rax, rax -- same flags as `cmp rax, 0` for an
        equality-to-zero check, in one instruction instead of two."""
        self.asm.test_rr(RAX, RAX)

    # ---- expressions (result always ends up in rax) ----

    def _push(self, reg):
        self.asm.push(reg)
        self.depth += 1

    def _pop(self, reg):
        self.asm.pop(reg)
        self.depth -= 1

    def _gen_expr(self, expr):
        asm = self.asm
        if isinstance(expr, IntLit):
            asm.movabs(RAX, expr.value)
        elif isinstance(expr, BoolLit):
            asm.movabs(RAX, 1 if expr.value else 0)
        elif isinstance(expr, VarRef):
            asm.load_slot(RAX, self._offset(expr.name))
        elif isinstance(expr, UnaryOp):
            self._gen_expr(expr.operand)
            if expr.op == "-":
                asm.neg_r(RAX)
            elif expr.op == "!":
                self._emit_cmp_zero()
                asm.setcc(CC_E)
                asm.movzx_al(RAX)
            else:
                raise EmberRuntimeError(f"codegen: unknown unary op {expr.op!r}")
        elif isinstance(expr, BinOp):
            self._gen_binop(expr)
        elif isinstance(expr, Call):
            self._gen_call(expr)
        else:
            raise EmberRuntimeError(f"codegen: unhandled expression {expr!r}")

    def _gen_binop(self, expr: BinOp):
        asm = self.asm
        op = expr.op
        if op == "&&":
            self._gen_short_circuit(expr, want_false_shortcircuit=True)
            return
        if op == "||":
            self._gen_short_circuit(expr, want_false_shortcircuit=False)
            return

        self._gen_expr(expr.left)
        self._push(RAX)
        self._gen_expr(expr.right)
        asm.mov_rr(RCX, RAX)
        self._pop(RAX)
        # now: rax = left, rcx = right

        if op == "+":
            asm.add_rr(RAX, RCX)
        elif op == "-":
            asm.sub_rr(RAX, RCX)
        elif op == "*":
            asm.imul_rr(RAX, RCX)
        elif op in ("/", "%"):
            self._gen_div_guard()
            asm.cqo()
            asm.idiv_r(RCX)
            if op == "%":
                asm.mov_rr(RAX, RDX)
        elif op in _CC:
            asm.cmp_rr(RAX, RCX)
            asm.setcc(_CC[op])
            asm.movzx_al(RAX)
        else:
            raise EmberRuntimeError(f"codegen: unknown binary op {op!r}")

    def _gen_short_circuit(self, expr: BinOp, want_false_shortcircuit: bool):
        """&&: shortcircuit to false as soon as any operand is false.
        ||: shortcircuit to true as soon as any operand is true."""
        asm = self.asm
        shortcircuit_label = _new_label("sc")
        end_label = _new_label("sc_end")
        cc = CC_E if want_false_shortcircuit else CC_NE
        result_on_shortcircuit = 0 if want_false_shortcircuit else 1
        result_otherwise = 1 if want_false_shortcircuit else 0

        self._gen_expr(expr.left)
        self._emit_cmp_zero()
        asm.jcc(cc, shortcircuit_label)
        self._gen_expr(expr.right)
        self._emit_cmp_zero()
        asm.jcc(cc, shortcircuit_label)
        asm.movabs(RAX, result_otherwise)
        asm.jmp(end_label)
        asm.define_label(shortcircuit_label)
        asm.movabs(RAX, result_on_shortcircuit)
        asm.define_label(end_label)

    def _gen_div_guard(self):
        """Divisor is always in rcx by the time this runs (see
        _gen_binop). Uses rdx as scratch -- safe because the real
        dividend high bits aren't loaded into rdx until `cqo`, which runs
        after this guard."""
        asm = self.asm
        ok_label = _new_label("divok")

        asm.test_rr(RCX, RCX)
        asm.jcc(CC_E, self._error_label(ERR_DIV_ZERO))

        asm.movabs(RDX, -1)
        asm.cmp_rr(RCX, RDX)
        asm.jcc(CC_NE, ok_label)
        asm.movabs(RDX, -(2 ** 63))
        asm.cmp_rr(RAX, RDX)
        asm.jcc(CC_E, self._error_label(ERR_DIV_OVERFLOW))
        asm.define_label(ok_label)

    def _gen_call(self, expr: Call):
        asm = self.asm
        for arg in expr.args:
            self._gen_expr(arg)
            self._push(RAX)
        # pop args, last-pushed first, into the correct arg register
        for i in range(len(expr.args) - 1, -1, -1):
            self._pop(ARG_REGS[i])
        pad = (self.depth % 2) == 1
        if pad:
            asm.sub_rsp_imm32(8)
        asm.call(f"fn__{expr.name}")
        if pad:
            asm.add_rsp_imm32(8)


def compile_program(program) -> CompiledProgram:
    error_flag = ctypes.c_int64(0)
    error_flag_addr = ctypes.addressof(error_flag)

    asm = Assembler()
    entry_offsets = {}
    for fn in program.functions:
        gen = FunctionCodeGen(asm, fn, error_flag_addr)
        gen.compile()
        entry_offsets[fn.name] = None  # resolved below, after resolve()

    asm.resolve()
    code = bytes(asm.buf)

    page = mmap_mod.PAGESIZE
    size = ((len(code) + page - 1) // page) * page
    size = max(size, page)
    mem = mmap_mod.mmap(-1, size, prot=mmap_mod.PROT_READ | mmap_mod.PROT_WRITE | mmap_mod.PROT_EXEC)
    mem.write(code)
    mem.write(b"\x00" * (size - len(code)))

    for fn in program.functions:
        entry_offsets[fn.name] = asm.labels[f"fn__{fn.name}"]
    param_counts = {fn.name: len(fn.params) for fn in program.functions}

    return CompiledProgram(mem, entry_offsets, error_flag, code, param_counts)
