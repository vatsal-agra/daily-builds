"""A two-pass assembler for Cosmac's CHIP-8 mnemonic dialect.

Pass 1 walks the source computing each line's emitted size (labels cost
nothing; every real instruction is 2 bytes; `DB`/`DW` are sized by their
operand list) to build a label -> address symbol table.

Pass 2 re-walks the source, this time actually encoding each instruction,
resolving label references against the pass-1 symbol table.

Syntax:
    ; or # start a line comment
    LABEL:                     defines a label at the current address
    LABEL: MNEMONIC operands   a label and an instruction on one line
    MNEMONIC operand, operand  whitespace/comma-separated operands
    Registers are V0-VF (case-insensitive).
    Numbers are decimal (`200`), hex (`0x200` or `$200`), all unsigned.
    DB 1, 2, 0xFF, "hi"        emits raw bytes (strings emit their ASCII bytes)
    DW 0x1234, LABEL           emits raw big-endian 16-bit words
"""
from __future__ import annotations

from dataclasses import dataclass

PROGRAM_START = 0x200

# Keywords with fixed operand meanings (I, DT, ST, F, B, K, [I]) that a
# label must never shadow, on top of register names V0-VF.
_RESERVED_WORDS = {"I", "DT", "ST", "F", "B", "K", "[I]"}


class AssemblerError(Exception):
    def __init__(self, message: str, line_no: "int | None" = None):
        self.line_no = line_no
        prefix = f"line {line_no}: " if line_no is not None else ""
        super().__init__(prefix + message)


@dataclass
class Line:
    line_no: int
    label: "str | None"
    mnemonic: "str | None"
    operands: list[str]
    raw: str


def _strip_comment(text: str) -> str:
    out = []
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
        if not in_quote and ch in ";#":
            break
        out.append(ch)
    return "".join(out)


def _split_operands(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts: list[str] = []
    current = []
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def parse_lines(source: str) -> list[Line]:
    lines: list[Line] = []
    for i, raw in enumerate(source.splitlines(), start=1):
        text = _strip_comment(raw).strip()
        if not text:
            continue
        label = None
        if ":" in text:
            head, _, rest = text.partition(":")
            head = head.strip()
            if head and all(c.isalnum() or c == "_" for c in head) and not head[0].isdigit():
                if _is_register(head) or head.upper() in _RESERVED_WORDS:
                    raise AssemblerError(
                        f"'{head}' can't be used as a label -- it's also a "
                        f"register/keyword name and every operand parse would be ambiguous",
                        i,
                    )
                label = head
                text = rest.strip()
        if not text:
            lines.append(Line(i, label, None, [], raw))
            continue
        tokens = text.split(None, 1)
        mnemonic = tokens[0].upper()
        operand_text = tokens[1] if len(tokens) > 1 else ""
        operands = _split_operands(operand_text)
        lines.append(Line(i, label, mnemonic, operands, raw))
    return lines


def _parse_number(token: str, line_no: int) -> int:
    t = token.strip()
    try:
        if t.lower().startswith("0x"):
            return int(t, 16)
        if t.startswith("$"):
            return int(t[1:], 16)
        return int(t, 10)
    except ValueError as exc:
        raise AssemblerError(f"invalid number '{token}'", line_no) from exc


def _is_register(token: str) -> bool:
    t = token.strip().upper()
    if len(t) != 2 or t[0] != "V":
        return False
    return t[1] in "0123456789ABCDEF"


def _reg_num(token: str) -> int:
    return int(token.strip().upper()[1], 16)


# Mnemonics that always occupy exactly 2 bytes.
_INSTRUCTION_SIZE = 2


def _line_size(line: Line, line_no: int) -> int:
    if line.mnemonic is None:
        return 0
    if line.mnemonic == "DB":
        total = 0
        for op in line.operands:
            if op.startswith('"') and op.endswith('"') and len(op) >= 2:
                total += len(op[1:-1])
            else:
                total += 1
        return total
    if line.mnemonic == "DW":
        return 2 * len(line.operands)
    if line.mnemonic == "ORG":
        return 0
    return _INSTRUCTION_SIZE


def assemble(source: str, origin: int = PROGRAM_START) -> bytes:
    """Assemble Cosmac source text into raw CHIP-8 bytecode."""
    lines = parse_lines(source)

    # Pass 1: compute addresses and the label symbol table.
    symbols: dict[str, int] = {}
    addr = origin
    sized: list[tuple[Line, int]] = []
    for line in lines:
        if line.mnemonic == "ORG":
            if not line.operands:
                raise AssemblerError("ORG requires an address operand", line.line_no)
            addr = _parse_number(line.operands[0], line.line_no)
        if line.label is not None:
            if line.label in symbols:
                raise AssemblerError(f"duplicate label '{line.label}'", line.line_no)
            symbols[line.label] = addr
        size = _line_size(line, line.line_no)
        sized.append((line, addr))
        addr += size

    end_addr = addr

    # Pass 2: encode.
    out = bytearray()
    addr = origin
    for line, line_addr in sized:
        if line.mnemonic is None:
            continue
        if line.mnemonic == "ORG":
            pad_target = _parse_number(line.operands[0], line.line_no)
            if pad_target < origin + len(out):
                raise AssemblerError("ORG cannot move address backwards", line.line_no)
            out.extend(b"\x00" * (pad_target - (origin + len(out))))
            continue
        if line.mnemonic == "DB":
            out.extend(_encode_db(line, symbols))
            continue
        if line.mnemonic == "DW":
            out.extend(_encode_dw(line, symbols))
            continue
        opcode = _encode_instruction(line, symbols)
        out.append((opcode >> 8) & 0xFF)
        out.append(opcode & 0xFF)

    return bytes(out)


def _resolve_addr(token: str, symbols: dict, line_no: int) -> int:
    t = token.strip()
    if t in symbols:
        return symbols[t]
    return _parse_number(t, line_no)


def _encode_db(line: Line, symbols: dict) -> bytes:
    out = bytearray()
    for op in line.operands:
        if op.startswith('"') and op.endswith('"') and len(op) >= 2:
            out.extend(op[1:-1].encode("ascii"))
        else:
            value = _resolve_addr(op, symbols, line.line_no)
            if not 0 <= value <= 0xFF:
                raise AssemblerError(f"DB value {value} out of byte range", line.line_no)
            out.append(value)
    return bytes(out)


def _encode_dw(line: Line, symbols: dict) -> bytes:
    out = bytearray()
    for op in line.operands:
        value = _resolve_addr(op, symbols, line.line_no)
        if not 0 <= value <= 0xFFFF:
            raise AssemblerError(f"DW value {value} out of word range", line.line_no)
        out.append((value >> 8) & 0xFF)
        out.append(value & 0xFF)
    return bytes(out)


def _require(cond: bool, message: str, line_no: int) -> None:
    if not cond:
        raise AssemblerError(message, line_no)


def _encode_instruction(line: Line, symbols: dict) -> int:
    m = line.mnemonic
    ops = line.operands
    ln = line.line_no

    def reg(idx: int) -> int:
        _require(idx < len(ops), f"{m} missing operand", ln)
        _require(_is_register(ops[idx]), f"{m}: '{ops[idx]}' is not a register", ln)
        return _reg_num(ops[idx])

    def addr12(idx: int) -> int:
        _require(idx < len(ops), f"{m} missing operand", ln)
        value = _resolve_addr(ops[idx], symbols, ln)
        _require(0 <= value <= 0xFFF, f"{m}: address {value} out of 12-bit range", ln)
        return value

    def byte8(idx: int) -> int:
        _require(idx < len(ops), f"{m} missing operand", ln)
        value = _resolve_addr(ops[idx], symbols, ln)
        _require(0 <= value <= 0xFF, f"{m}: value {value} out of byte range", ln)
        return value

    def nibble4(idx: int) -> int:
        _require(idx < len(ops), f"{m} missing operand", ln)
        value = _parse_number(ops[idx], ln)
        _require(0 <= value <= 0xF, f"{m}: value {value} out of nibble range", ln)
        return value

    if m == "CLS":
        _require(len(ops) == 0, "CLS takes no operands", ln)
        return 0x00E0
    if m == "RET":
        _require(len(ops) == 0, "RET takes no operands", ln)
        return 0x00EE
    if m == "SYS":
        return 0x0000 | addr12(0)
    if m == "JP":
        if len(ops) == 2:
            _require(ops[0].strip().upper() == "V0", "JP with 2 operands must be 'JP V0, addr'", ln)
            return 0xB000 | addr12(1)
        return 0x1000 | addr12(0)
    if m == "CALL":
        return 0x2000 | addr12(0)
    if m == "SE":
        x = reg(0)
        if _is_register(ops[1]):
            return 0x5000 | (x << 8) | (_reg_num(ops[1]) << 4)
        return 0x3000 | (x << 8) | byte8(1)
    if m == "SNE":
        x = reg(0)
        if _is_register(ops[1]):
            return 0x9000 | (x << 8) | (_reg_num(ops[1]) << 4)
        return 0x4000 | (x << 8) | byte8(1)
    if m == "LD":
        return _encode_ld(ops, ln, reg, addr12, byte8)
    if m == "ADD":
        first = ops[0].strip().upper() if ops else ""
        if first == "I":
            _require(len(ops) > 1 and _is_register(ops[1]), "ADD I, Vx needs a register", ln)
            return 0xF01E | (_reg_num(ops[1]) << 8)
        x = reg(0)
        if _is_register(ops[1]):
            return 0x8004 | (x << 8) | (_reg_num(ops[1]) << 4)
        return 0x7000 | (x << 8) | byte8(1)
    if m == "OR":
        return 0x8001 | (reg(0) << 8) | (reg(1) << 4)
    if m == "AND":
        return 0x8002 | (reg(0) << 8) | (reg(1) << 4)
    if m == "XOR":
        return 0x8003 | (reg(0) << 8) | (reg(1) << 4)
    if m == "SUB":
        return 0x8005 | (reg(0) << 8) | (reg(1) << 4)
    if m == "SUBN":
        return 0x8007 | (reg(0) << 8) | (reg(1) << 4)
    if m == "SHR":
        x = reg(0)
        y = reg(1) if len(ops) > 1 and _is_register(ops[1]) else 0
        return 0x8006 | (x << 8) | (y << 4)
    if m == "SHL":
        x = reg(0)
        y = reg(1) if len(ops) > 1 and _is_register(ops[1]) else 0
        return 0x800E | (x << 8) | (y << 4)
    if m == "RND":
        return 0xC000 | (reg(0) << 8) | byte8(1)
    if m == "DRW":
        return 0xD000 | (reg(0) << 8) | (reg(1) << 4) | nibble4(2)
    if m == "SKP":
        return 0xE09E | (reg(0) << 8)
    if m == "SKNP":
        return 0xE0A1 | (reg(0) << 8)

    raise AssemblerError(f"unknown mnemonic '{m}'", ln)


def _encode_ld(ops, ln, reg, addr12, byte8) -> int:
    _require(len(ops) == 2, "LD requires 2 operands", ln)
    dst, src = ops[0].strip(), ops[1].strip()
    dst_u, src_u = dst.upper(), src.upper()

    if dst_u == "I":
        return 0xA000 | addr12(1)
    if dst_u == "DT":
        return 0xF015 | (reg(1) << 8)
    if dst_u == "ST":
        return 0xF018 | (reg(1) << 8)
    if dst_u == "F":
        return 0xF029 | (reg(1) << 8)
    if dst_u == "B":
        return 0xF033 | (reg(1) << 8)
    if dst_u == "[I]":
        return 0xF055 | (reg(1) << 8)
    if _is_register(dst):
        x = reg(0)
        if src_u == "DT":
            return 0xF007 | (x << 8)
        if src_u == "K":
            return 0xF00A | (x << 8)
        if src_u == "[I]":
            return 0xF065 | (x << 8)
        if _is_register(src):
            return 0x8000 | (x << 8) | (_reg_num(src) << 4)
        return 0x6000 | (x << 8) | byte8(1)

    raise AssemblerError(f"cannot encode 'LD {dst}, {src}'", ln)
