"""Decodes a real `.wasm` binary module into the Module IR (types.Module).

Instruction streams are decoded into a *structured* tree: `block`/`loop`/`if`
carry their nested body (and, for `if`, an else-body) as Python lists rather
than leaving the interpreter to scan for matching `end` bytes at runtime.
This mirrors the strict block-nesting the format guarantees (WASM has no
raw jumps — only structured control flow) and makes the interpreter simpler
and faster.
"""

from . import opcodes as ops
from .leb128 import ByteReader
from .types import (
    Module, FuncType, Import, Global, Export, Memory, Table, Element, Function, Data,
    SEC_TYPE, SEC_IMPORT, SEC_FUNCTION, SEC_TABLE, SEC_MEMORY, SEC_GLOBAL,
    SEC_EXPORT, SEC_START, SEC_ELEMENT, SEC_CODE, SEC_DATA, SEC_CUSTOM,
    WASM_MAGIC, WASM_VERSION, VALTYPE_NAMES,
)


class Instr:
    __slots__ = ("op", "opcode", "imm", "body", "else_body")

    def __init__(self, op, opcode, imm=None, body=None, else_body=None):
        self.op = op
        self.opcode = opcode
        self.imm = imm
        self.body = body
        self.else_body = else_body

    def __repr__(self):
        return f"Instr({self.op!r}, imm={self.imm!r})"


def _read_valtype(r):
    b = r.read_byte()
    if b not in VALTYPE_NAMES:
        raise ValueError(f"unknown value type byte 0x{b:02x}")
    return b


def _read_blocktype(r):
    """blocktype ::= 0x40 | valtype | s33(typeidx)"""
    save = r.pos
    b = r.data[r.pos]
    if b == 0x40:
        r.pos += 1
        return None  # empty type
    if b in VALTYPE_NAMES:
        r.pos += 1
        return b  # single result type
    r.pos = save
    return r.read_sleb(33)  # type index (multi-value block)


def decode_instructions(r, terminators=(ops.END_OPCODE,)):
    """Decode instructions until one of `terminators` is hit (consumed).
    Returns (instr_list, terminator_opcode)."""
    out = []
    while True:
        opcode = r.read_byte()
        if opcode in terminators:
            return out, opcode
        name, imm_kind = ops.BY_OPCODE.get(opcode, (None, None))
        if name is None:
            raise ValueError(f"unknown opcode 0x{opcode:02x} at byte {r.pos - 1}")

        if opcode in ops.BLOCK_OPENERS:
            blocktype = _read_blocktype(r)
            if opcode == 0x04:  # if
                then_body, term = decode_instructions(r, (ops.END_OPCODE, ops.ELSE_OPCODE))
                else_body = None
                if term == ops.ELSE_OPCODE:
                    else_body, _ = decode_instructions(r, (ops.END_OPCODE,))
                out.append(Instr(name, opcode, blocktype, then_body, else_body))
            else:  # block / loop
                body, _ = decode_instructions(r, (ops.END_OPCODE,))
                out.append(Instr(name, opcode, blocktype, body))
            continue

        imm = _read_immediate(r, imm_kind)
        out.append(Instr(name, opcode, imm))


def _read_immediate(r, kind):
    if kind is None:
        return None
    if kind == ops.LOCALIDX or kind == ops.GLOBALIDX or kind == ops.FUNCIDX or kind == ops.LABELIDX:
        return r.read_uleb(32)
    if kind == ops.MEMARG:
        align = r.read_uleb(32)
        offset = r.read_uleb(32)
        return (align, offset)
    if kind == ops.MEMORY_IMM:
        r.read_byte()  # reserved 0x00
        return None
    if kind == ops.CALL_INDIRECT:
        type_index = r.read_uleb(32)
        r.read_byte()  # reserved table index, 0x00 in MVP
        return type_index
    if kind == ops.BR_TABLE:
        n = r.read_uleb(32)
        labels = [r.read_uleb(32) for _ in range(n)]
        default = r.read_uleb(32)
        return (labels, default)
    if kind == ops.I32:
        return r.read_sleb(32) & 0xFFFFFFFF
    if kind == ops.I64:
        return r.read_sleb(64) & 0xFFFFFFFFFFFFFFFF
    if kind == ops.F32:
        return r.read_f32()
    if kind == ops.F64:
        return r.read_f64()
    raise ValueError(f"unhandled immediate kind {kind}")


def decode_module(data):
    if data[:4] != WASM_MAGIC:
        raise ValueError("not a wasm module (bad magic)")
    if data[4:8] != WASM_VERSION:
        raise ValueError(f"unsupported wasm version {data[4:8]!r}")

    m = Module()
    r = ByteReader(data, 8)
    func_type_indices = []  # from the Function section, in order

    while not r.eof():
        section_id = r.read_byte()
        size = r.read_uleb(32)
        section_end = r.pos + size
        body = ByteReader(data, r.pos)

        if section_id == SEC_TYPE:
            count = body.read_uleb(32)
            for _ in range(count):
                form = body.read_byte()
                if form != 0x60:
                    raise ValueError("expected func type form 0x60")
                nparams = body.read_uleb(32)
                params = tuple(_read_valtype(body) for _ in range(nparams))
                nresults = body.read_uleb(32)
                results = tuple(_read_valtype(body) for _ in range(nresults))
                m.types.append(FuncType(params, results))

        elif section_id == SEC_IMPORT:
            count = body.read_uleb(32)
            for _ in range(count):
                mod = body.read_name()
                name = body.read_name()
                kind_byte = body.read_byte()
                if kind_byte == 0x00:
                    type_index = body.read_uleb(32)
                    m.imports.append(Import(mod, name, "func", type_index=type_index))
                elif kind_byte == 0x02:
                    limits_flag = body.read_byte()
                    mn = body.read_uleb(32)
                    mx = body.read_uleb(32) if limits_flag == 0x01 else None
                    m.imports.append(Import(mod, name, "memory", mem_min=mn, mem_max=mx))
                elif kind_byte == 0x03:
                    vt = _read_valtype(body)
                    mut = body.read_byte() == 0x01
                    m.imports.append(Import(mod, name, "global", global_type=vt, global_mutable=mut))
                else:
                    raise ValueError(f"unsupported import kind 0x{kind_byte:02x} (table imports unimplemented)")

        elif section_id == SEC_FUNCTION:
            count = body.read_uleb(32)
            func_type_indices = [body.read_uleb(32) for _ in range(count)]

        elif section_id == SEC_TABLE:
            count = body.read_uleb(32)
            for _ in range(count):
                body.read_byte()  # elemtype, always 0x70 funcref in MVP
                flag = body.read_byte()
                mn = body.read_uleb(32)
                mx = body.read_uleb(32) if flag == 0x01 else None
                m.tables.append(Table(mn, mx))

        elif section_id == SEC_MEMORY:
            count = body.read_uleb(32)
            for _ in range(count):
                flag = body.read_byte()
                mn = body.read_uleb(32)
                mx = body.read_uleb(32) if flag == 0x01 else None
                m.memories.append(Memory(mn, mx))

        elif section_id == SEC_GLOBAL:
            count = body.read_uleb(32)
            for _ in range(count):
                vt = _read_valtype(body)
                mut = body.read_byte() == 0x01
                init, _ = decode_instructions(body)
                m.globals.append(Global(vt, mut, init))

        elif section_id == SEC_EXPORT:
            count = body.read_uleb(32)
            kind_names = {0x00: "func", 0x01: "table", 0x02: "memory", 0x03: "global"}
            for _ in range(count):
                name = body.read_name()
                kind_byte = body.read_byte()
                index = body.read_uleb(32)
                m.exports.append(Export(name, kind_names.get(kind_byte, "?"), index))

        elif section_id == SEC_START:
            m.start = body.read_uleb(32)

        elif section_id == SEC_ELEMENT:
            count = body.read_uleb(32)
            for _ in range(count):
                table_index = body.read_uleb(32)
                offset, _ = decode_instructions(body)
                n = body.read_uleb(32)
                func_indices = [body.read_uleb(32) for _ in range(n)]
                m.elements.append(Element(table_index, offset, func_indices))

        elif section_id == SEC_CODE:
            count = body.read_uleb(32)
            for i in range(count):
                body_size = body.read_uleb(32)
                fn_end = body.pos + body_size
                nlocal_groups = body.read_uleb(32)
                local_types = []
                for _ in range(nlocal_groups):
                    n = body.read_uleb(32)
                    vt = _read_valtype(body)
                    local_types.extend([vt] * n)
                instrs, _ = decode_instructions(body)
                body.pos = fn_end
                type_index = func_type_indices[i] if i < len(func_type_indices) else None
                m.functions.append(Function(type_index, local_types, instrs))

        elif section_id == SEC_DATA:
            count = body.read_uleb(32)
            for _ in range(count):
                mem_index = body.read_uleb(32)
                offset, _ = decode_instructions(body)
                n = body.read_uleb(32)
                init = body.read_bytes(n)
                m.data.append(Data(mem_index, offset, init))

        elif section_id == SEC_CUSTOM:
            pass  # names / producers / etc. — not needed for execution

        else:
            raise ValueError(f"unknown section id {section_id}")

        r.pos = section_end

    return m
