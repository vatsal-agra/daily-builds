"""x86-64 instruction encoder: operands, ModRM/SIB/REX construction, mnemonic table."""
import struct
from .errors import FerruleError
from .expr import Expr

# ---------------------------------------------------------------- registers
_R64 = "rax rcx rdx rbx rsp rbp rsi rdi".split() + [f"r{i}" for i in range(8, 16)]
_R32 = "eax ecx edx ebx esp ebp esi edi".split() + [f"r{i}d" for i in range(8, 16)]
_R16 = "ax cx dx bx sp bp si di".split() + [f"r{i}w" for i in range(8, 16)]
_R8 = "al cl dl bl spl bpl sil dil".split() + [f"r{i}b" for i in range(8, 16)]
_H8 = "ah ch dh bh".split()


class Reg:
    __slots__ = ("num", "size", "high8", "name")

    def __init__(self, name, num, size, high8=False):
        self.name, self.num, self.size, self.high8 = name, num, size, high8

    def __repr__(self):
        return self.name


REGS = {}
for _tab, _sz in ((_R64, 64), (_R32, 32), (_R16, 16), (_R8, 8)):
    for _i, _n in enumerate(_tab):
        REGS[_n] = Reg(_n, _i, _sz)
for _i, _n in enumerate(_H8):
    REGS[_n] = Reg(_n, 4 + _i, 8, high8=True)
REGS["rip"] = Reg("rip", -1, 64)
RIP = REGS["rip"]


class Mem:
    def __init__(self, base=None, index=None, scale=1, disp=None, size=None):
        self.base, self.index, self.scale = base, index, scale
        self.disp = disp if disp is not None else Expr(0)
        self.size = size

    @property
    def rip(self):
        return self.base is RIP


class Imm:
    def __init__(self, expr):
        self.expr = expr


class Fix:
    """A value to be patched into emitted bytes once symbols are resolved."""

    def __init__(self, offset, size, kind, expr, signed=False, trail=0):
        self.offset, self.size, self.kind = offset, size, kind   # kind: 'abs' | 'pc'
        self.expr, self.signed, self.trail = expr, signed, trail


class Chunk:
    def __init__(self, data=b"", fixes=None):
        self.data, self.fixes = bytes(data), fixes or []


CC = {"o": 0, "no": 1, "b": 2, "c": 2, "nae": 2, "nb": 3, "nc": 3, "ae": 3, "e": 4, "z": 4,
      "ne": 5, "nz": 5, "be": 6, "na": 6, "nbe": 7, "a": 7, "s": 8, "ns": 9, "p": 10, "pe": 10,
      "np": 11, "po": 11, "l": 12, "nge": 12, "nl": 13, "ge": 13, "le": 14, "ng": 14,
      "nle": 15, "g": 15}


def fits_s(v, bits):
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))


def norm_imm(v, size, mnem="instruction"):
    """Validate `v` against the operand width and return its signed interpretation."""
    bits = 32 if size == 64 else size
    lo = -(1 << (bits - 1))
    hi = (1 << bits) - 1 if size != 64 else (1 << 31) - 1
    if not lo <= v <= hi:
        raise FerruleError(f"immediate {v:#x} out of range for a {size}-bit operand in '{mnem}'")
    return v - (1 << bits) if v > (1 << (bits - 1)) - 1 else v


def imm_pack(v, nbytes):
    bits = nbytes * 8
    if not (-(1 << (bits - 1)) <= v < (1 << bits)):
        raise FerruleError(f"immediate {v:#x} does not fit in {nbytes} byte(s)")
    return (v & ((1 << bits) - 1)).to_bytes(nbytes, "little")


def _num(x):
    return x.num if isinstance(x, Reg) else x


def build(opcode, reg, rm, opsize, *, w=None, p66=None, prefix=b"", imm=b"", imm_expr=None,
          imm_signed=False, force_rex=False):
    """Assemble prefix/REX/opcode/ModRM/SIB/disp/imm into a Chunk.

    reg : int digit or Reg (ModRM.reg)   rm : Reg or Mem (ModRM.rm) or None (opcode-only)
    imm_expr : symbolic immediate (Expr) whose field is len(imm) bytes (zeros in `imm`).
    """
    if w is None:
        w = opsize == 64
    if p66 is None:
        p66 = opsize == 16
    r = _num(reg) if reg is not None else 0
    rex = 0x40 | (8 if w else 0) | (4 if r >= 8 else 0)
    body = bytearray()
    fixes = []
    need_rex_byte = False
    high8 = False
    for x in (reg, rm):
        if isinstance(x, Reg) and x.size == 8:
            if x.high8:
                high8 = True
            elif 4 <= x.num <= 7:
                need_rex_byte = True
    disp_fix = None
    if isinstance(rm, Reg):
        if rm.num >= 8:
            rex |= 1
        body.append(0xC0 | ((r & 7) << 3) | (rm.num & 7))
    elif isinstance(rm, Mem):
        base, idx = rm.base, rm.index
        if idx is not None and idx.num == 4:
            raise FerruleError("rsp cannot be used as an index register")
        for x in (base, idx):
            if isinstance(x, Reg) and x is not RIP and x.size != 64:
                raise FerruleError("addressing needs 64-bit registers")
        if idx is not None and idx.num >= 8:
            rex |= 2
        d = rm.disp
        if rm.rip:
            if idx is not None:
                raise FerruleError("rip-relative address cannot have an index")
            body.append(((r & 7) << 3) | 5)
            disp_fix = ("pc", d)
            if d.is_const:                      # [rip + literal]: a raw displacement
                body += imm_pack(d.const, 4)
                disp_fix = None
        elif base is None:
            # absolute disp32 through SIB (no base)
            if idx is None:
                body.append(((r & 7) << 3) | 4)
                body.append(0x25)
            else:
                body.append(((r & 7) << 3) | 4)
                body.append(({1: 0, 2: 1, 4: 2, 8: 3}[rm.scale] << 6) | ((idx.num & 7) << 3) | 5)
            disp_fix = ("abs", d)
        else:
            if base.num >= 8:
                rex |= 1
            need_sib = idx is not None or (base.num & 7) == 4
            if d.is_const and d.const == 0 and (base.num & 7) != 5:
                mod, dbytes = 0, b""
            elif d.is_const and fits_s(d.const, 8):
                mod, dbytes = 1, imm_pack(d.const, 1)
            elif d.is_const:
                if not fits_s(d.const, 32):
                    raise FerruleError(f"displacement {d.const:#x} out of 32-bit range")
                mod, dbytes = 2, imm_pack(d.const, 4)
            else:
                mod, dbytes = 2, b"\0\0\0\0"
                disp_fix = ("abs", d)
            if need_sib:
                body.append((mod << 6) | ((r & 7) << 3) | 4)
                sc = {1: 0, 2: 1, 4: 2, 8: 3}[rm.scale]
                body.append((sc << 6) | (((idx.num if idx else 4) & 7) << 3) | (base.num & 7))
            else:
                body.append((mod << 6) | ((r & 7) << 3) | (base.num & 7))
            body += dbytes
            if disp_fix:
                disp_fix = (disp_fix[0], disp_fix[1], len(body) - 4)
        if (rm.rip and disp_fix) or (base is None):
            disp_fix = (disp_fix[0], disp_fix[1], len(body))
            body += b"\0\0\0\0"
    elif rm is not None:
        raise FerruleError("internal: bad rm operand")
    out = bytearray()
    if p66:
        out.append(0x66)
    out += prefix
    use_rex = rex != 0x40 or need_rex_byte or force_rex
    if use_rex and high8:
        raise FerruleError("ah/ch/dh/bh cannot be encoded together with a REX prefix or r8-r15/64-bit operands")
    if use_rex:
        out.append(rex)
    out += bytes(opcode)
    base_len = len(out)
    out += body
    if disp_fix:
        kind, expr, off = disp_fix
        fixes.append(Fix(base_len + off, 4, kind, expr, signed=True, trail=len(imm)))
    if imm:
        if imm_expr is not None:
            fixes.append(Fix(len(out), len(imm), "abs", imm_expr, signed=imm_signed))
        out += imm
    return Chunk(out, fixes)


def build_oplus(opcode, regop, opsize, *, w=None, imm=b"", imm_expr=None, imm_signed=False, p66=None):
    """Opcode with register in low 3 bits (push/pop/mov r,imm/bswap/xchg)."""
    if w is None:
        w = opsize == 64
    if p66 is None:
        p66 = opsize == 16
    out = bytearray()
    if p66:
        out.append(0x66)
    rex = 0x40 | (8 if w else 0) | (1 if regop.num >= 8 else 0)
    byte_rex = regop.size == 8 and not regop.high8 and 4 <= regop.num <= 7
    if rex != 0x40 or byte_rex:
        if regop.high8:
            raise FerruleError("high-byte register cannot be used with REX")
        out.append(rex)
    oc = bytearray(opcode)
    oc[-1] |= regop.num & 7
    out += oc
    fixes = []
    if imm:
        if imm_expr is not None:
            fixes.append(Fix(len(out), len(imm), "abs", imm_expr, signed=imm_signed))
        out += imm
    return Chunk(out, fixes)


# ---------------------------------------------------------------- operand helpers
def is_reg(o):
    return isinstance(o, Reg)


def is_mem(o):
    return isinstance(o, Mem)


def is_imm(o):
    return isinstance(o, Imm)


def opsize_of(ops, mnem):
    for o in ops:
        if is_reg(o) and o is not RIP:
            return o.size
    for o in ops:
        if is_mem(o) and o.size:
            return o.size
    raise FerruleError(f"'{mnem}': operand size is ambiguous (add byte/word/dword/qword ptr)")


def imm_bytes(im, size, mnem):
    """Return (bytes, expr_or_None, signed) for an immediate field of `size` bytes."""
    e = im.expr
    if e.is_const:
        return imm_pack(e.const, size), None, False
    return b"\0" * size, e, size == 4


def need(cond, mnem, ops):
    if not cond:
        raise FerruleError(f"invalid operands for '{mnem}'")


ALU = {"add": 0, "or": 1, "adc": 2, "sbb": 3, "and": 4, "sub": 5, "xor": 6, "cmp": 7}
SHIFT = {"rol": 0, "ror": 1, "rcl": 2, "rcr": 3, "shl": 4, "sal": 4, "shr": 5, "sar": 7}
UNARY = {"not": 2, "neg": 3, "mul": 4, "div": 6, "idiv": 7}
SIMPLE = {"ret": b"\xc3", "leave": b"\xc9", "nop": b"\x90", "syscall": b"\x0f\x05",
          "int3": b"\xcc", "hlt": b"\xf4", "ud2": b"\x0f\x0b", "cpuid": b"\x0f\xa2",
          "pause": b"\xf3\x90", "cld": b"\xfc", "std": b"\xfd", "cdq": b"\x99",
          "cqo": b"\x48\x99", "cdqe": b"\x48\x98", "cwde": b"\x98", "cwd": b"\x66\x99",
          "mfence": b"\x0f\xae\xf0", "lfence": b"\x0f\xae\xe8", "sfence": b"\x0f\xae\xf8",
          "rdtsc": b"\x0f\x31", "clc": b"\xf8", "stc": b"\xf9", "sahf": b"\x9e", "lahf": b"\x9f",
          "pushfq": b"\x9c", "popfq": b"\x9d", "retf": b"\xcb"}
STRING = {"movsb": (0xA4, 8), "movsw": (0xA5, 16), "movsq": (0xA5, 64), "stosb": (0xAA, 8),
          "stosw": (0xAB, 16), "stosd": (0xAB, 32), "stosq": (0xAB, 64), "lodsb": (0xAC, 8),
          "lodsq": (0xAD, 64), "scasb": (0xAE, 8), "scasq": (0xAF, 64), "cmpsb": (0xA6, 8),
          "cmpsq": (0xA7, 64), "lodsd": (0xAD, 32), "scasd": (0xAF, 32), "cmpsd": (0xA7, 32),
          "movsd": (0xA5, 32)}


def encode(mnem, ops):
    """Encode one non-branch instruction. Returns a Chunk."""
    n = len(ops)
    if mnem in SIMPLE:
        need(n == 0, mnem, ops)
        return Chunk(SIMPLE[mnem])
    if mnem in STRING:
        need(n == 0, mnem, ops)
        op, sz = STRING[mnem]
        pre = b"\x66" if sz == 16 else b""
        rex = b"\x48" if sz == 64 else b""
        return Chunk(pre + rex + bytes([op if sz != 8 else op]))
    if mnem in ALU:
        return _alu(mnem, ops)
    if mnem == "mov":
        return _mov(ops)
    if mnem == "movabs":
        need(n == 2 and is_reg(ops[0]) and ops[0].size == 64 and is_imm(ops[1]), mnem, ops)
        im = ops[1]
        b, e, _ = imm_bytes(im, 8, mnem)
        return build_oplus([0xB8], ops[0], 64, imm=b, imm_expr=e)
    if mnem == "lea":
        need(n == 2 and is_reg(ops[0]) and is_mem(ops[1]) and ops[0].size >= 16, mnem, ops)
        return build([0x8D], ops[0], ops[1], ops[0].size)
    if mnem == "test":
        return _test(ops)
    if mnem in ("push", "pop"):
        return _pushpop(mnem, ops)
    if mnem in ("inc", "dec"):
        need(n == 1 and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
        sz = opsize_of(ops, mnem)
        return build([0xFE if sz == 8 else 0xFF], 0 if mnem == "inc" else 1, ops[0], sz)
    if mnem in UNARY:
        need(n == 1 and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
        sz = opsize_of(ops, mnem)
        return build([0xF6 if sz == 8 else 0xF7], UNARY[mnem], ops[0], sz)
    if mnem == "imul":
        return _imul(ops)
    if mnem in SHIFT:
        return _shift(mnem, ops)
    if mnem in ("movzx", "movsx", "movsxd"):
        return _movx(mnem, ops)
    if mnem in ("xchg",):
        need(n == 2, mnem, ops)
        a, b = ops
        if is_mem(a):
            a, b = b, a
        need(is_reg(a) and (is_reg(b) or is_mem(b)), mnem, ops)
        if is_reg(b):
            need(a.size == b.size, mnem, ops)
        if is_reg(b) and a.size > 8 and (a.num == 0 or b.num == 0) and a.size == b.size:
            other = b if a.num == 0 else a
            if not (a.size == 32 and other.num == 0):
                return build_oplus([0x90], other, a.size)
        if is_reg(b):
            return build([0x86 if a.size == 8 else 0x87], b, a, a.size)
        return build([0x86 if a.size == 8 else 0x87], a, b, a.size)
    if mnem.startswith("cmov"):
        cc = CC.get(mnem[4:])
        need(cc is not None and n == 2 and is_reg(ops[0]) and ops[0].size > 8
             and (is_reg(ops[1]) or is_mem(ops[1])), mnem, ops)
        if is_reg(ops[1]):
            need(ops[1].size == ops[0].size, mnem, ops)
        return build([0x0F, 0x40 | cc], ops[0], ops[1], ops[0].size)
    if mnem.startswith("set") and mnem[3:] in CC:
        need(n == 1 and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
        if is_reg(ops[0]):
            need(ops[0].size == 8, mnem, ops)
        elif ops[0].size not in (None, 8):
            raise FerruleError("'set<cc>' needs a byte operand")
        return build([0x0F, 0x90 | CC[mnem[3:]]], 0, ops[0], 8)
    if mnem == "bswap":
        need(n == 1 and is_reg(ops[0]) and ops[0].size in (32, 64), mnem, ops)
        return build_oplus([0x0F, 0xC8], ops[0], ops[0].size)
    if mnem in ("bt", "bts", "btr", "btc"):
        return _bt(mnem, ops)
    if mnem in ("bsf", "bsr", "popcnt", "lzcnt", "tzcnt"):
        need(n == 2 and is_reg(ops[0]) and ops[0].size > 8 and (is_reg(ops[1]) or is_mem(ops[1])), mnem, ops)
        if is_reg(ops[1]):
            need(ops[1].size == ops[0].size, mnem, ops)
        op = {"bsf": [0x0F, 0xBC], "bsr": [0x0F, 0xBD], "popcnt": [0x0F, 0xB8],
              "lzcnt": [0x0F, 0xBD], "tzcnt": [0x0F, 0xBC]}[mnem]
        pre = b"\xf3" if mnem in ("popcnt", "lzcnt", "tzcnt") else b""
        return build(op, ops[0], ops[1], ops[0].size, prefix=pre)
    if mnem in ("cmpxchg", "xadd"):
        need(n == 2 and is_reg(ops[1]) and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
        base = 0xB0 if mnem == "cmpxchg" else 0xC0
        return build([0x0F, base | (0 if ops[1].size == 8 else 1)], ops[1], ops[0], ops[1].size)
    if mnem == "int":
        need(n == 1 and is_imm(ops[0]) and ops[0].expr.is_const, mnem, ops)
        return Chunk(b"\xcd" + imm_pack(ops[0].expr.const, 1))
    if mnem == "ret" and n == 1:
        return Chunk(b"\xc2" + imm_pack(ops[0].expr.const, 2))
    raise FerruleError(f"unknown instruction '{mnem}'")


def _alu(mnem, ops):
    need(len(ops) == 2, mnem, ops)
    d, s = ops
    k = ALU[mnem]
    base = k << 3
    if is_reg(d) and (is_reg(s)):
        need(d.size == s.size, mnem, ops)
        return build([base | (0 if d.size == 8 else 1)], s, d, d.size)
    if is_mem(d) and is_reg(s):
        return build([base | (0 if s.size == 8 else 1)], s, d, s.size)
    if is_reg(d) and is_mem(s):
        return build([base | (2 if d.size == 8 else 3)], d, s, d.size)
    if (is_reg(d) or is_mem(d)) and is_imm(s):
        sz = opsize_of([d], mnem)
        e = s.expr
        if sz == 8:
            if e.is_const:
                norm_imm(e.const, 8, mnem)
            b, ex, _ = imm_bytes(s, 1, mnem)
            if is_reg(d) and d.num == 0 and not d.high8:
                return build_acc(base | 4, b, ex, 8)
            return build([0x80], k, d, 8, imm=b, imm_expr=ex)
        if e.is_const:
            v = norm_imm(e.const, sz, mnem)
            if fits_s(v, 8):
                return build([0x83], k, d, sz, imm=imm_pack(v, 1))
            isz = 2 if sz == 16 else 4
            b = imm_pack(v, isz)
            if is_reg(d) and d.num == 0:
                return build_acc(base | 5, b, None, sz)
            return build([0x81], k, d, sz, imm=b)
        isz = 2 if sz == 16 else 4
        return build([0x81], k, d, sz, imm=b"\0" * isz, imm_expr=e, imm_signed=(sz == 64))
    raise FerruleError(f"invalid operands for '{mnem}'")


def build_acc(opcode, imm, ex, size):
    """Accumulator short form: [66] [REX.W] op imm."""
    out = bytearray()
    if size == 16:
        out.append(0x66)
    if size == 64:
        out.append(0x48)
    out.append(opcode)
    fixes = []
    if ex is not None:
        fixes.append(Fix(len(out), len(imm), "abs", ex, signed=size == 64))
    out += imm
    return Chunk(out, fixes)


def _mov(ops):
    mnem = "mov"
    need(len(ops) == 2, mnem, ops)
    d, s = ops
    if is_reg(d) and is_reg(s):
        need(d.size == s.size, mnem, ops)
        return build([0x88 if d.size == 8 else 0x89], s, d, d.size)
    if is_mem(d) and is_reg(s):
        return build([0x88 if s.size == 8 else 0x89], s, d, s.size)
    if is_reg(d) and is_mem(s):
        return build([0x8A if d.size == 8 else 0x8B], d, s, d.size)
    if is_reg(d) and is_imm(s):
        e = s.expr
        sz = d.size
        if e.is_const and sz < 64:
            norm_imm(e.const, sz, mnem)
        if sz == 8:
            b, ex, _ = imm_bytes(s, 1, mnem)
            return build_oplus([0xB0], d, 8, imm=b, imm_expr=ex)
        if sz == 16:
            b, ex, _ = imm_bytes(s, 2, mnem)
            return build_oplus([0xB8], d, 16, imm=b, imm_expr=ex)
        if sz == 32:
            b, ex, _ = imm_bytes(s, 4, mnem)
            return build_oplus([0xB8], d, 32, imm=b, imm_expr=ex)
        if e.is_const:
            if fits_s(e.const, 32):
                return build([0xC7], 0, d, 64, imm=imm_pack(e.const, 4))
            return build_oplus([0xB8], d, 64, imm=imm_pack(e.const, 8))
        return build([0xC7], 0, d, 64, imm=b"\0\0\0\0", imm_expr=e, imm_signed=True)
    if is_mem(d) and is_imm(s):
        sz = opsize_of([d], mnem)
        if s.expr.is_const:
            norm_imm(s.expr.const, sz, mnem)
        if sz == 8:
            b, ex, _ = imm_bytes(s, 1, mnem)
            return build([0xC6], 0, d, 8, imm=b, imm_expr=ex)
        isz = 2 if sz == 16 else 4
        e = s.expr
        b = imm_pack(norm_imm(e.const, sz, mnem), isz) if e.is_const else b"\0" * isz
        return build([0xC7], 0, d, sz, imm=b, imm_expr=None if e.is_const else e,
                     imm_signed=(sz == 64))
    raise FerruleError("invalid operands for 'mov'")


def _test(ops):
    mnem = "test"
    need(len(ops) == 2, mnem, ops)
    d, s = ops
    if is_reg(s) and (is_reg(d) or is_mem(d)):
        return build([0x84 if s.size == 8 else 0x85], s, d, s.size)
    if is_reg(d) and is_mem(s):
        return build([0x84 if d.size == 8 else 0x85], d, s, d.size)
    if (is_reg(d) or is_mem(d)) and is_imm(s):
        sz = opsize_of([d], mnem)
        isz = 1 if sz == 8 else (2 if sz == 16 else 4)
        if s.expr.is_const:
            norm_imm(s.expr.const, sz, mnem)
        b, ex, _ = imm_bytes(s, isz, mnem)
        if is_reg(d) and d.num == 0 and not d.high8:
            return build_acc(0xA8 if sz == 8 else 0xA9, b, ex, sz)
        return build([0xF6 if sz == 8 else 0xF7], 0, d, sz, imm=b, imm_expr=ex, imm_signed=(sz == 64))
    raise FerruleError("invalid operands for 'test'")


def _pushpop(mnem, ops):
    need(len(ops) == 1, mnem, ops)
    o = ops[0]
    if is_reg(o):
        need(o.size == 64, mnem, ops)
        return build_oplus([0x50 if mnem == "push" else 0x58], o, 64, w=False)
    if is_mem(o):
        need(o.size in (None, 64), mnem, ops)
        return build([0xFF] if mnem == "push" else [0x8F], 6 if mnem == "push" else 0, o, 64, w=False)
    need(mnem == "push" and is_imm(o), mnem, ops)
    e = o.expr
    if e.is_const and fits_s(e.const, 8):
        return Chunk(b"\x6a" + imm_pack(e.const, 1))
    if e.is_const:
        if not fits_s(e.const, 32):
            raise FerruleError("push immediate out of 32-bit range")
        return Chunk(b"\x68" + imm_pack(e.const, 4))
    return Chunk(b"\x68\0\0\0\0", [Fix(1, 4, "abs", e, signed=True)])


def _imul(ops):
    mnem = "imul"
    n = len(ops)
    if n == 1:
        need(is_reg(ops[0]) or is_mem(ops[0]), mnem, ops)
        sz = opsize_of(ops, mnem)
        return build([0xF6 if sz == 8 else 0xF7], 5, ops[0], sz)
    if n == 2:
        need(is_reg(ops[0]) and ops[0].size > 8, mnem, ops)
        if is_imm(ops[1]):
            return _imul([ops[0], ops[0], ops[1]])
        need(is_reg(ops[1]) or is_mem(ops[1]), mnem, ops)
        if is_reg(ops[1]):
            need(ops[1].size == ops[0].size, mnem, ops)
        return build([0x0F, 0xAF], ops[0], ops[1], ops[0].size)
    need(n == 3 and is_reg(ops[0]) and (is_reg(ops[1]) or is_mem(ops[1])) and is_imm(ops[2]), mnem, ops)
    d, s, im = ops
    e = im.expr
    if is_reg(s):
        need(s.size == d.size, mnem, ops)
    if e.is_const:
        e = Expr(norm_imm(e.const, d.size, mnem))
        im = Imm(e)
    if e.is_const and fits_s(e.const, 8):
        return build([0x6B], d, s, d.size, imm=imm_pack(e.const, 1))
    isz = 2 if d.size == 16 else 4
    b, ex, _ = imm_bytes(im, isz, mnem)
    return build([0x69], d, s, d.size, imm=b, imm_expr=ex, imm_signed=(d.size == 64))


def _shift(mnem, ops):
    need(len(ops) == 2 and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
    d, c = ops
    k = SHIFT[mnem]
    sz = opsize_of([d], mnem)
    if is_reg(c):
        need(c.name == "cl", mnem, ops)
        return build([0xD2 if sz == 8 else 0xD3], k, d, sz)
    need(is_imm(c) and c.expr.is_const, mnem, ops)
    v = c.expr.const
    if v == 1:
        return build([0xD0 if sz == 8 else 0xD1], k, d, sz)
    return build([0xC0 if sz == 8 else 0xC1], k, d, sz, imm=imm_pack(v, 1))


def _movx(mnem, ops):
    need(len(ops) == 2 and is_reg(ops[0]) and (is_reg(ops[1]) or is_mem(ops[1])), mnem, ops)
    d, s = ops
    ssz = s.size if is_reg(s) else s.size
    if ssz is None:
        raise FerruleError(f"'{mnem}': source size is ambiguous (add byte/word/dword ptr)")
    if mnem == "movsxd" or (mnem == "movsx" and ssz == 32):
        need(ssz == 32 and d.size == 64, mnem, ops)
        return build([0x63], d, s, 64)
    need(ssz in (8, 16) and d.size > ssz, mnem, ops)
    op = {("movzx", 8): 0xB6, ("movzx", 16): 0xB7, ("movsx", 8): 0xBE, ("movsx", 16): 0xBF}[(mnem, ssz)]
    return build([0x0F, op], d, s, d.size)


def _bt(mnem, ops):
    need(len(ops) == 2 and (is_reg(ops[0]) or is_mem(ops[0])), mnem, ops)
    d, s = ops
    k = {"bt": 4, "bts": 5, "btr": 6, "btc": 7}[mnem]
    if is_reg(s):
        op = {"bt": 0xA3, "bts": 0xAB, "btr": 0xB3, "btc": 0xBB}[mnem]
        return build([0x0F, op], s, d, s.size)
    need(is_imm(s) and s.expr.is_const, mnem, ops)
    sz = opsize_of([d], mnem)
    return build([0x0F, 0xBA], k, d, sz, imm=imm_pack(s.expr.const, 1))


def encode_indirect_branch(mnem, op):
    """call/jmp through register or memory."""
    digit = 2 if mnem == "call" else 4
    if is_reg(op):
        need(op.size == 64, mnem, [op])
    elif is_mem(op):
        need(op.size in (None, 64), mnem, [op])
    else:
        raise FerruleError(f"invalid operand for '{mnem}'")
    return build([0xFF], digit, op, 64, w=False)
