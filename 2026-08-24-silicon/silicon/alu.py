"""Pure-function ALU and branch-condition semantics shared by both
simulators. Kept tiny and side-effect-free so it's trivially testable in
isolation against known arithmetic facts, independent of either simulator's
control logic.
"""

from __future__ import annotations

from . import isa


def alu_op(mnemonic: str, a: int, b: int) -> int:
    """a, b are unsigned 32-bit ints (as produced by RegisterFile.read /
    sign-extended immediates already reduced mod 2**32). Returns an unsigned
    32-bit result."""
    a_s, b_s = isa.to_s32(a), isa.to_s32(b)
    if mnemonic in ("add", "addi"):
        return isa.to_u32(a + b)
    if mnemonic == "sub":
        return isa.to_u32(a - b)
    if mnemonic in ("sll", "slli"):
        return isa.to_u32(a << (b & 0x1F))
    if mnemonic in ("srl", "srli"):
        return isa.to_u32(a) >> (b & 0x1F)
    if mnemonic in ("sra", "srai"):
        return isa.to_u32(a_s >> (b & 0x1F))
    if mnemonic in ("slt", "slti"):
        return 1 if a_s < b_s else 0
    if mnemonic in ("sltu", "sltiu"):
        return 1 if isa.to_u32(a) < isa.to_u32(b) else 0
    if mnemonic in ("xor", "xori"):
        return isa.to_u32(a ^ b)
    if mnemonic in ("or", "ori"):
        return isa.to_u32(a | b)
    if mnemonic in ("and", "andi"):
        return isa.to_u32(a & b)
    raise ValueError(f"alu_op: unknown mnemonic {mnemonic!r}")


def branch_taken(mnemonic: str, a: int, b: int) -> bool:
    a_s, b_s = isa.to_s32(a), isa.to_s32(b)
    if mnemonic == "beq":
        return a == b
    if mnemonic == "bne":
        return a != b
    if mnemonic == "blt":
        return a_s < b_s
    if mnemonic == "bge":
        return a_s >= b_s
    if mnemonic == "bltu":
        return isa.to_u32(a) < isa.to_u32(b)
    if mnemonic == "bgeu":
        return isa.to_u32(a) >= isa.to_u32(b)
    raise ValueError(f"branch_taken: unknown mnemonic {mnemonic!r}")


# ALU ops used by R/I-ALU instructions that do NOT depend on rs2/imm at all
# (none in RV32I -- every ALU op takes two operands). Kept as a marker set
# for instructions where the second pipeline operand comes from an immediate
# rather than a register, used by hazard-detection logic.
IMM_ALU_OPS = {"addi", "slti", "sltiu", "xori", "ori", "andi", "slli", "srli", "srai"}
