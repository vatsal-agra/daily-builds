"""A stack-machine interpreter that executes a decoded Module IR directly —
no bytecode re-compilation, no JIT. Structured control flow (block/loop/if)
is executed by recursing into the decoder's nested Instr tree; br/br_if/
br_table/return are implemented as Python exceptions carrying a branch
depth, unwound exactly the way the WASM spec's label stack works."""

import math
import struct

PAGE_SIZE = 65536
MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF


class WasmTrap(Exception):
    """A runtime trap — division by zero, out-of-bounds memory access,
    unreachable, stack exhaustion, etc. Mirrors real WASM trap semantics:
    execution stops immediately and the trap propagates to the host."""


class _Branch(Exception):
    def __init__(self, depth):
        self.depth = depth


class _Return(Exception):
    def __init__(self, values):
        self.values = values


def _s32(u):
    u &= MASK32
    return u - 0x100000000 if u >= 0x80000000 else u


def _u32(s):
    return s & MASK32


def _s64(u):
    u &= MASK64
    return u - 0x10000000000000000 if u >= 0x8000000000000000 else u


def _u64(s):
    return s & MASK64


def _as_f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _trunc_to_int(x, lo, hi, ctx):
    if math.isnan(x):
        raise WasmTrap(f"{ctx}: cannot convert NaN to integer")
    t = math.trunc(x)
    if t < lo or t > hi:
        raise WasmTrap(f"{ctx}: integer overflow converting {x!r}")
    return t


class HostFunc:
    """Wraps a Python callable as a WASM import: (instance, *args) -> list[values]."""

    def __init__(self, fn, param_types, result_types):
        self.fn = fn
        self.param_types = param_types
        self.result_types = result_types


class Instance:
    """A live, instantiated module: memory, globals, table and the callable
    function list (imports first, then defined functions — matching WASM's
    global function index space)."""

    def __init__(self, module, imports=None):
        self.module = module
        imports = imports or {}
        self.memory = bytearray()
        self.mem_max_pages = None
        self.globals = []
        self.table = []
        self.funcs = []  # list of ("host", HostFunc) or ("wasm", func_index)
        self.tracer = None  # optional trace.Tracer; see kiln/trace.py

        for imp in module.imports:
            if imp.kind == "func":
                host_mod = imports.get(imp.module, {})
                if imp.name not in host_mod:
                    raise WasmTrap(f"missing import {imp.module}.{imp.name}")
                self.funcs.append(("host", host_mod[imp.name]))
            elif imp.kind == "global":
                host_mod = imports.get(imp.module, {})
                self.globals.append(host_mod.get(imp.name, 0))
            elif imp.kind == "memory":
                pass  # imported memory not supported; modules define their own
            else:
                raise WasmTrap(f"unsupported import kind {imp.kind}")

        for i in range(len(module.functions)):
            self.funcs.append(("wasm", i))

        if module.memories:
            mem = module.memories[0]
            self.memory = bytearray(mem.min * PAGE_SIZE)
            self.mem_max_pages = mem.max

        for g in module.globals:
            self.globals.append(eval_const_expr(g.init, self))

        if module.tables:
            self.table = [None] * module.tables[0].min
        for el in module.elements:
            base = eval_const_expr(el.offset, self)
            for i, fi in enumerate(el.func_indices):
                if base + i < len(self.table):
                    self.table[base + i] = fi

        for d in module.data:
            offset = eval_const_expr(d.offset, self)
            end = offset + len(d.init)
            if end > len(self.memory):
                raise WasmTrap("data segment does not fit in memory")
            self.memory[offset:end] = d.init

        if module.start is not None:
            call_function(self, module.start, [])

    def export_index(self, name, kind="func"):
        for e in self.module.exports:
            if e.name == name and e.kind == kind:
                return e.index
        raise KeyError(f"no export named {name!r} of kind {kind}")

    def call(self, name, args):
        return call_function(self, self.export_index(name), list(args))

    def read_global(self, name):
        return self.globals[self.export_index(name, "global")]


def eval_const_expr(instrs, instance):
    stack = []
    for instr in instrs:
        if instr.op == "i32.const" or instr.op == "i64.const":
            stack.append(instr.imm)
        elif instr.op == "f32.const" or instr.op == "f64.const":
            stack.append(instr.imm)
        elif instr.op == "global.get":
            stack.append(instance.globals[instr.imm])
        elif instr.op == "end":
            pass
        else:
            raise WasmTrap(f"unsupported constant-expression opcode {instr.op}")
    return stack[-1] if stack else 0


class Frame:
    __slots__ = ("locals", "instance")

    def __init__(self, locals_, instance):
        self.locals = locals_
        self.instance = instance


def call_function(instance, func_index, args):
    kind, ref = instance.funcs[func_index]
    if kind == "host":
        hf = ref
        if instance.tracer is not None:
            instance.tracer.enter_host(func_index, args)
        results = list(hf.fn(*args))
        if instance.tracer is not None:
            instance.tracer.exit_call(func_index, results)
        return results

    func = instance.module.functions[ref]
    ftype = instance.module.types[func.type_index]
    locals_ = list(args) + [0 for _ in func.locals]
    frame = Frame(locals_, instance)
    stack = []
    if instance.tracer is not None:
        instance.tracer.enter(func_index, locals_)
    try:
        exec_instrs(func.body, frame, stack)
    except _Return:
        pass
    except RecursionError:
        raise WasmTrap("call stack exhausted")
    nres = len(ftype.results)
    results = stack[-nres:] if nres else []
    if instance.tracer is not None:
        instance.tracer.exit_call(func_index, results)
    return results


def exec_instrs(instrs, frame, stack):
    tracer = frame.instance.tracer
    for instr in instrs:
        op = instr.op
        if tracer is not None:
            tracer.step(instr, stack, frame.locals)

        if op == "block":
            try:
                exec_instrs(instr.body, frame, stack)
            except _Branch as b:
                if b.depth > 0:
                    raise _Branch(b.depth - 1)

        elif op == "loop":
            while True:
                try:
                    exec_instrs(instr.body, frame, stack)
                    break
                except _Branch as b:
                    if b.depth == 0:
                        continue
                    raise _Branch(b.depth - 1)

        elif op == "if":
            cond = stack.pop()
            try:
                if cond != 0:
                    exec_instrs(instr.body, frame, stack)
                elif instr.else_body is not None:
                    exec_instrs(instr.else_body, frame, stack)
            except _Branch as b:
                if b.depth > 0:
                    raise _Branch(b.depth - 1)

        elif op == "br":
            raise _Branch(instr.imm)
        elif op == "br_if":
            cond = stack.pop()
            if cond != 0:
                raise _Branch(instr.imm)
        elif op == "br_table":
            labels, default = instr.imm
            idx = stack.pop()
            depth = labels[idx] if 0 <= idx < len(labels) else default
            raise _Branch(depth)
        elif op == "return":
            raise _Return(stack)
        elif op == "unreachable":
            raise WasmTrap("unreachable instruction executed")
        elif op == "nop":
            pass

        elif op == "call":
            _do_call(frame.instance, instr.imm, stack)
        elif op == "call_indirect":
            table_idx = stack.pop()
            table = frame.instance.table
            if table_idx < 0 or table_idx >= len(table) or table[table_idx] is None:
                raise WasmTrap("call_indirect: undefined element")
            fi = table[table_idx]
            expected = frame.instance.module.types[instr.imm]
            actual = frame.instance.module.types[frame.instance.module.func_type_index(fi)]
            if expected.key() != actual.key():
                raise WasmTrap("call_indirect: signature mismatch")
            _do_call(frame.instance, fi, stack)

        elif op == "drop":
            stack.pop()
        elif op == "select":
            c = stack.pop()
            b = stack.pop()
            a = stack.pop()
            stack.append(a if c != 0 else b)

        elif op == "local.get":
            stack.append(frame.locals[instr.imm])
        elif op == "local.set":
            frame.locals[instr.imm] = stack.pop()
        elif op == "local.tee":
            frame.locals[instr.imm] = stack[-1]
        elif op == "global.get":
            stack.append(frame.instance.globals[instr.imm])
        elif op == "global.set":
            frame.instance.globals[instr.imm] = stack.pop()

        elif op in _MEM_LOADS:
            _do_load(frame.instance, instr, stack)
        elif op in _MEM_STORES:
            _do_store(frame.instance, instr, stack)
        elif op == "memory.size":
            stack.append(len(frame.instance.memory) // PAGE_SIZE)
        elif op == "memory.grow":
            stack.append(_do_grow(frame.instance, stack.pop()))

        elif op == "i32.const" or op == "i64.const" or op == "f32.const" or op == "f64.const":
            stack.append(instr.imm)

        else:
            _do_numeric(op, stack)


_MEM_LOADS = {
    "i32.load", "i64.load", "f32.load", "f64.load",
    "i32.load8_s", "i32.load8_u", "i32.load16_s", "i32.load16_u",
    "i64.load8_s", "i64.load8_u", "i64.load16_s", "i64.load16_u",
    "i64.load32_s", "i64.load32_u",
}
_MEM_STORES = {
    "i32.store", "i64.store", "f32.store", "f64.store",
    "i32.store8", "i32.store16", "i64.store8", "i64.store16", "i64.store32",
}

_LOAD_SPEC = {
    # op: (width_bytes, struct_fmt_or_None, signed)
    "i32.load": (4, "<i", None), "i64.load": (8, "<q", None),
    "f32.load": (4, "<f", None), "f64.load": (8, "<d", None),
    "i32.load8_s": (1, None, True), "i32.load8_u": (1, None, False),
    "i32.load16_s": (2, None, True), "i32.load16_u": (2, None, False),
    "i64.load8_s": (1, None, True), "i64.load8_u": (1, None, False),
    "i64.load16_s": (2, None, True), "i64.load16_u": (2, None, False),
    "i64.load32_s": (4, None, True), "i64.load32_u": (4, None, False),
}
_STORE_WIDTH = {
    "i32.store": 4, "i64.store": 8, "f32.store": 4, "f64.store": 8,
    "i32.store8": 1, "i32.store16": 2,
    "i64.store8": 1, "i64.store16": 2, "i64.store32": 4,
}


def _check_bounds(memory, addr, width, ctx):
    if addr < 0 or addr + width > len(memory):
        raise WasmTrap(f"{ctx}: out of bounds memory access (addr={addr}, width={width}, size={len(memory)})")


def _do_load(instance, instr, stack):
    align, offset = instr.imm
    base = stack.pop()
    addr = base + offset
    width, fmt, signed = _LOAD_SPEC[instr.op]
    _check_bounds(instance.memory, addr, width, instr.op)
    raw = bytes(instance.memory[addr:addr + width])
    if fmt is not None:
        v = struct.unpack(fmt, raw)[0]
    else:
        v = int.from_bytes(raw, "little", signed=signed)
    if instr.op[:3] == "i32":
        v = _u32(v)
    elif instr.op[:3] == "i64":
        v = _u64(v)
    stack.append(v)


def _do_store(instance, instr, stack):
    align, offset = instr.imm
    value = stack.pop()
    base = stack.pop()
    addr = base + offset
    width = _STORE_WIDTH[instr.op]
    _check_bounds(instance.memory, addr, width, instr.op)
    if instr.op == "f32.store":
        raw = struct.pack("<f", value)
    elif instr.op == "f64.store":
        raw = struct.pack("<d", value)
    else:
        raw = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
    instance.memory[addr:addr + width] = raw


def _do_grow(instance, delta_pages):
    current = len(instance.memory) // PAGE_SIZE
    new_total = current + delta_pages
    if instance.mem_max_pages is not None and new_total > instance.mem_max_pages:
        return _u32(-1)
    if new_total > 65536:
        return _u32(-1)
    instance.memory.extend(bytes(delta_pages * PAGE_SIZE))
    return current


def _do_call(instance, func_index, stack):
    kind, ref = instance.funcs[func_index]
    if kind == "host":
        ftype_params = ref.param_types
        n = len(ftype_params)
    else:
        ftype = instance.module.types[instance.module.functions[ref].type_index]
        n = len(ftype.params)
    args = stack[len(stack) - n:] if n else []
    if n:
        del stack[len(stack) - n:]
    results = call_function(instance, func_index, args)
    stack.extend(results)


def _do_numeric(op, stack):
    ty, name = op.split(".", 1)

    if name == "add":
        b, a = stack.pop(), stack.pop()
        stack.append(_wrap(ty, a + b) if ty[0] == "i" else _fwrap(ty, a + b))
        return
    if name == "sub":
        b, a = stack.pop(), stack.pop()
        stack.append(_wrap(ty, a - b) if ty[0] == "i" else _fwrap(ty, a - b))
        return
    if name == "mul":
        b, a = stack.pop(), stack.pop()
        stack.append(_wrap(ty, a * b) if ty[0] == "i" else _fwrap(ty, a * b))
        return

    if ty == "i32" or ty == "i64":
        bits = 32 if ty == "i32" else 64
        to_s = _s32 if ty == "i32" else _s64
        to_u = _u32 if ty == "i32" else _u64
        mask = MASK32 if ty == "i32" else MASK64
        _do_int_op(name, stack, bits, to_s, to_u, mask, ty)
        return

    _do_float_op(ty, name, stack)


def _do_int_op(name, stack, bits, to_s, to_u, mask, ty):
    if name == "eqz":
        stack.append(1 if stack.pop() == 0 else 0)
        return
    if name in ("clz", "ctz", "popcnt"):
        v = to_u(stack.pop())
        if name == "popcnt":
            stack.append(bin(v).count("1"))
        elif name == "clz":
            stack.append(bits if v == 0 else bits - v.bit_length())
        else:  # ctz
            if v == 0:
                stack.append(bits)
            else:
                stack.append((v & -v).bit_length() - 1)
        return

    b, a = stack.pop(), stack.pop()

    if name == "div_s":
        sa, sb = to_s(a), to_s(b)
        if sb == 0:
            raise WasmTrap(f"{ty}.div_s: division by zero")
        if sa == -(1 << (bits - 1)) and sb == -1:
            raise WasmTrap(f"{ty}.div_s: integer overflow")
        q = abs(sa) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        stack.append(to_u(q))
        return
    if name == "div_u":
        ua, ub = to_u(a), to_u(b)
        if ub == 0:
            raise WasmTrap(f"{ty}.div_u: division by zero")
        stack.append(to_u(ua // ub))
        return
    if name == "rem_s":
        sa, sb = to_s(a), to_s(b)
        if sb == 0:
            raise WasmTrap(f"{ty}.rem_s: division by zero")
        r = abs(sa) % abs(sb)
        stack.append(to_u(-r if sa < 0 else r))
        return
    if name == "rem_u":
        ua, ub = to_u(a), to_u(b)
        if ub == 0:
            raise WasmTrap(f"{ty}.rem_u: division by zero")
        stack.append(to_u(ua % ub))
        return

    if name == "and":
        stack.append(to_u(a) & to_u(b)); return
    if name == "or":
        stack.append(to_u(a) | to_u(b)); return
    if name == "xor":
        stack.append(to_u(a) ^ to_u(b)); return
    if name == "shl":
        stack.append(to_u(a << (to_u(b) % bits))); return
    if name == "shr_u":
        stack.append(to_u(a) >> (to_u(b) % bits)); return
    if name == "shr_s":
        sh = to_u(b) % bits
        stack.append(to_u(to_s(a) >> sh)); return
    if name == "rotl":
        sh = to_u(b) % bits
        v = to_u(a)
        stack.append(to_u((v << sh) | (v >> (bits - sh))) if sh else v); return
    if name == "rotr":
        sh = to_u(b) % bits
        v = to_u(a)
        stack.append(to_u((v >> sh) | (v << (bits - sh))) if sh else v); return

    if name in ("eq", "ne", "lt_s", "lt_u", "gt_s", "gt_u", "le_s", "le_u", "ge_s", "ge_u"):
        sa, sb, ua, ub = to_s(a), to_s(b), to_u(a), to_u(b)
        result = {
            "eq": ua == ub, "ne": ua != ub,
            "lt_s": sa < sb, "lt_u": ua < ub,
            "gt_s": sa > sb, "gt_u": ua > ub,
            "le_s": sa <= sb, "le_u": ua <= ub,
            "ge_s": sa >= sb, "ge_u": ua >= ub,
        }[name]
        stack.append(1 if result else 0)
        return

    if name == "wrap_i64":
        stack.append(_u32(a)); return
    if name in ("extend_i32_s",):
        stack.append(_u64(_s32(a))); return
    if name == "extend_i32_u":
        stack.append(_u64(_u32(a))); return
    if name.startswith("trunc_f"):
        _trunc_float_to_int(name, a, stack, ty); return
    if name.startswith("reinterpret_f"):
        raw = struct.pack("<f" if "f32" in name else "<d", a)
        stack.append(int.from_bytes(raw, "little")); return

    raise WasmTrap(f"unimplemented integer op {ty}.{name}")


def _trunc_float_to_int(name, x, stack, ty):
    lo, hi = (-(1 << 31), (1 << 31) - 1) if ty == "i32" else (-(1 << 63), (1 << 63) - 1)
    if "_u" in name:
        lo, hi = 0, (1 << 32) - 1 if ty == "i32" else (1 << 64) - 1
    v = _trunc_to_int(x, lo, hi, f"{ty}.{name}")
    stack.append(_u32(v) if ty == "i32" else _u64(v))


def _do_float_op(ty, name, stack):
    wrap = _as_f32 if ty == "f32" else (lambda x: x)

    if name in ("abs", "neg", "ceil", "floor", "trunc", "nearest", "sqrt"):
        a = stack.pop()
        if name == "abs":
            r = abs(a)
        elif name == "neg":
            r = -a
        elif name == "ceil":
            r = math.ceil(a) if math.isfinite(a) else a
        elif name == "floor":
            r = math.floor(a) if math.isfinite(a) else a
        elif name == "trunc":
            r = math.trunc(a) if math.isfinite(a) else a
        elif name == "nearest":
            r = a if not math.isfinite(a) else float(_round_half_even(a))
        else:  # sqrt
            r = math.sqrt(a) if a >= 0 or math.isnan(a) else float("nan")
        stack.append(wrap(r))
        return

    if name in ("convert_i32_s", "convert_i32_u", "convert_i64_s", "convert_i64_u"):
        a = stack.pop()
        if name.endswith("_s"):
            bits = 32 if "i32" in name else 64
            v = _s32(a) if bits == 32 else _s64(a)
        else:
            v = a
        stack.append(wrap(float(v)))
        return
    if name == "demote_f64":
        stack.append(_as_f32(stack.pop())); return
    if name == "promote_f32":
        stack.append(stack.pop()); return
    if name.startswith("reinterpret_i"):
        a = stack.pop()
        width = 4 if ty == "f32" else 8
        raw = (a & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        stack.append(struct.unpack("<f" if ty == "f32" else "<d", raw)[0])
        return

    b, a = stack.pop(), stack.pop()
    if name == "div":
        if b == 0:
            r = float("nan") if a == 0 else math.copysign(float("inf"), a) * math.copysign(1, b)
        else:
            r = a / b
        stack.append(wrap(r)); return
    if name == "min":
        if math.isnan(a) or math.isnan(b):
            stack.append(float("nan")); return
        stack.append(wrap(min(a, b))); return
    if name == "max":
        if math.isnan(a) or math.isnan(b):
            stack.append(float("nan")); return
        stack.append(wrap(max(a, b))); return
    if name == "copysign":
        stack.append(wrap(math.copysign(a, b))); return
    if name in ("eq", "ne", "lt", "gt", "le", "ge"):
        result = {
            "eq": a == b, "ne": a != b, "lt": a < b,
            "gt": a > b, "le": a <= b, "ge": a >= b,
        }[name]
        stack.append(1 if result else 0)
        return

    raise WasmTrap(f"unimplemented float op {ty}.{name}")


def _round_half_even(x):
    floor_x = math.floor(x)
    diff = x - floor_x
    if diff < 0.5:
        return floor_x
    if diff > 0.5:
        return floor_x + 1
    return floor_x if floor_x % 2 == 0 else floor_x + 1


def _wrap(ty, v):
    return _u32(v) if ty == "i32" else _u64(v)


def _fwrap(ty, v):
    return _as_f32(v) if ty == "f32" else v
