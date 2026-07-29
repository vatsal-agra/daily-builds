"""A hand-rolled x86-64 instruction encoder.

Only the instruction subset Ember's code generator actually needs is
implemented -- but each one is encoded from first principles (REX
prefix bits, ModRM, SIB avoidance) rather than looked up in a table, and
every one is covered by tests/test_asm.py which independently decodes
the bytes with a tiny hand-written decoder *and* cross-checks against the
box's real `objdump` (see disasm.py) so an encoding mistake can't hide
behind "well, my own disassembler agrees with itself".

Register numbering matches the real x86-64 encoding (0=rax .. 15=r15) so
register numbers can be used directly in ModRM/opcode arithmetic.
"""

import struct

RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI = range(8)
R8, R9, R10, R11, R12, R13, R14, R15 = range(8, 16)

ARG_REGS = [RDI, RSI, RDX, RCX, R8, R9]  # System V AMD64 integer args, in order

REG_NAMES = {
    RAX: "rax", RCX: "rcx", RDX: "rdx", RBX: "rbx",
    RSP: "rsp", RBP: "rbp", RSI: "rsi", RDI: "rdi",
    R8: "r8", R9: "r9", R10: "r10", R11: "r11",
    R12: "r12", R13: "r13", R14: "r14", R15: "r15",
}

# Condition codes shared by Jcc and SETcc (bits 0-3 of the opcode).
CC_E, CC_NE, CC_L, CC_GE, CC_LE, CC_G = 0x4, 0x5, 0xC, 0xD, 0xE, 0xF


def _rex(w=1, r=0, x=0, b=0):
    return 0x40 | (w << 3) | (r << 2) | (x << 1) | b


def _modrm(mod, reg, rm):
    return (mod << 6) | ((reg & 7) << 3) | (rm & 7)


class Assembler:
    def __init__(self):
        self.buf = bytearray()
        self.labels = {}        # name -> byte offset
        self._fixups = []       # (offset_of_rel32_field, label_name)

    def pos(self):
        return len(self.buf)

    def _emit(self, *bs):
        self.buf.extend(bs)

    def _emit_bytes(self, data: bytes):
        self.buf.extend(data)

    # ---- labels & relative-offset fixups ----

    def define_label(self, name):
        assert name not in self.labels, f"label {name!r} defined twice"
        self.labels[name] = self.pos()

    def _emit_rel32(self, label_name):
        """Emit a placeholder rel32 field and remember to patch it once
        every label's final address is known (labels may be defined
        later in the buffer than the jump/call that targets them --
        forward jumps and forward/mutual-recursive calls both need
        this)."""
        self._fixups.append((self.pos(), label_name))
        self._emit_bytes(b"\x00\x00\x00\x00")

    def resolve(self):
        for field_off, label in self._fixups:
            if label not in self.labels:
                raise KeyError(f"undefined label {label!r}")
            target = self.labels[label]
            rel = target - (field_off + 4)
            struct.pack_into("<i", self.buf, field_off, rel)
        self._fixups.clear()

    # ---- stack ----

    def push(self, reg):
        if reg >= 8:
            self._emit(_rex(w=0, b=1), 0x50 + (reg - 8))
        else:
            self._emit(0x50 + reg)

    def pop(self, reg):
        if reg >= 8:
            self._emit(_rex(w=0, b=1), 0x58 + (reg - 8))
        else:
            self._emit(0x58 + reg)

    # ---- data movement ----

    def movabs(self, reg, imm64: int):
        imm64 &= (1 << 64) - 1
        self._emit(_rex(b=1 if reg >= 8 else 0), 0xB8 + (reg & 7))
        self._emit_bytes(struct.pack("<Q", imm64))

    def mov_rr(self, dst, src):
        """mov dst, src  (dst = src)"""
        self._emit(_rex(r=(src >> 3) & 1, b=(dst >> 3) & 1), 0x89,
                    _modrm(0b11, src, dst))

    def load_slot(self, dst, disp32):
        """mov dst, [rbp + disp32]"""
        self._emit(_rex(r=(dst >> 3) & 1), 0x8B, _modrm(0b10, dst, RBP))
        self._emit_bytes(struct.pack("<i", disp32))

    def store_slot(self, disp32, src):
        """mov [rbp + disp32], src"""
        self._emit(_rex(r=(src >> 3) & 1), 0x89, _modrm(0b10, src, RBP))
        self._emit_bytes(struct.pack("<i", disp32))

    def store_slot_abs_ptr(self, base_reg, imm32):
        """mov qword [base_reg], imm32   (sign-extended to 64 bits)"""
        self._emit(_rex(b=(base_reg >> 3) & 1), 0xC7, _modrm(0b00, 0, base_reg))
        self._emit_bytes(struct.pack("<i", imm32))

    # ---- arithmetic (two-register forms) ----

    def add_rr(self, dst, src):
        self._emit(_rex(r=(src >> 3) & 1, b=(dst >> 3) & 1), 0x01, _modrm(0b11, src, dst))

    def sub_rr(self, dst, src):
        self._emit(_rex(r=(src >> 3) & 1, b=(dst >> 3) & 1), 0x29, _modrm(0b11, src, dst))

    def imul_rr(self, dst, src):
        self._emit(_rex(r=(dst >> 3) & 1, b=(src >> 3) & 1), 0x0F, 0xAF, _modrm(0b11, dst, src))

    def cqo(self):
        self._emit(_rex(), 0x99)

    def idiv_r(self, reg):
        self._emit(_rex(b=(reg >> 3) & 1), 0xF7, _modrm(0b11, 7, reg))

    def neg_r(self, reg):
        self._emit(_rex(b=(reg >> 3) & 1), 0xF7, _modrm(0b11, 3, reg))

    def cmp_rr(self, a, b):
        """compare a - b, set flags"""
        self._emit(_rex(r=(b >> 3) & 1, b=(a >> 3) & 1), 0x39, _modrm(0b11, b, a))

    def test_rr(self, a, b):
        self._emit(_rex(r=(b >> 3) & 1, b=(a >> 3) & 1), 0x85, _modrm(0b11, b, a))

    def setcc(self, cc):
        """SETcc al  (result is the low byte of rax)"""
        self._emit(0x0F, 0x90 | cc, _modrm(0b11, 0, RAX))

    def movzx_al(self, dst):
        """movzx dst, al"""
        self._emit(_rex(r=(dst >> 3) & 1), 0x0F, 0xB6, _modrm(0b11, dst, RAX))

    def xor_eax_eax(self):
        self._emit(0x31, 0xC0)

    # ---- stack frame adjustment ----

    def sub_rsp_imm32(self, imm32):
        self._emit(_rex(), 0x81, _modrm(0b11, 5, RSP))
        self._emit_bytes(struct.pack("<i", imm32))

    def add_rsp_imm32(self, imm32):
        self._emit(_rex(), 0x81, _modrm(0b11, 0, RSP))
        self._emit_bytes(struct.pack("<i", imm32))

    def mov_rsp_rbp(self):
        self.mov_rr(RSP, RBP)

    # ---- control flow ----

    def jmp(self, label):
        self._emit(0xE9)
        self._emit_rel32(label)

    def jcc(self, cc, label):
        self._emit(0x0F, 0x80 | cc)
        self._emit_rel32(label)

    def call(self, label):
        self._emit(0xE8)
        self._emit_rel32(label)

    def ret(self):
        self._emit(0xC3)
