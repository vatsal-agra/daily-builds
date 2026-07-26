"""Encodes the Module IR (types.Module) back into a real `.wasm` binary —
the inverse of decoder.py. Used by the assembler and the Pebble compiler,
both of which build a Module IR and then call `encode_module` to produce
bytes any real WASM engine (including Node's) can load."""

import struct

from . import opcodes as ops
from .leb128 import encode_uleb, encode_sleb
from .types import (
    WASM_MAGIC, WASM_VERSION, VALTYPE_NAMES,
    SEC_TYPE, SEC_IMPORT, SEC_FUNCTION, SEC_TABLE, SEC_MEMORY, SEC_GLOBAL,
    SEC_EXPORT, SEC_START, SEC_ELEMENT, SEC_CODE, SEC_DATA,
)


def _name(s):
    b = s.encode("utf-8")
    return encode_uleb(len(b)) + b


def _vec(items):
    return encode_uleb(len(items)) + b"".join(items)


def _blocktype(bt):
    if bt is None:
        return bytes([0x40])
    if bt in VALTYPE_NAMES:
        return bytes([bt])
    return encode_sleb(bt)  # type index


def encode_instr(instr):
    opcode = instr.opcode
    out = bytearray([opcode])
    if opcode in ops.BLOCK_OPENERS:
        out += _blocktype(instr.imm)
        out += encode_instrs(instr.body)
        if opcode == 0x04 and instr.else_body is not None:
            out.append(ops.ELSE_OPCODE)
            out += encode_instrs(instr.else_body)
        out.append(ops.END_OPCODE)
        return bytes(out)

    _, kind = ops.BY_OPCODE[opcode]
    if kind is None:
        pass
    elif kind in (ops.LOCALIDX, ops.GLOBALIDX, ops.FUNCIDX, ops.LABELIDX):
        out += encode_uleb(instr.imm)
    elif kind == ops.MEMARG:
        align, offset = instr.imm
        out += encode_uleb(align) + encode_uleb(offset)
    elif kind == ops.MEMORY_IMM:
        out.append(0x00)
    elif kind == ops.CALL_INDIRECT:
        out += encode_uleb(instr.imm) + bytes([0x00])
    elif kind == ops.BR_TABLE:
        labels, default = instr.imm
        out += encode_uleb(len(labels))
        for l in labels:
            out += encode_uleb(l)
        out += encode_uleb(default)
    elif kind == ops.I32:
        v = instr.imm
        if v >= 0x80000000:
            v -= 0x100000000
        out += encode_sleb(v)
    elif kind == ops.I64:
        v = instr.imm
        if v >= 0x8000000000000000:
            v -= 0x10000000000000000
        out += encode_sleb(v)
    elif kind == ops.F32:
        out += struct.pack("<f", instr.imm)
    elif kind == ops.F64:
        out += struct.pack("<d", instr.imm)
    else:
        raise ValueError(f"unhandled immediate kind {kind}")
    return bytes(out)


def encode_instrs(instrs):
    return b"".join(encode_instr(i) for i in instrs)


def encode_expr(instrs):
    """A constant/init expression: instructions followed by an explicit end."""
    return encode_instrs(instrs) + bytes([ops.END_OPCODE])


def _section(section_id, payload):
    if not payload:
        return b""
    return bytes([section_id]) + encode_uleb(len(payload)) + payload


def encode_module(m):
    out = bytearray(WASM_MAGIC + WASM_VERSION)

    if m.types:
        payload = _vec([
            bytes([0x60]) + encode_uleb(len(t.params)) + bytes(t.params)
            + encode_uleb(len(t.results)) + bytes(t.results)
            for t in m.types
        ])
        out += _section(SEC_TYPE, payload)

    if m.imports:
        entries = []
        for imp in m.imports:
            head = _name(imp.module) + _name(imp.name)
            if imp.kind == "func":
                entries.append(head + bytes([0x00]) + encode_uleb(imp.type_index))
            elif imp.kind == "memory":
                if imp.mem_max is None:
                    entries.append(head + bytes([0x02, 0x00]) + encode_uleb(imp.mem_min))
                else:
                    entries.append(head + bytes([0x02, 0x01]) + encode_uleb(imp.mem_min) + encode_uleb(imp.mem_max))
            elif imp.kind == "global":
                entries.append(head + bytes([0x03, imp.global_type, 0x01 if imp.global_mutable else 0x00]))
            else:
                raise ValueError(f"unsupported import kind {imp.kind}")
        out += _section(SEC_IMPORT, _vec(entries))

    if m.functions:
        out += _section(SEC_FUNCTION, _vec([encode_uleb(f.type_index) for f in m.functions]))

    if m.tables:
        entries = []
        for t in m.tables:
            if t.max is None:
                entries.append(bytes([0x70, 0x00]) + encode_uleb(t.min))
            else:
                entries.append(bytes([0x70, 0x01]) + encode_uleb(t.min) + encode_uleb(t.max))
        out += _section(SEC_TABLE, _vec(entries))

    if m.memories:
        entries = []
        for mem in m.memories:
            if mem.max is None:
                entries.append(bytes([0x00]) + encode_uleb(mem.min))
            else:
                entries.append(bytes([0x01]) + encode_uleb(mem.min) + encode_uleb(mem.max))
        out += _section(SEC_MEMORY, _vec(entries))

    if m.globals:
        entries = [
            bytes([g.val_type, 0x01 if g.mutable else 0x00]) + encode_expr(g.init)
            for g in m.globals
        ]
        out += _section(SEC_GLOBAL, _vec(entries))

    if m.exports:
        kind_bytes = {"func": 0x00, "table": 0x01, "memory": 0x02, "global": 0x03}
        entries = [
            _name(e.name) + bytes([kind_bytes[e.kind]]) + encode_uleb(e.index)
            for e in m.exports
        ]
        out += _section(SEC_EXPORT, _vec(entries))

    if m.start is not None:
        out += _section(SEC_START, encode_uleb(m.start))

    if m.elements:
        entries = [
            encode_uleb(e.table_index) + encode_expr(e.offset)
            + encode_uleb(len(e.func_indices)) + b"".join(encode_uleb(fi) for fi in e.func_indices)
            for e in m.elements
        ]
        out += _section(SEC_ELEMENT, _vec(entries))

    if m.functions:
        bodies = []
        for f in m.functions:
            # RLE-compress consecutive identical local types into groups,
            # exactly like a real compiler backend would.
            groups = []
            for vt in f.locals:
                if groups and groups[-1][1] == vt:
                    groups[-1][0] += 1
                else:
                    groups.append([1, vt])
            locals_payload = _vec([encode_uleb(n) + bytes([vt]) for n, vt in groups])
            code = locals_payload + encode_expr(f.body)
            bodies.append(encode_uleb(len(code)) + code)
        out += _section(SEC_CODE, _vec(bodies))

    if m.data:
        entries = [
            encode_uleb(d.memory_index) + encode_expr(d.offset)
            + encode_uleb(len(d.init)) + d.init
            for d in m.data
        ]
        out += _section(SEC_DATA, _vec(entries))

    return bytes(out)
