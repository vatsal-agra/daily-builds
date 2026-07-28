"""Bytecode -> Cosmac mnemonic text, the inverse of `assembler.assemble`.

`disassemble_instruction` decodes exactly one opcode into the same mnemonic
syntax `assembler.py` accepts, chosen so that for every program shipped in
`programs/`, `assemble(disassemble(assemble(src)))` is byte-identical to
`assemble(src)` -- see `tests/test_assembler.py`.
"""
from __future__ import annotations

from dataclasses import dataclass


class DisassemblerError(Exception):
    pass


def _reg(n: int) -> str:
    return f"V{n:X}"


@dataclass
class Decoded:
    address: int
    opcode: int
    mnemonic: str
    size: int = 2


def disassemble_instruction(opcode: int) -> str:
    nnn = opcode & 0x0FFF
    n = opcode & 0x000F
    x = (opcode & 0x0F00) >> 8
    y = (opcode & 0x00F0) >> 4
    kk = opcode & 0x00FF
    group = (opcode & 0xF000) >> 12

    if opcode == 0x00E0:
        return "CLS"
    if opcode == 0x00EE:
        return "RET"
    if group == 0x0:
        return f"SYS 0x{nnn:03X}"
    if group == 0x1:
        return f"JP 0x{nnn:03X}"
    if group == 0x2:
        return f"CALL 0x{nnn:03X}"
    if group == 0x3:
        return f"SE {_reg(x)}, 0x{kk:02X}"
    if group == 0x4:
        return f"SNE {_reg(x)}, 0x{kk:02X}"
    if group == 0x5 and n == 0:
        return f"SE {_reg(x)}, {_reg(y)}"
    if group == 0x6:
        return f"LD {_reg(x)}, 0x{kk:02X}"
    if group == 0x7:
        return f"ADD {_reg(x)}, 0x{kk:02X}"
    if group == 0x8:
        return _disassemble_8xy(x, y, n)
    if group == 0x9 and n == 0:
        return f"SNE {_reg(x)}, {_reg(y)}"
    if group == 0xA:
        return f"LD I, 0x{nnn:03X}"
    if group == 0xB:
        return f"JP V0, 0x{nnn:03X}"
    if group == 0xC:
        return f"RND {_reg(x)}, 0x{kk:02X}"
    if group == 0xD:
        return f"DRW {_reg(x)}, {_reg(y)}, 0x{n:X}"
    if group == 0xE and kk == 0x9E:
        return f"SKP {_reg(x)}"
    if group == 0xE and kk == 0xA1:
        return f"SKNP {_reg(x)}"
    if group == 0xF:
        return _disassemble_fx(x, kk)

    raise DisassemblerError(f"unknown opcode 0x{opcode:04X}")


def _disassemble_8xy(x: int, y: int, n: int) -> str:
    if n == 0x0:
        return f"LD {_reg(x)}, {_reg(y)}"
    if n == 0x1:
        return f"OR {_reg(x)}, {_reg(y)}"
    if n == 0x2:
        return f"AND {_reg(x)}, {_reg(y)}"
    if n == 0x3:
        return f"XOR {_reg(x)}, {_reg(y)}"
    if n == 0x4:
        return f"ADD {_reg(x)}, {_reg(y)}"
    if n == 0x5:
        return f"SUB {_reg(x)}, {_reg(y)}"
    if n == 0x6:
        return f"SHR {_reg(x)}, {_reg(y)}"
    if n == 0x7:
        return f"SUBN {_reg(x)}, {_reg(y)}"
    if n == 0xE:
        return f"SHL {_reg(x)}, {_reg(y)}"
    raise DisassemblerError(f"unknown 8XY_ variant 0x{n:X}")


def _disassemble_fx(x: int, kk: int) -> str:
    table = {
        0x07: f"LD {_reg(x)}, DT",
        0x0A: f"LD {_reg(x)}, K",
        0x15: f"LD DT, {_reg(x)}",
        0x18: f"LD ST, {_reg(x)}",
        0x1E: f"ADD I, {_reg(x)}",
        0x29: f"LD F, {_reg(x)}",
        0x33: f"LD B, {_reg(x)}",
        0x55: f"LD [I], {_reg(x)}",
        0x65: f"LD {_reg(x)}, [I]",
    }
    if kk in table:
        return table[kk]
    raise DisassemblerError(f"unknown FX__ variant 0x{kk:02X}")


def disassemble_range(memory: bytes, start: int, end: int) -> list[Decoded]:
    """Best-effort linear disassembly of memory[start:end].

    Any opcode this decoder doesn't recognize (frequently just sprite/data
    bytes living in the same address space as code) falls back to a `DB`
    listing of the two raw bytes rather than raising, since a debugger
    walking memory has no reliable way to distinguish code from data ahead
    of time.
    """
    out = []
    addr = start
    while addr < end - 1:
        opcode = (memory[addr] << 8) | memory[addr + 1]
        try:
            text = disassemble_instruction(opcode)
        except DisassemblerError:
            text = f"DB 0x{memory[addr]:02X}, 0x{memory[addr + 1]:02X}"
        out.append(Decoded(addr, opcode, text))
        addr += 2
    if addr == end - 1:
        # A trailing odd byte can't form a 2-byte opcode (this happens
        # whenever the total data size is odd, e.g. a 1-byte sprite);
        # emit it as a single-byte DB so the round trip stays lossless.
        out.append(Decoded(addr, memory[addr], f"DB 0x{memory[addr]:02X}", size=1))
    return out


def disassemble(program: bytes, origin: int = 0x200) -> str:
    """Disassemble a whole program into Cosmac assembly source text."""
    lines = [f"; disassembled {len(program)} bytes from 0x{origin:03X}"]
    for decoded in disassemble_range(program, 0, len(program)):
        lines.append(f"L{origin + decoded.address:03X}: {decoded.mnemonic}")
    return "\n".join(lines) + "\n"
