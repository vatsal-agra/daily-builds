"""
From-scratch WebAssembly binary decoder + stack-machine interpreter.

This is completely independent of compiler/encoder.py: it re-derives
sections, function bodies, and instructions purely from the byte stream,
using the shared opcode table in wasm.py as its only point of contact with
the encoder. Executing a module compiled by this project's own encoder.py
through *this* decoder+interpreter is what lets verify.py catch bugs that
would otherwise cancel out between "the compiler's idea of the format" and
"the interpreter's idea of the format".
"""

import struct

from .wasm import (
    MAGIC, VERSION, SEC_TYPE, SEC_FUNCTION, SEC_MEMORY, SEC_EXPORT, SEC_CODE, SEC_DATA,
    EXPORT_KIND_FUNC, OPCODE_BY_BYTE, WASM_PAGE_SIZE,
    uleb128_decode, sleb128_decode, i32_wrap,
)


class WasmTrap(Exception):
    """Raised when execution hits a spec-defined trap (div by zero, unreachable, ...)."""


class DecodeError(Exception):
    pass


# ---------------------------------------------------------------------------
# Binary decoding
# ---------------------------------------------------------------------------

def decode_module(data):
    if data[0:4] != MAGIC:
        raise DecodeError("bad magic number — not a wasm module")
    if data[4:8] != VERSION:
        raise DecodeError("unsupported wasm version")

    mod = {
        "types": [],
        "func_typeidx": [],
        "memory_pages": None,
        "exports": {},
        "code": [],
        "data": [],
    }
    pos = 8
    n = len(data)
    while pos < n:
        sec_id = data[pos]
        pos += 1
        size, pos = uleb128_decode(data, pos)
        content = data[pos:pos + size]
        pos += size
        if sec_id == SEC_TYPE:
            mod["types"] = _decode_type_section(content)
        elif sec_id == SEC_FUNCTION:
            mod["func_typeidx"] = _decode_function_section(content)
        elif sec_id == SEC_MEMORY:
            mod["memory_pages"] = _decode_memory_section(content)
        elif sec_id == SEC_EXPORT:
            mod["exports"] = _decode_export_section(content)
        elif sec_id == SEC_CODE:
            mod["code"] = _decode_code_section(content)
        elif sec_id == SEC_DATA:
            mod["data"] = _decode_data_section(content)
        # unrecognized sections (import/table/global/start/element) are
        # skipped — this project's compiler never emits them.
    return mod


def _decode_type_section(content):
    count, pos = uleb128_decode(content, 0)
    types = []
    for _ in range(count):
        pos += 1  # 0x60 tag
        nparams, pos = uleb128_decode(content, pos)
        pos += nparams
        nresults, pos = uleb128_decode(content, pos)
        pos += nresults
        types.append((nparams, nresults))
    return types


def _decode_function_section(content):
    count, pos = uleb128_decode(content, 0)
    out = []
    for _ in range(count):
        idx, pos = uleb128_decode(content, pos)
        out.append(idx)
    return out


def _decode_memory_section(content):
    _count, pos = uleb128_decode(content, 0)
    flag = content[pos]
    pos += 1
    min_pages, pos = uleb128_decode(content, pos)
    return min_pages


def _decode_export_section(content):
    count, pos = uleb128_decode(content, 0)
    exports = {}
    for _ in range(count):
        namelen, pos = uleb128_decode(content, pos)
        name = content[pos:pos + namelen].decode("utf-8")
        pos += namelen
        kind = content[pos]
        pos += 1
        idx, pos = uleb128_decode(content, pos)
        exports[name] = (kind, idx)
    return exports


def _decode_instrs(data, pos):
    instrs = []
    n = len(data)
    while pos < n:
        opcode = data[pos]
        pos += 1
        if opcode not in OPCODE_BY_BYTE:
            raise DecodeError(f"unknown opcode byte 0x{opcode:02x} at offset {pos - 1}")
        name, kind = OPCODE_BY_BYTE[opcode]
        if kind is None:
            instrs.append((name, None))
        elif kind == "blocktype":
            imm = data[pos]
            pos += 1
            instrs.append((name, imm))
        elif kind in ("labelidx", "funcidx", "localidx"):
            val, pos = uleb128_decode(data, pos)
            instrs.append((name, val))
        elif kind == "i32const":
            val, pos = sleb128_decode(data, pos)
            instrs.append((name, val))
        elif kind == "memarg":
            align, pos = uleb128_decode(data, pos)
            offset, pos = uleb128_decode(data, pos)
            instrs.append((name, (align, offset)))
        else:
            raise DecodeError(f"unhandled immediate kind {kind!r}")
    return instrs


def _decode_function_body(body):
    ngroups, pos = uleb128_decode(body, 0)
    num_locals = 0
    for _ in range(ngroups):
        cnt, pos = uleb128_decode(body, pos)
        pos += 1  # valtype byte
        num_locals += cnt
    instrs = _decode_instrs(body, pos)
    return {"num_locals": num_locals, "instrs": instrs}


def _decode_code_section(content):
    count, pos = uleb128_decode(content, 0)
    funcs = []
    for _ in range(count):
        bodysize, pos = uleb128_decode(content, pos)
        body = content[pos:pos + bodysize]
        pos += bodysize
        funcs.append(_decode_function_body(body))
    return funcs


def _decode_data_section(content):
    count, pos = uleb128_decode(content, 0)
    segs = []
    for _ in range(count):
        flag, pos = uleb128_decode(content, pos)
        if flag != 0:
            raise DecodeError("only active data segments (memidx 0) are supported")
        opcode = content[pos]
        pos += 1
        if opcode != 0x41:  # i32.const
            raise DecodeError("data segment offset expression must be i32.const")
        val, pos = sleb128_decode(content, pos)
        end_byte = content[pos]
        pos += 1
        if end_byte != 0x0B:
            raise DecodeError("malformed data segment offset expression")
        datalen, pos = uleb128_decode(content, pos)
        raw = content[pos:pos + datalen]
        pos += datalen
        segs.append({"offset": val, "bytes": raw})
    return segs


# ---------------------------------------------------------------------------
# Control-flow structure resolution (matches block/loop/if to their 'end'
# and, for 'if', their 'else') — a one-time pass per function, so branches
# don't need to re-scan the instruction stream at runtime.
# ---------------------------------------------------------------------------

def _build_match(instrs):
    match = {}
    stack = []
    for i, (op, _imm) in enumerate(instrs):
        if op in ("block", "loop", "if"):
            stack.append(i)
            match[i] = {"start": i + 1, "end": None, "else": None}
        elif op == "else":
            match[stack[-1]]["else"] = i
        elif op == "end":
            if stack:
                top = stack.pop()
                match[top]["end"] = i + 1
    return match


# ---------------------------------------------------------------------------
# i32 arithmetic (WASM's exact wraparound + truncating-division + trap rules)
# ---------------------------------------------------------------------------

def _i32_div_s(a, b):
    if b == 0:
        raise WasmTrap("integer divide by zero")
    if a == -2147483648 and b == -1:
        raise WasmTrap("integer overflow")
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return i32_wrap(q)


def _i32_rem_s(a, b):
    if b == 0:
        raise WasmTrap("integer divide by zero")
    if a == -2147483648 and b == -1:
        return 0
    r = abs(a) % abs(b)
    if a < 0:
        r = -r
    return i32_wrap(r)


BIN_OPS = {
    "i32.add": lambda a, b: i32_wrap(a + b),
    "i32.sub": lambda a, b: i32_wrap(a - b),
    "i32.mul": lambda a, b: i32_wrap(a * b),
    "i32.div_s": _i32_div_s,
    "i32.rem_s": _i32_rem_s,
    "i32.and": lambda a, b: i32_wrap(a & b),
    "i32.or": lambda a, b: i32_wrap(a | b),
    "i32.xor": lambda a, b: i32_wrap(a ^ b),
    "i32.eq": lambda a, b: 1 if a == b else 0,
    "i32.ne": lambda a, b: 1 if a != b else 0,
    "i32.lt_s": lambda a, b: 1 if a < b else 0,
    "i32.gt_s": lambda a, b: 1 if a > b else 0,
    "i32.le_s": lambda a, b: 1 if a <= b else 0,
    "i32.ge_s": lambda a, b: 1 if a >= b else 0,
}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class Memory:
    def __init__(self, pages):
        self.pages = pages
        self.data = bytearray(pages * WASM_PAGE_SIZE)

    def load_i32(self, addr):
        if addr < 0 or addr + 4 > len(self.data):
            raise WasmTrap(f"out of bounds memory access at {addr}")
        return struct.unpack_from("<i", self.data, addr)[0]

    def store_i32(self, addr, value):
        if addr < 0 or addr + 4 > len(self.data):
            raise WasmTrap(f"out of bounds memory access at {addr}")
        struct.pack_into("<i", self.data, addr, i32_wrap(value))


# ---------------------------------------------------------------------------
# Instance: an executable, instantiated module
# ---------------------------------------------------------------------------

class Instance:
    def __init__(self, wasm_bytes, trace_hook=None):
        self.mod = decode_module(wasm_bytes)
        pages = self.mod["memory_pages"] or 0
        self.memory = Memory(pages) if pages else None
        if self.memory:
            for seg in self.mod["data"]:
                off = seg["offset"]
                b = seg["bytes"]
                self.memory.data[off:off + len(b)] = b
        self.exports = self.mod["exports"]
        self._matches = [_build_match(f["instrs"]) for f in self.mod["code"]]
        # optional callback(funcidx, pc, op, imm, stack, locals, call_depth) for the visualizer
        self.trace_hook = trace_hook
        self._call_depth = 0

    def exported_functions(self):
        return [name for name, (kind, _idx) in self.exports.items() if kind == EXPORT_KIND_FUNC]

    def call_by_name(self, name, args):
        if name not in self.exports:
            raise RuntimeError(f"no export named '{name}'")
        kind, idx = self.exports[name]
        if kind != EXPORT_KIND_FUNC:
            raise RuntimeError(f"export '{name}' is not a function")
        return self.call(idx, args)

    def call(self, funcidx, args):
        nparams, _nresults = self.mod["types"][self.mod["func_typeidx"][funcidx]]
        if len(args) != nparams:
            raise RuntimeError(f"function #{funcidx} expects {nparams} args, got {len(args)}")
        body = self.mod["code"][funcidx]
        locals_ = [i32_wrap(a) for a in args] + [0] * body["num_locals"]
        self._call_depth += 1
        try:
            return self._execute(funcidx, body["instrs"], self._matches[funcidx], locals_)
        finally:
            self._call_depth -= 1

    def _execute(self, funcidx, instrs, match, locals_):
        stack = []
        control = []
        pc = 0
        n = len(instrs)
        while pc < n:
            op, imm = instrs[pc]

            if self.trace_hook:
                self.trace_hook(funcidx, pc, op, imm, stack, locals_, self._call_depth)

            if op == "i32.const":
                stack.append(imm)
                pc += 1
            elif op == "local.get":
                stack.append(locals_[imm])
                pc += 1
            elif op == "local.set":
                locals_[imm] = stack.pop()
                pc += 1
            elif op == "local.tee":
                locals_[imm] = stack[-1]
                pc += 1
            elif op == "drop":
                stack.pop()
                pc += 1
            elif op in ("block", "loop"):
                control.append((op, pc))
                pc += 1
            elif op == "if":
                cond = stack.pop()
                info = match[pc]
                if cond != 0:
                    control.append(("if", pc))
                    pc = info["start"]
                elif info["else"] is not None:
                    control.append(("if", pc))
                    pc = info["else"] + 1
                else:
                    # No else branch and condition is false: skip the whole
                    # construct without ever reaching its 'end', so no frame
                    # is pushed here (there is nothing to pop).
                    pc = info["end"]
            elif op == "else":
                # Reached only by falling through after the then-branch ran
                # to completion (condition was true, an else exists): skip
                # the else-branch, popping the frame we won't otherwise
                # reach a real 'end' for.
                _kind, idx = control.pop()
                pc = match[idx]["end"]
            elif op == "end":
                if control:
                    control.pop()
                pc += 1
                if not control and pc >= n:
                    return stack.pop() if stack else 0
            elif op in ("br", "br_if"):
                do_branch = True
                if op == "br_if":
                    do_branch = stack.pop() != 0
                if do_branch:
                    label = imm
                    kind, idx = control[-(label + 1)]
                    info = match[idx]
                    if kind == "loop":
                        del control[len(control) - label:]
                        pc = info["start"]
                    else:
                        del control[len(control) - label - 1:]
                        pc = info["end"]
                else:
                    pc += 1
            elif op == "return":
                return stack.pop() if stack else 0
            elif op == "call":
                callee_idx = imm
                nparams, _ = self.mod["types"][self.mod["func_typeidx"][callee_idx]]
                cargs = stack[len(stack) - nparams:]
                del stack[len(stack) - nparams:]
                stack.append(self.call(callee_idx, cargs))
                pc += 1
            elif op == "i32.load":
                _align, offset = imm
                addr = stack.pop() + offset
                stack.append(self.memory.load_i32(addr))
                pc += 1
            elif op == "i32.store":
                _align, offset = imm
                value = stack.pop()
                addr = stack.pop() + offset
                self.memory.store_i32(addr, value)
                pc += 1
            elif op == "i32.eqz":
                stack.append(1 if stack.pop() == 0 else 0)
                pc += 1
            elif op in BIN_OPS:
                b = stack.pop()
                a = stack.pop()
                stack.append(BIN_OPS[op](a, b))
                pc += 1
            elif op == "unreachable":
                raise WasmTrap("unreachable instruction executed")
            elif op == "nop":
                pc += 1
            else:
                raise RuntimeError(f"interpreter: unhandled opcode {op!r}")

        return stack.pop() if stack else 0


def run(wasm_bytes, func_name, args, trace_hook=None):
    inst = Instance(wasm_bytes, trace_hook=trace_hook)
    return inst.call_by_name(func_name, args)
