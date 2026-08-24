"""A two-pass assembler for the RV32I subset in isa.py.

Turns assembly text (labels, comments, real R/I/S/B/U/J instructions, and a
handful of standard RISC-V pseudo-instructions) into a flat list of 32-bit
machine words plus a symbol table, ready to load into simulator memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import isa

_MEM_OPERAND_RE = re.compile(r"^(-?(?:0[xX][0-9a-fA-F]+|\d+))\((\w+)\)$")


class AssemblerError(Exception):
    def __init__(self, message: str, line_no: Optional[int] = None, text: str = ""):
        self.line_no = line_no
        self.raw_message = message  # kept so a line-less error can be re-raised *with* a line later
        self.text = text
        loc = f"line {line_no}: " if line_no is not None else ""
        super().__init__(f"{loc}{message}" + (f" ({text!r})" if text else ""))


@dataclass
class AssembledProgram:
    words: List[int]
    base_address: int
    labels: Dict[str, int]
    source_lines: Dict[int, int]  # word index -> 1-based source line number
    text: Dict[int, str] = field(default_factory=dict)  # word index -> canonical text


def _strip_comment(line: str) -> str:
    for marker in ("#", ";"):
        idx = line.find(marker)
        if idx != -1:
            line = line[:idx]
    return line


def _split_label(line: str) -> Tuple[Optional[str], str]:
    if ":" in line:
        label, rest = line.split(":", 1)
        label = label.strip()
        if not label or not re.match(r"^[A-Za-z_.][A-Za-z0-9_.]*$", label):
            raise AssemblerError(f"invalid label {label!r}", text=line)
        return label, rest.strip()
    return None, line.strip()


def _parse_int(tok: str) -> int:
    tok = tok.strip()
    try:
        return int(tok, 0)
    except ValueError:
        raise AssemblerError(f"expected an integer literal, got {tok!r}")


def _split_operands(rest: str) -> List[str]:
    rest = rest.strip()
    if not rest:
        return []
    return [p.strip() for p in rest.split(",")]


def _parse_mem_operand(tok: str) -> Tuple[int, str]:
    m = _MEM_OPERAND_RE.match(tok.strip())
    if not m:
        raise AssemblerError(f"expected 'offset(reg)' memory operand, got {tok!r}")
    return _parse_int(m.group(1)), m.group(2)


# Pseudo-instructions expand to this many real words, given their operands.
# `li` is variable (1 or 2) and handled specially.
_PSEUDO_FIXED_WORDS = {
    "nop": 1, "mv": 1, "not": 1, "neg": 1,
    "j": 1, "jal1": 1, "jr": 1, "ret": 1,
    "beqz": 1, "bnez": 1, "call": 1,
}


def _li_word_count(imm: int) -> int:
    imm = isa.to_s32(imm)
    lo = isa.sign_extend(imm & 0xFFF, 12)
    hi = (imm - lo) >> 12
    if hi == 0:
        return 1
    if lo == 0:
        return 1
    return 2


def _mnemonic_and_rest(instr_text: str) -> Tuple[str, str]:
    parts = instr_text.split(None, 1)
    mnemonic = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return mnemonic, rest


def _word_count_for(mnemonic: str, rest: str, line_no: int) -> int:
    if mnemonic in isa.ALL_MNEMONICS:
        return 1
    if mnemonic == "li":
        ops = _split_operands(rest)
        if len(ops) != 2:
            raise AssemblerError("li expects rd, imm", line_no, rest)
        return _li_word_count(_parse_int(ops[1]))
    if mnemonic == "jal" and len(_split_operands(rest)) == 1:
        return 1
    if mnemonic in _PSEUDO_FIXED_WORDS:
        return 1
    raise AssemblerError(f"unknown mnemonic {mnemonic!r}", line_no, rest)


def assemble(source: str, base_address: int = 0) -> AssembledProgram:
    raw_lines = source.splitlines()

    # ---- Pass 1: compute label addresses and per-line word counts ----
    labels: Dict[str, int] = {}
    plan: List[Tuple[int, Optional[str], str, str]] = []  # (line_no, label, mnemonic, rest)
    addr = base_address
    for line_no, raw in enumerate(raw_lines, start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        label, rest = _split_label(line)
        if label is not None:
            if label in labels:
                raise AssemblerError(f"duplicate label {label!r}", line_no, raw)
            labels[label] = addr
        if not rest:
            continue
        mnemonic, operand_text = _mnemonic_and_rest(rest)
        count = _word_count_for(mnemonic, operand_text, line_no)
        plan.append((line_no, mnemonic, operand_text, addr))
        addr += 4 * count

    # ---- Pass 2: encode ----
    words: List[int] = []
    source_lines: Dict[int, int] = {}
    text_map: Dict[int, str] = {}

    def emit(word: int, line_no: int, text: str) -> None:
        idx = len(words)
        words.append(isa.to_u32(word))
        source_lines[idx] = line_no
        text_map[idx] = text

    for line_no, mnemonic, operand_text, instr_addr in plan:
        ops = _split_operands(operand_text)
        try:
            _encode_one(mnemonic, ops, instr_addr, labels, emit, line_no, operand_text)
        except AssemblerError as exc:
            # Errors raised deep inside operand parsing (e.g. an unresolved
            # branch-target label) don't know their own line number -- fill
            # it in here rather than surface a location-less message.
            if exc.line_no is None:
                raise AssemblerError(exc.raw_message, line_no, exc.text or operand_text) from exc
            raise
        except (KeyError, IndexError, ValueError) as exc:
            raise AssemblerError(str(exc), line_no, operand_text) from exc

    return AssembledProgram(words, base_address, labels, source_lines, text_map)


def _resolve_branch_target(ops_last: str, instr_addr: int, labels: Dict[str, int]) -> int:
    ops_last = ops_last.strip()
    if ops_last in labels:
        return labels[ops_last] - instr_addr
    return _parse_int(ops_last)


def _encode_one(mnemonic, ops, addr, labels, emit, line_no, operand_text):
    r = isa.reg_num

    if mnemonic in isa.R_TYPE:
        if len(ops) != 3:
            raise AssemblerError(f"{mnemonic} expects rd, rs1, rs2", line_no, operand_text)
        emit(isa.encode_r(mnemonic, r(ops[0]), r(ops[1]), r(ops[2])), line_no, f"{mnemonic} {operand_text}")
        return

    if mnemonic in isa.I_ALU_TYPE:
        if len(ops) != 3:
            raise AssemblerError(f"{mnemonic} expects rd, rs1, imm", line_no, operand_text)
        emit(isa.encode_i_alu(mnemonic, r(ops[0]), r(ops[1]), _parse_int(ops[2])), line_no, f"{mnemonic} {operand_text}")
        return

    if mnemonic in isa.LOAD_TYPE:
        if len(ops) != 2:
            raise AssemblerError(f"{mnemonic} expects rd, offset(rs1)", line_no, operand_text)
        off, base = _parse_mem_operand(ops[1])
        emit(isa.encode_load(mnemonic, r(ops[0]), r(base), off), line_no, f"{mnemonic} {operand_text}")
        return

    if mnemonic in isa.STORE_TYPE:
        if len(ops) != 2:
            raise AssemblerError(f"{mnemonic} expects rs2, offset(rs1)", line_no, operand_text)
        off, base = _parse_mem_operand(ops[1])
        emit(isa.encode_store(mnemonic, r(base), r(ops[0]), off), line_no, f"{mnemonic} {operand_text}")
        return

    if mnemonic in isa.BRANCH_TYPE:
        if len(ops) != 3:
            raise AssemblerError(f"{mnemonic} expects rs1, rs2, label", line_no, operand_text)
        offset = _resolve_branch_target(ops[2], addr, labels)
        emit(isa.encode_branch(mnemonic, r(ops[0]), r(ops[1]), offset), line_no, f"{mnemonic} {operand_text}")
        return

    if mnemonic == "jal":
        if len(ops) == 2:
            offset = _resolve_branch_target(ops[1], addr, labels)
            emit(isa.encode_jal(r(ops[0]), offset), line_no, f"jal {operand_text}")
        elif len(ops) == 1:
            offset = _resolve_branch_target(ops[0], addr, labels)
            emit(isa.encode_jal(isa.reg_num("ra"), offset), line_no, f"jal {operand_text}")
        else:
            raise AssemblerError("jal expects [rd,] label", line_no, operand_text)
        return

    if mnemonic == "jalr":
        if len(ops) != 3:
            raise AssemblerError("jalr expects rd, rs1, imm", line_no, operand_text)
        emit(isa.encode_jalr(r(ops[0]), r(ops[1]), _parse_int(ops[2])), line_no, f"jalr {operand_text}")
        return

    if mnemonic == "lui":
        if len(ops) != 2:
            raise AssemblerError("lui expects rd, imm20", line_no, operand_text)
        emit(isa.encode_lui(r(ops[0]), _parse_int(ops[1])), line_no, f"lui {operand_text}")
        return

    if mnemonic == "auipc":
        if len(ops) != 2:
            raise AssemblerError("auipc expects rd, imm20", line_no, operand_text)
        emit(isa.encode_auipc(r(ops[0]), _parse_int(ops[1])), line_no, f"auipc {operand_text}")
        return

    if mnemonic == "ecall":
        emit(isa.encode_ecall(), line_no, "ecall")
        return

    # ---- pseudo-instructions ----
    if mnemonic == "nop":
        emit(isa.encode_i_alu("addi", 0, 0, 0), line_no, "nop")
        return

    if mnemonic == "li":
        if len(ops) != 2:
            raise AssemblerError("li expects rd, imm", line_no, operand_text)
        rd = r(ops[0])
        imm = isa.to_s32(_parse_int(ops[1]))
        lo = isa.sign_extend(imm & 0xFFF, 12)
        hi = (imm - lo) >> 12
        if hi == 0:
            emit(isa.encode_i_alu("addi", rd, 0, lo), line_no, f"li {operand_text}")
        elif lo == 0:
            emit(isa.encode_lui(rd, hi & 0xFFFFF), line_no, f"li {operand_text}")
        else:
            emit(isa.encode_lui(rd, hi & 0xFFFFF), line_no, f"li {operand_text} (1/2)")
            emit(isa.encode_i_alu("addi", rd, rd, lo), line_no, f"li {operand_text} (2/2)")
        return

    if mnemonic == "mv":
        if len(ops) != 2:
            raise AssemblerError("mv expects rd, rs", line_no, operand_text)
        emit(isa.encode_i_alu("addi", r(ops[0]), r(ops[1]), 0), line_no, f"mv {operand_text}")
        return

    if mnemonic == "not":
        if len(ops) != 2:
            raise AssemblerError("not expects rd, rs", line_no, operand_text)
        emit(isa.encode_i_alu("xori", r(ops[0]), r(ops[1]), -1), line_no, f"not {operand_text}")
        return

    if mnemonic == "neg":
        if len(ops) != 2:
            raise AssemblerError("neg expects rd, rs", line_no, operand_text)
        emit(isa.encode_r("sub", r(ops[0]), 0, r(ops[1])), line_no, f"neg {operand_text}")
        return

    if mnemonic == "j":
        if len(ops) != 1:
            raise AssemblerError("j expects label", line_no, operand_text)
        offset = _resolve_branch_target(ops[0], addr, labels)
        emit(isa.encode_jal(0, offset), line_no, f"j {operand_text}")
        return

    if mnemonic == "jr":
        if len(ops) != 1:
            raise AssemblerError("jr expects rs", line_no, operand_text)
        emit(isa.encode_jalr(0, r(ops[0]), 0), line_no, f"jr {operand_text}")
        return

    if mnemonic == "ret":
        emit(isa.encode_jalr(0, isa.reg_num("ra"), 0), line_no, "ret")
        return

    if mnemonic == "call":
        if len(ops) != 1:
            raise AssemblerError("call expects label", line_no, operand_text)
        offset = _resolve_branch_target(ops[0], addr, labels)
        emit(isa.encode_jal(isa.reg_num("ra"), offset), line_no, f"call {operand_text}")
        return

    if mnemonic == "beqz":
        if len(ops) != 2:
            raise AssemblerError("beqz expects rs, label", line_no, operand_text)
        offset = _resolve_branch_target(ops[1], addr, labels)
        emit(isa.encode_branch("beq", r(ops[0]), 0, offset), line_no, f"beqz {operand_text}")
        return

    if mnemonic == "bnez":
        if len(ops) != 2:
            raise AssemblerError("bnez expects rs, label", line_no, operand_text)
        offset = _resolve_branch_target(ops[1], addr, labels)
        emit(isa.encode_branch("bne", r(ops[0]), 0, offset), line_no, f"bnez {operand_text}")
        return

    raise AssemblerError(f"unknown mnemonic {mnemonic!r}", line_no, operand_text)
