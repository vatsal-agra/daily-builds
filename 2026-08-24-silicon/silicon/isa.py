"""RV32I (subset) instruction formats, encoding, and decoding.

Implements the real RISC-V 32-bit instruction encoding: opcode/funct3/funct7
fields and the six immediate layouts (I, S, B, U, J -- R-type has no
immediate). This module is deliberately the *only* place that knows how a
RISC-V instruction bit-pattern maps to a mnemonic + operands; both the
sequential golden-model simulator and the pipelined simulator decode through
it, so a decoding bug (as opposed to a *timing* bug) would show up in both
and be caught by external encoding tests, not just by cross-checking the two
simulators against each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

XLEN = 32
WORD_MASK = (1 << XLEN) - 1

# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------

ABI_NAMES = [
    "zero", "ra", "sp", "gp", "tp",
    "t0", "t1", "t2",
    "s0", "s1",
    "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
    "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11",
    "t3", "t4", "t5", "t6",
]
assert len(ABI_NAMES) == 32

NAME_TO_REG = {name: i for i, name in enumerate(ABI_NAMES)}
NAME_TO_REG.update({f"x{i}": i for i in range(32)})
# fp is an alias for s0
NAME_TO_REG["fp"] = 8


def reg_num(name: str) -> int:
    key = name.strip().lower()
    if key not in NAME_TO_REG:
        raise ValueError(f"unknown register {name!r}")
    return NAME_TO_REG[key]


def reg_name(num: int) -> str:
    return ABI_NAMES[num]


# ---------------------------------------------------------------------------
# Opcodes / funct3 / funct7
# ---------------------------------------------------------------------------

OP_R = 0b0110011
OP_I_ALU = 0b0010011
OP_LOAD = 0b0000011
OP_STORE = 0b0100011
OP_BRANCH = 0b1100011
OP_JAL = 0b1101111
OP_JALR = 0b1100111
OP_LUI = 0b0110111
OP_AUIPC = 0b0010111
OP_SYSTEM = 0b1110011

# (mnemonic) -> (opcode, funct3, funct7 or None)
R_TYPE = {
    "add": (OP_R, 0b000, 0b0000000),
    "sub": (OP_R, 0b000, 0b0100000),
    "sll": (OP_R, 0b001, 0b0000000),
    "slt": (OP_R, 0b010, 0b0000000),
    "sltu": (OP_R, 0b011, 0b0000000),
    "xor": (OP_R, 0b100, 0b0000000),
    "srl": (OP_R, 0b101, 0b0000000),
    "sra": (OP_R, 0b101, 0b0100000),
    "or": (OP_R, 0b110, 0b0000000),
    "and": (OP_R, 0b111, 0b0000000),
}

I_ALU_TYPE = {
    "addi": (OP_I_ALU, 0b000, None),
    "slti": (OP_I_ALU, 0b010, None),
    "sltiu": (OP_I_ALU, 0b011, None),
    "xori": (OP_I_ALU, 0b100, None),
    "ori": (OP_I_ALU, 0b110, None),
    "andi": (OP_I_ALU, 0b111, None),
    "slli": (OP_I_ALU, 0b001, 0b0000000),
    "srli": (OP_I_ALU, 0b101, 0b0000000),
    "srai": (OP_I_ALU, 0b101, 0b0100000),
}
SHIFT_IMM_OPS = {"slli", "srli", "srai"}

LOAD_TYPE = {
    "lb": (OP_LOAD, 0b000),
    "lh": (OP_LOAD, 0b001),
    "lw": (OP_LOAD, 0b010),
    "lbu": (OP_LOAD, 0b100),
    "lhu": (OP_LOAD, 0b101),
}

STORE_TYPE = {
    "sb": (OP_STORE, 0b000),
    "sh": (OP_STORE, 0b001),
    "sw": (OP_STORE, 0b010),
}

BRANCH_TYPE = {
    "beq": (OP_BRANCH, 0b000),
    "bne": (OP_BRANCH, 0b001),
    "blt": (OP_BRANCH, 0b100),
    "bge": (OP_BRANCH, 0b101),
    "bltu": (OP_BRANCH, 0b110),
    "bgeu": (OP_BRANCH, 0b111),
}

ALL_MNEMONICS = (
    set(R_TYPE) | set(I_ALU_TYPE) | set(LOAD_TYPE) | set(STORE_TYPE)
    | set(BRANCH_TYPE) | {"jal", "jalr", "lui", "auipc", "ecall"}
)


def sign_extend(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def to_u32(value: int) -> int:
    return value & WORD_MASK


def to_s32(value: int) -> int:
    return sign_extend(value & WORD_MASK, 32)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _field(value: int, bits: int, name: str) -> int:
    lo, hi = 0, (1 << bits) - 1
    # allow the natural signed range for immediates encoded in `bits` bits
    if not (-(1 << (bits - 1)) <= value < (1 << bits)):
        raise ValueError(f"{name}={value} does not fit in {bits} bits")
    return value & ((1 << bits) - 1)


def encode_r(mnemonic: str, rd: int, rs1: int, rs2: int) -> int:
    opcode, funct3, funct7 = R_TYPE[mnemonic]
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_i_alu(mnemonic: str, rd: int, rs1: int, imm: int) -> int:
    opcode, funct3, funct7 = I_ALU_TYPE[mnemonic]
    if mnemonic in SHIFT_IMM_OPS:
        shamt = _field(imm, 5, "shamt")
        imm12 = (funct7 << 5) | shamt
    else:
        imm12 = _field(imm, 12, "imm") & 0xFFF
    return (imm12 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_load(mnemonic: str, rd: int, rs1: int, imm: int) -> int:
    opcode, funct3 = LOAD_TYPE[mnemonic]
    imm12 = _field(imm, 12, "imm") & 0xFFF
    return (imm12 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def encode_store(mnemonic: str, rs1: int, rs2: int, imm: int) -> int:
    opcode, funct3 = STORE_TYPE[mnemonic]
    imm12 = _field(imm, 12, "imm") & 0xFFF
    imm_hi = (imm12 >> 5) & 0x7F
    imm_lo = imm12 & 0x1F
    return (imm_hi << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_lo << 7) | opcode


def encode_branch(mnemonic: str, rs1: int, rs2: int, imm: int) -> int:
    opcode, funct3 = BRANCH_TYPE[mnemonic]
    if imm % 2 != 0:
        raise ValueError("branch offset must be even")
    imm13 = _field(imm, 13, "imm")
    bit12 = (imm13 >> 12) & 1
    bit11 = (imm13 >> 11) & 1
    bits10_5 = (imm13 >> 5) & 0x3F
    bits4_1 = (imm13 >> 1) & 0xF
    return (
        (bit12 << 31) | (bits10_5 << 25) | (rs2 << 20) | (rs1 << 15)
        | (funct3 << 12) | (bits4_1 << 8) | (bit11 << 7) | opcode
    )


def encode_jal(rd: int, imm: int) -> int:
    if imm % 2 != 0:
        raise ValueError("jal offset must be even")
    imm21 = _field(imm, 21, "imm")
    bit20 = (imm21 >> 20) & 1
    bits10_1 = (imm21 >> 1) & 0x3FF
    bit11 = (imm21 >> 11) & 1
    bits19_12 = (imm21 >> 12) & 0xFF
    return (
        (bit20 << 31) | (bits10_1 << 21) | (bit11 << 20) | (bits19_12 << 12)
        | (rd << 7) | OP_JAL
    )


def encode_jalr(rd: int, rs1: int, imm: int) -> int:
    imm12 = _field(imm, 12, "imm") & 0xFFF
    return (imm12 << 20) | (rs1 << 15) | (0b000 << 12) | (rd << 7) | OP_JALR


def encode_u(opcode: int, rd: int, imm20: int) -> int:
    # imm20 is the *already-shifted* upper-20-bits value (imm20 << 12), given
    # as the raw 20-bit field (i.e. caller passes bits[31:12]).
    val = _field(imm20, 20, "imm") & 0xFFFFF
    return (val << 12) | (rd << 7) | opcode


def encode_lui(rd: int, imm20: int) -> int:
    return encode_u(OP_LUI, rd, imm20)


def encode_auipc(rd: int, imm20: int) -> int:
    return encode_u(OP_AUIPC, rd, imm20)


def encode_ecall() -> int:
    return OP_SYSTEM  # all other fields zero


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

@dataclass
class Decoded:
    raw: int
    opcode: int
    mnemonic: str
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    funct3: int = 0
    funct7: int = 0
    imm: int = 0
    fmt: str = ""  # 'R','I','S','B','U','J','SYS'

    def uses_rs1(self) -> bool:
        return self.fmt in ("R", "I", "S", "B")

    def uses_rs2(self) -> bool:
        return self.fmt in ("R", "S", "B")

    def writes_rd(self) -> bool:
        return self.fmt in ("R", "I", "U", "J") and self.mnemonic not in ("ecall",)


_R_BY_KEY = {(f3, f7): mn for mn, (op, f3, f7) in R_TYPE.items()}
_IALU_BY_KEY = {}
for _mn, (_op, _f3, _f7) in I_ALU_TYPE.items():
    _IALU_BY_KEY[(_f3, _f7)] = _mn
_LOAD_BY_F3 = {f3: mn for mn, (op, f3) in LOAD_TYPE.items()}
_STORE_BY_F3 = {f3: mn for mn, (op, f3) in STORE_TYPE.items()}
_BRANCH_BY_F3 = {f3: mn for mn, (op, f3) in BRANCH_TYPE.items()}


def decode(word: int) -> Decoded:
    word &= WORD_MASK
    opcode = word & 0x7F
    rd = (word >> 7) & 0x1F
    funct3 = (word >> 12) & 0x7
    rs1 = (word >> 15) & 0x1F
    rs2 = (word >> 20) & 0x1F
    funct7 = (word >> 25) & 0x7F

    if opcode == OP_R:
        mn = _R_BY_KEY.get((funct3, funct7))
        if mn is None:
            raise ValueError(f"illegal R-type instruction 0x{word:08x}")
        return Decoded(word, opcode, mn, rd=rd, rs1=rs1, rs2=rs2, funct3=funct3, funct7=funct7, fmt="R")

    if opcode == OP_I_ALU:
        if funct3 in (0b001, 0b101):
            mn = _IALU_BY_KEY.get((funct3, funct7))
            if mn is None:
                raise ValueError(f"illegal shift-immediate instruction 0x{word:08x}")
            shamt = (word >> 20) & 0x1F
            return Decoded(word, opcode, mn, rd=rd, rs1=rs1, imm=shamt, funct3=funct3, funct7=funct7, fmt="I")
        mn = _IALU_BY_KEY.get((funct3, None))
        if mn is None:
            raise ValueError(f"illegal I-ALU instruction 0x{word:08x}")
        imm = sign_extend(word >> 20, 12)
        return Decoded(word, opcode, mn, rd=rd, rs1=rs1, imm=imm, funct3=funct3, fmt="I")

    if opcode == OP_LOAD:
        mn = _LOAD_BY_F3.get(funct3)
        if mn is None:
            raise ValueError(f"illegal load instruction 0x{word:08x}")
        imm = sign_extend(word >> 20, 12)
        return Decoded(word, opcode, mn, rd=rd, rs1=rs1, imm=imm, funct3=funct3, fmt="I")

    if opcode == OP_STORE:
        mn = _STORE_BY_F3.get(funct3)
        if mn is None:
            raise ValueError(f"illegal store instruction 0x{word:08x}")
        imm_lo = (word >> 7) & 0x1F
        imm_hi = (word >> 25) & 0x7F
        imm = sign_extend((imm_hi << 5) | imm_lo, 12)
        return Decoded(word, opcode, mn, rs1=rs1, rs2=rs2, imm=imm, funct3=funct3, fmt="S")

    if opcode == OP_BRANCH:
        mn = _BRANCH_BY_F3.get(funct3)
        if mn is None:
            raise ValueError(f"illegal branch instruction 0x{word:08x}")
        bit12 = (word >> 31) & 1
        bit11 = (word >> 7) & 1
        bits10_5 = (word >> 25) & 0x3F
        bits4_1 = (word >> 8) & 0xF
        raw = (bit12 << 12) | (bit11 << 11) | (bits10_5 << 5) | (bits4_1 << 1)
        imm = sign_extend(raw, 13)
        return Decoded(word, opcode, mn, rs1=rs1, rs2=rs2, imm=imm, funct3=funct3, fmt="B")

    if opcode == OP_JAL:
        bit20 = (word >> 31) & 1
        bits19_12 = (word >> 12) & 0xFF
        bit11 = (word >> 20) & 1
        bits10_1 = (word >> 21) & 0x3FF
        raw = (bit20 << 20) | (bits19_12 << 12) | (bit11 << 11) | (bits10_1 << 1)
        imm = sign_extend(raw, 21)
        return Decoded(word, opcode, "jal", rd=rd, imm=imm, fmt="J")

    if opcode == OP_JALR:
        imm = sign_extend(word >> 20, 12)
        return Decoded(word, opcode, "jalr", rd=rd, rs1=rs1, imm=imm, funct3=funct3, fmt="I")

    if opcode == OP_LUI:
        imm = sign_extend((word >> 12) << 12, 32)
        return Decoded(word, opcode, "lui", rd=rd, imm=imm, fmt="U")

    if opcode == OP_AUIPC:
        imm = sign_extend((word >> 12) << 12, 32)
        return Decoded(word, opcode, "auipc", rd=rd, imm=imm, fmt="U")

    if opcode == OP_SYSTEM:
        return Decoded(word, opcode, "ecall", fmt="SYS")

    raise ValueError(f"illegal opcode 0b{opcode:07b} in word 0x{word:08x}")


NOP_WORD = encode_i_alu("addi", 0, 0, 0)
assert NOP_WORD == 0x00000013, "NOP must match the real RISC-V NOP encoding"
