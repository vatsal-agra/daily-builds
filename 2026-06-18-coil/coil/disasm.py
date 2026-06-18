"""Bytecode disassembler: renders a Chunk (and nested functions) as text."""

from .bytecode import Op, has_operand
from .objects import FunctionObj
from .vm import stringify

# opcodes whose single operand names a constant
_CONST_OPS = {Op.CONSTANT, Op.DEFINE_GLOBAL, Op.GET_GLOBAL, Op.SET_GLOBAL}
_JUMP_OPS = {Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_FALSE_POP}


def disassemble(function, indent=0):
    lines = []
    _disassemble_chunk(function, lines, indent)
    return "\n".join(lines)


def _disassemble_chunk(function, out, indent):
    pad = "  " * indent
    name = function.name or "<script>"
    out.append(f"{pad}== {name} (arity {function.arity}, "
               f"upvalues {function.upvalue_count}) ==")
    chunk = function.chunk
    code = chunk.code
    offset = 0
    nested = []
    prev_line = None
    while offset < len(code):
        op = Op(code[offset])
        line = chunk.lines[offset]
        line_str = "   |" if line == prev_line else f"{line:>4}"
        prev_line = line
        prefix = f"{pad}{offset:04d} {line_str} {op.name:<18}"

        if op == Op.CLOSURE:
            const_idx = code[offset + 1]
            fn = chunk.constants[const_idx]
            out.append(f"{prefix} {const_idx} -> {stringify(fn)}")
            offset += 2
            uv_count = fn.upvalue_count if isinstance(fn, FunctionObj) else 0
            for _ in range(uv_count):
                is_local = code[offset]
                index = code[offset + 1]
                kind = "local" if is_local else "upvalue"
                out.append(f"{pad}{offset:04d}    |   "
                           f"{'':<18} {kind} {index}")
                offset += 2
            if isinstance(fn, FunctionObj):
                nested.append(fn)
            continue

        if has_operand(op):
            operand = code[offset + 1]
            if op in _CONST_OPS:
                val = chunk.constants[operand]
                out.append(f"{prefix} {operand} -> {stringify(val, quote=True)}")
            elif op in _JUMP_OPS:
                out.append(f"{prefix} -> {operand:04d}")
            else:
                out.append(f"{prefix} {operand}")
            offset += 2
        else:
            out.append(prefix.rstrip())
            offset += 1

    for fn in nested:
        out.append("")
        _disassemble_chunk(fn, out, indent + 1)
