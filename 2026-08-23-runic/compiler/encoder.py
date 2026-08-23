"""
Compiles a CheckedProgram + per-function instruction lists into real
WebAssembly binary bytes (the exact MVP format — magic, version, and
type/function/memory/export/code/data sections), byte for byte, with no
library assistance.
"""

import math
import struct

from .wasm import (
    MAGIC, VERSION, SEC_TYPE, SEC_FUNCTION, SEC_MEMORY, SEC_EXPORT, SEC_CODE, SEC_DATA,
    VALTYPE_I32, FUNCTYPE_TAG, EXPORT_KIND_FUNC, EXPORT_KIND_MEM, OPCODES,
    WASM_PAGE_SIZE, uleb128_encode, sleb128_encode, vec, name_bytes, i32_wrap,
)


def _section(section_id, content):
    return bytes([section_id]) + uleb128_encode(len(content)) + content


def _encode_functype(arity):
    params = uleb128_encode(arity) + bytes([VALTYPE_I32]) * arity
    results = uleb128_encode(1) + bytes([VALTYPE_I32])
    return bytes([FUNCTYPE_TAG]) + params + results


def encode_instr(op, imm):
    byte, kind = OPCODES[op]
    head = bytes([byte])
    if kind is None:
        return head
    if kind == "blocktype":
        return head + bytes([imm])
    if kind in ("labelidx", "funcidx", "localidx"):
        return head + uleb128_encode(imm)
    if kind == "i32const":
        # Defensive normalization: any i32.const immediate must be in
        # canonical signed 32-bit range before sleb128 encoding, or the
        # bytes produced are non-canonical and real engines reject them
        # (see codegen.py's IntLit handling for where this actually matters).
        return head + sleb128_encode(i32_wrap(imm))
    if kind == "memarg":
        align, offset = imm
        return head + uleb128_encode(align) + uleb128_encode(offset)
    raise ValueError(f"unknown immediate kind {kind!r}")


def _encode_locals_vec(num_locals):
    if num_locals == 0:
        return uleb128_encode(0)
    return uleb128_encode(1) + uleb128_encode(num_locals) + bytes([VALTYPE_I32])


def _encode_function_body(num_locals, instrs):
    body = _encode_locals_vec(num_locals) + b"".join(encode_instr(op, imm) for op, imm in instrs)
    return uleb128_encode(len(body)) + body


def encode_module(checked, compiled_funcs):
    """
    checked: typecheck.CheckedProgram
    compiled_funcs: list of (num_locals, instrs) aligned with checked.func_order
    """
    # --- type + function sections: one function type per function ---
    type_entries = [_encode_functype(info.arity) for info in checked.func_order]
    func_entries = [uleb128_encode(info.index) for info in checked.func_order]

    type_section = _section(SEC_TYPE, vec(type_entries))
    function_section = _section(SEC_FUNCTION, vec(func_entries))

    # --- memory section (only if the program declared any arrays) ---
    has_memory = checked.total_mem_bytes > 0
    sections = [type_section, function_section]
    if has_memory:
        min_pages = max(1, math.ceil(checked.total_mem_bytes / WASM_PAGE_SIZE))
        limits = bytes([0x00]) + uleb128_encode(min_pages)
        memory_section = _section(SEC_MEMORY, vec([limits]))
        sections.append(memory_section)

    # --- export section: every function, plus memory if present ---
    exports = []
    for info in checked.func_order:
        exports.append(name_bytes(info.name) + bytes([EXPORT_KIND_FUNC]) + uleb128_encode(info.index))
    if has_memory:
        exports.append(name_bytes("memory") + bytes([EXPORT_KIND_MEM]) + uleb128_encode(0))
    export_section = _section(SEC_EXPORT, vec(exports))
    sections.append(export_section)

    # --- code section ---
    code_entries = [_encode_function_body(nl, instrs) for nl, instrs in compiled_funcs]
    code_section = _section(SEC_CODE, vec(code_entries))
    sections.append(code_section)

    # --- data section: arrays with an initializer list ---
    data_entries = []
    for arr in checked.arrays_by_name.values():
        if arr.init is None:
            continue
        offset_expr = encode_instr("i32.const", arr.base_offset) + bytes([0x0B])
        raw = b"".join(struct.pack("<i", v) for v in arr.init)
        data_entries.append(bytes([0x00]) + offset_expr + uleb128_encode(len(raw)) + raw)
    if data_entries:
        data_section = _section(SEC_DATA, vec(data_entries))
        sections.append(data_section)

    return MAGIC + VERSION + b"".join(sections)
