"""Intel-syntax x86-64 assembler producing ELF64 relocatable objects."""
import re
from .errors import AsmError, FerruleError
from .expr import Expr, parse_expr, _ESC
from . import elf
from .elf import Section, Symbol, Reloc, ElfObject
from . import x86
from .x86 import REGS, RIP, Reg, Mem, Imm, Fix, Chunk, CC

NOPS = [b"", b"\x90", b"\x66\x90", b"\x0f\x1f\x00", b"\x0f\x1f\x40\x00", b"\x0f\x1f\x44\x00\x00",
        b"\x66\x0f\x1f\x44\x00\x00", b"\x0f\x1f\x80\x00\x00\x00\x00",
        b"\x0f\x1f\x84\x00\x00\x00\x00\x00", b"\x66\x0f\x1f\x84\x00\x00\x00\x00\x00"]

STD_SECTIONS = {
    ".text": (elf.SHT_PROGBITS, elf.SHF_ALLOC | elf.SHF_EXECINSTR),
    ".data": (elf.SHT_PROGBITS, elf.SHF_ALLOC | elf.SHF_WRITE),
    ".bss": (elf.SHT_NOBITS, elf.SHF_ALLOC | elf.SHF_WRITE),
    ".rodata": (elf.SHT_PROGBITS, elf.SHF_ALLOC),
}


# ------------------------------------------------------------------ items
class Item:
    size = 0
    def measure(self, off): return self.size


class Raw(Item):
    def __init__(self, chunk, line):
        self.chunk, self.line = chunk, line
        self.size = len(chunk.data)


class Label(Item):
    def __init__(self, name): self.name = name


class Align(Item):
    def __init__(self, boundary, fill, maxskip, code):
        self.boundary, self.fill, self.maxskip, self.code = boundary, fill, maxskip, code
        self.size = 0

    def measure(self, off):
        pad = (-off) % self.boundary
        if self.maxskip is not None and pad > self.maxskip:
            pad = 0
        self.size = pad
        return pad


class Space(Item):
    def __init__(self, n, fill): self.size, self.fill = n, fill


class Branch(Item):
    def __init__(self, mnem, target, line):
        self.mnem, self.target, self.line = mnem, target, line
        self.cc = CC[mnem[1:]] if mnem not in ("jmp", "call") else None
        self.short = mnem != "call"       # optimistic; grown during relaxation
        self.resolvable = False
        self.size = 2

    def measure(self, off):
        if self.mnem == "call":
            self.size = 5
        elif self.short and self.resolvable:
            self.size = 2
        else:
            self.size = 5 if self.mnem == "jmp" else 6
        return self.size


class ASection:
    def __init__(self, name, type, flags):
        self.name, self.type, self.flags = name, type, flags
        self.items = []
        self.align = 1
        self.size = 0
        self.elf = None


class ASym:
    def __init__(self, name):
        self.name = name
        self.section = None      # ASection once defined
        self.offset = 0
        self.const = None        # int if defined via .equ
        self.expr = None         # deferred .equ expression
        self.bind = elf.STB_LOCAL
        self.type = elf.STT_NOTYPE
        self.size = 0
        self.size_expr = None
        self.common = None       # (size, align)
        self.referenced = False


_LABEL = re.compile(r"^\s*([A-Za-z_.$][A-Za-z0-9_.$]*)\s*:(?!:)")
_SIZES = {"byte": 8, "word": 16, "dword": 32, "qword": 64}


def strip_comment(line):
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q and line[i - 1] != "\\":
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch in ";#":
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def split_top(s, sep=","):
    parts, depth, cur, q = [], 0, [], None
    for i, ch in enumerate(s):
        if q:
            cur.append(ch)
            if ch == q and s[i - 1] != "\\":
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail or parts:
        parts.append(tail)
    return parts


def parse_string(s):
    s = s.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        raise FerruleError(f"expected a quoted string, got {s!r}")
    body, out, i = s[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out += ch.encode()
            i += 1
            continue
        i += 1
        if i >= len(body):
            raise FerruleError("dangling backslash in string")
        c = body[i]
        if c == "x":
            m = re.match(r"[0-9a-fA-F]{1,2}", body[i + 1:])
            if not m:
                raise FerruleError("bad \\x escape")
            out.append(int(m.group(), 16))
            i += 1 + len(m.group())
        elif c in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i:])
            out.append(int(m.group(), 8) & 255)
            i += len(m.group())
        elif c in _ESC:
            out.append(_ESC[c])
            i += 1
        else:
            raise FerruleError(f"unknown escape \\{c}")
    return bytes(out)


class Assembler:
    def __init__(self, filename="<asm>"):
        self.filename = filename
        self.sections = {}
        self.order = []
        self.cur = None
        self.syms = {}
        self.line = 0
        self.use_section(".text")

    # ----------------------------------------------------------- symbols
    def sym(self, name):
        s = self.syms.get(name)
        if s is None:
            s = self.syms[name] = ASym(name)
        return s

    def lookup_const(self, name):
        s = self.syms.get(name)
        if s is not None and s.const is not None and s.section is None:
            return s.const
        return None

    def expr(self, text):
        try:
            e = parse_expr(text, self.lookup_const)
        except AsmError:
            raise
        except FerruleError as ex:
            raise AsmError(str(ex), self.line, self.filename)
        if "." in e.terms:
            # `.` is the location *of this directive/instruction*: pin it with a hidden label now,
            # so later growth of the section cannot change its meaning.
            self.dot_n = getattr(self, "dot_n", 0) + 1
            name = f".Ldot{self.dot_n}"
            self.define_label(name)
            terms = dict(e.terms)
            terms[name] = terms.pop(".")
            e = Expr(e.const, terms, e.mod)
        for t in e.terms:
            self.sym(t).referenced = True
        return e

    def err(self, msg):
        return AsmError(msg, self.line, self.filename)

    # ----------------------------------------------------------- sections
    def use_section(self, name, type=None, flags=None):
        sec = self.sections.get(name)
        if sec is None:
            std = STD_SECTIONS.get(name)
            if std is None:
                for pre in (".text.", ".data.", ".rodata.", ".bss."):
                    if name.startswith(pre):
                        std = STD_SECTIONS[pre[:-1]]
                        break
            t, f = std if std else (elf.SHT_PROGBITS, elf.SHF_ALLOC)
            sec = ASection(name, type if type is not None else t, flags if flags is not None else f)
            self.sections[name] = sec
            self.order.append(sec)
        self.cur = sec
        return sec

    def emit(self, item):
        self.cur.items.append(item)

    # ----------------------------------------------------------- driver
    def assemble(self, text):
        lines = text.splitlines()
        try:
            return self._assemble(lines)
        except AsmError as ex:
            if ex.line is not None and ex.source is None and 1 <= ex.line <= len(lines):
                raise AsmError(ex.bare, ex.line, ex.file, lines[ex.line - 1]) from None
            raise

    def _assemble(self, lines):
        for n, raw in enumerate(lines, 1):
            self.line = n
            line = strip_comment(raw)
            while True:
                m = _LABEL.match(line)
                if not m:
                    break
                self.define_label(m.group(1))
                line = line[m.end():].strip()
            if not line:
                continue
            try:
                if line.startswith("."):
                    self.directive(line)
                else:
                    self.instruction(line)
            except AsmError:
                raise
            except FerruleError as ex:
                raise self.err(str(ex))
        return self.finish()

    def define_label(self, name):
        s = self.sym(name)
        if s.section is not None or s.const is not None or s.common:
            raise self.err(f"symbol '{name}' is already defined")
        s.section = self.cur
        self.emit(Label(name))

    # ----------------------------------------------------------- directives
    def directive(self, line):
        parts = line.split(None, 1)
        d = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if d in (".text", ".data", ".bss"):
            self.use_section(d)
        elif d == ".rodata":
            self.use_section(".rodata")
        elif d == ".section":
            self.section_directive(arg)
        elif d in (".global", ".globl", ".weak", ".local"):
            for name in split_top(arg):
                s = self.sym(name)
                s.bind = {".global": elf.STB_GLOBAL, ".globl": elf.STB_GLOBAL,
                          ".weak": elf.STB_WEAK, ".local": elf.STB_LOCAL}[d]
                s.referenced = True
        elif d == ".type":
            name, _, kind = arg.partition(",")
            kind = kind.strip().lstrip("@%").lower()
            self.sym(name.strip()).type = {"function": elf.STT_FUNC, "object": elf.STT_OBJECT,
                                           "notype": elf.STT_NOTYPE}.get(kind, elf.STT_NOTYPE)
        elif d == ".size":
            name, _, ex = arg.partition(",")
            self.sym(name.strip()).size_expr = (self.cur, self.expr(ex.strip()))
        elif d in (".byte", ".word", ".short", ".value", ".long", ".int", ".quad", ".8byte", ".2byte", ".4byte"):
            size = {".byte": 1, ".word": 2, ".short": 2, ".value": 2, ".2byte": 2, ".long": 4,
                    ".int": 4, ".4byte": 4, ".quad": 8, ".8byte": 8}[d]
            for piece in split_top(arg):
                if not piece:
                    raise self.err(f"missing value in {d}")
                e = self.expr(piece)
                ch = Chunk(b"\0" * size, [Fix(0, size, "abs", e)])
                self.emit(Raw(ch, self.line))
        elif d in (".ascii", ".asciz", ".string"):
            for piece in split_top(arg):
                data = parse_string(piece)
                if d != ".ascii":
                    data += b"\0"
                self.emit(Raw(Chunk(data), self.line))
        elif d in (".zero", ".skip", ".space", ".fill"):
            ps = split_top(arg)
            n = self.const(ps[0], d)
            if d == ".fill":
                cnt = n
                width = self.const(ps[1], d) if len(ps) > 1 else 1
                val = self.const(ps[2], d) if len(ps) > 2 else 0
                if cnt < 0 or not 1 <= width <= 8:
                    raise self.err(".fill needs a non-negative count and a size of 1..8")
                self.check_size(cnt * width)
                self.emit(Raw(Chunk((val & ((1 << (8 * width)) - 1)).to_bytes(width, "little") * cnt), self.line))
                return
            fill = self.const(ps[1], d) if len(ps) > 1 else 0
            if n < 0:
                raise self.err(f"negative size in {d}")
            self.check_size(n)
            self.emit(Space(n, fill & 255))
        elif d in (".align", ".balign", ".p2align"):
            ps = split_top(arg)
            v = self.const(ps[0], d)
            if d == ".p2align" and not 0 <= v <= 24:
                raise self.err(f".p2align {v} out of range (0..24)")
            b = (1 << v) if d == ".p2align" else v
            if b > (1 << 24):
                raise self.err(f"alignment {b} is too large")
            if b <= 0 or b & (b - 1):
                raise self.err(f"alignment {b} is not a power of two")
            fill = self.const(ps[1], d) if len(ps) > 1 and ps[1] else None
            mx = self.const(ps[2], d) if len(ps) > 2 else None
            self.cur.align = max(self.cur.align, b)
            self.emit(Align(b, fill, mx, bool(self.cur.flags & elf.SHF_EXECINSTR)))
        elif d in (".equ", ".set"):
            name, _, ex = arg.partition(",")
            s = self.sym(name.strip())
            e = self.expr(ex.strip())
            if not e.is_const:
                s.expr = e
            else:
                s.const = e.const
        elif d == ".comm":
            ps = split_top(arg)
            if len(ps) < 2:
                raise self.err(".comm needs a name and a size")
            s = self.sym(ps[0])
            size = self.const(ps[1], d)
            al = self.const(ps[2], d) if len(ps) > 2 else 1
            if s.section is not None:
                raise self.err(f"symbol '{ps[0]}' is already defined")
            s.common = (size, al)
            s.bind = elf.STB_GLOBAL
            s.type = elf.STT_OBJECT
        elif d in (".file", ".ident", ".intel_syntax", ".att_syntax", ".code64", ".arch", ".cfi_startproc",
                   ".cfi_endproc", ".addrsig"):
            if d == ".att_syntax":
                raise self.err("AT&T syntax is not supported")
        else:
            raise self.err(f"unknown directive '{d}'")

    MAX_BLOCK = 1 << 28

    def check_size(self, n):
        if n > self.MAX_BLOCK:
            raise self.err(f"block of {n} bytes exceeds the assembler limit of {self.MAX_BLOCK}")

    def const(self, text, what):
        e = self.expr(text)
        if not e.is_const:
            raise self.err(f"{what} needs a constant expression")
        return e.const

    def section_directive(self, arg):
        ps = split_top(arg)
        name = ps[0].strip('"')
        type = flags = None
        if len(ps) > 1:
            fl = ps[1].strip('"')
            flags = 0
            for ch in fl:
                flags |= {"a": elf.SHF_ALLOC, "w": elf.SHF_WRITE, "x": elf.SHF_EXECINSTR,
                          "M": elf.SHF_MERGE, "S": elf.SHF_STRINGS}.get(ch, 0)
            type = elf.SHT_PROGBITS
        if len(ps) > 2:
            t = ps[2].lstrip("@%")
            type = {"progbits": elf.SHT_PROGBITS, "nobits": elf.SHT_NOBITS}.get(t)
            if type is None:
                raise self.err(f"unsupported section type '{ps[2]}'")
        self.use_section(name, type, flags)

    # ----------------------------------------------------------- operands
    def operand(self, text):
        text = text.strip()
        size = None
        m = re.match(r"^(byte|word|dword|qword)\b\s*(?:ptr\b)?\s*(.*)$", text, re.I)
        if m:
            size = _SIZES[m.group(1).lower()]
            text = m.group(2).strip()
        if text.startswith("["):
            if not text.endswith("]"):
                raise self.err(f"unterminated memory operand '{text}'")
            return self.memory(text[1:-1], size)
        if size is not None:
            raise self.err(f"size prefix on non-memory operand '{text}'")
        m = re.match(r"^offset\s+(.*)$", text, re.I)
        if m:                                   # `offset sym` = the address as an immediate
            return Imm(self.expr(m.group(1)))
        r = REGS.get(text.lower())
        if r is not None:
            if r is RIP:
                raise self.err("'rip' is only valid inside a memory operand")
            return r
        return Imm(self.expr(text))

    def memory(self, inner, size):
        base = index = None
        scale = 1
        disp_text = []
        pieces = re.findall(r"([+-]?)\s*([^+-]+(?:\([^)]*\))?)", inner.replace(" ", " "))
        # robust re-split respecting parentheses
        pieces, depth, cur = [], 0, ""
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch in "+-" and depth == 0 and cur.strip():
                pieces.append(cur)
                cur = ch
            else:
                cur += ch
        if cur.strip():
            pieces.append(cur)
        for p in pieces:
            p = p.strip()
            sign = 1
            if p.startswith("-"):
                sign, p = -1, p[1:].strip()
            elif p.startswith("+"):
                p = p[1:].strip()
            r = REGS.get(p.lower())
            ms = re.match(r"^([A-Za-z0-9]+)\s*\*\s*([A-Za-z0-9]+)$", p)
            if r is not None:
                if sign < 0:
                    raise self.err("cannot subtract a register in an address")
                if r is RIP or base is None:
                    if base is not None and r is not RIP:
                        pass
                if r is RIP:
                    if base is not None:
                        raise self.err("rip cannot be combined with another base")
                    base = RIP
                elif base is None:
                    base = r
                elif index is None:
                    index = r
                else:
                    raise self.err("too many registers in address")
            elif ms and (ms.group(1).lower() in REGS or ms.group(2).lower() in REGS):
                a, b = ms.group(1), ms.group(2)
                if a.lower() in REGS:
                    rr, sc = REGS[a.lower()], b
                else:
                    rr, sc = REGS[b.lower()], a
                try:
                    sc = int(sc, 0)
                except ValueError:
                    raise self.err(f"bad scale '{sc}'")
                if sc not in (1, 2, 4, 8):
                    raise self.err(f"scale must be 1, 2, 4 or 8, not {sc}")
                if index is not None:
                    raise self.err("two index registers in address")
                if sign < 0:
                    raise self.err("cannot subtract a register in an address")
                index, scale = rr, sc
            else:
                disp_text.append(("-" if sign < 0 else "+") + "(" + p + ")")
        if index is not None and base is None and scale == 1 and index.num == 4:
            base, index = index, None      # [rsp*1] can only be a base
        disp = self.expr("".join(disp_text) or "0")
        return Mem(base, index, scale, disp, size)

    # ----------------------------------------------------------- instructions
    def instruction(self, line):
        toks = line.split(None, 1)
        mnem = toks[0].lower()
        rest = toks[1] if len(toks) > 1 else ""
        prefix = b""
        while mnem in ("lock", "rep", "repe", "repz", "repne", "repnz"):
            prefix += {"lock": b"\xf0", "rep": b"\xf3", "repe": b"\xf3", "repz": b"\xf3",
                       "repne": b"\xf2", "repnz": b"\xf2"}[mnem]
            if not rest:
                raise self.err(f"'{mnem}' needs an instruction")
            toks = rest.split(None, 1)
            mnem = toks[0].lower()
            rest = toks[1] if len(toks) > 1 else ""
        if mnem in ("jmp", "call") or (mnem.startswith("j") and mnem[1:] in CC):
            ops = split_top(rest)
            if len(ops) != 1 or not ops[0]:
                raise self.err(f"'{mnem}' takes exactly one operand")
            o = ops[0]
            first = o.strip()
            if mnem in ("jmp", "call") and (first.startswith("[") or re.match(r"^(qword)\b", first, re.I)
                                             or first.lower() in REGS):
                op = self.operand(o)
                ch = x86.encode_indirect_branch(mnem, op)
            else:
                if mnem in ("jmp", "call") or True:
                    e = self.expr(o)
                    if e.is_const:
                        raise self.err(f"'{mnem}' target must be a symbol or label")
                    self.emit(Branch(mnem, e, self.line))
                    if prefix:
                        raise self.err("prefix not allowed on branches")
                    return
            self.emit(Raw(self.with_prefix(prefix, ch) if prefix else ch, self.line))
            return
        ops = [self.operand(o) for o in split_top(rest)] if rest else []
        if any(o == "" for o in split_top(rest)) and rest:
            raise self.err("empty operand")
        try:
            ch = x86.encode(mnem, ops)
        except AsmError:
            raise
        except FerruleError as ex:
            raise self.err(str(ex))
        if prefix:
            ch = self.with_prefix(prefix, ch)
        self.emit(Raw(ch, self.line))

    @staticmethod
    def with_prefix(prefix, ch):
        """Insert lock/rep prefixes after an operand-size (0x66) prefix, before REX/opcode."""
        at = 1 if ch.data[:1] == b"\x66" else 0
        data = ch.data[:at] + prefix + ch.data[at:]
        return Chunk(data, [Fix(f.offset + len(prefix), f.size, f.kind, f.expr, f.signed, f.trail)
                            for f in ch.fixes])

    # ----------------------------------------------------------- layout / output
    def sym_section_local(self, name):
        s = self.syms.get(name)
        return s if s is not None and s.section is not None else None

    def expand(self, e, seen=()):
        """Substitute symbols defined by `.equ name, <relocatable expr>` (aliases of labels)."""
        if not any(self.syms[t].expr is not None for t in e.terms if t in self.syms):
            return e
        out = Expr(e.const, {}, e.mod)
        for t, c in e.terms.items():
            s = self.syms.get(t)
            if s is not None and s.expr is not None and s.const is None:
                if t in seen:
                    raise AsmError(f"circular .equ definition involving '{t}'", None, self.filename)
                out = out.add(self.expand(s.expr, seen + (t,)).scale(c))
            else:
                out = out.add(Expr(0, {t: c}))
        return out

    def expand_all(self):
        for sec in self.order:
            for it in sec.items:
                if isinstance(it, Raw):
                    for f in it.chunk.fixes:
                        try:
                            f.expr = self.expand(f.expr)
                        except AsmError as ex:
                            raise AsmError(ex.bare, it.line, self.filename)
                elif isinstance(it, Branch):
                    try:
                        it.target = self.expand(it.target)
                    except AsmError as ex:
                        raise AsmError(ex.bare, it.line, self.filename)

    def layout(self):
        # which branches can ever be short: target is a label in the same section and not global/weak
        for sec in self.order:
            for it in sec.items:
                if isinstance(it, Branch):
                    it.resolvable = False
                    e = it.target
                    if len(e.terms) == 1 and list(e.terms.values()) == [1] and not e.mod:
                        s = self.syms.get(next(iter(e.terms)))
                        if s and s.section is sec and s.bind == elf.STB_LOCAL and s.const is None:
                            it.resolvable = True
                    it.short = it.short and it.resolvable
        for _ in range(64):
            changed = False
            for sec in self.order:
                off = 0
                for it in sec.items:
                    if isinstance(it, Label):
                        self.syms[it.name].offset = off
                    off += it.measure(off)
                sec.size = off
            for sec in self.order:
                off = 0
                for it in sec.items:
                    if isinstance(it, Branch) and it.short and it.resolvable:
                        s = self.syms[next(iter(it.target.terms))]
                        d = s.offset + it.target.const - (off + it.size)
                        if not -128 <= d <= 127:
                            it.short = False
                            changed = True
                    off += it.size
            if not changed:
                return
        raise FerruleError("branch relaxation did not converge")

    def finish(self):
        for _ in range(len(self.syms) + 1):   # deferred .equ chains of constants
            progress = False
            for s in self.syms.values():
                if s.expr is not None and s.const is None and self.try_fold(s):
                    progress = True
            if not progress:
                break
        for s in self.syms.values():
            if s.expr is not None and s.const is None and s.bind != elf.STB_LOCAL:
                raise AsmError(f"'.equ {s.name}' aliases a relocatable expression and cannot be global",
                               None, self.filename)
        self.expand_all()
        self.layout()
        obj = ElfObject(self.filename)
        out_secs = {}
        for sec in self.order:
            data = bytearray()
            relocs = []
            sec.relocs_pending = []
            if sec.type == elf.SHT_NOBITS:
                for it in sec.items:
                    if isinstance(it, Raw):
                        raise AsmError(f"section {sec.name} is NOBITS and cannot hold initialised data",
                                       it.line, self.filename)
                es = Section(sec.name, sec.type, sec.flags, b"", sec.align, size=sec.size)
            else:
                off = 0
                for it in sec.items:
                    if isinstance(it, Raw):
                        base = len(data)
                        buf = bytearray(it.chunk.data)
                        for f in it.chunk.fixes:
                            self.resolve_fix(sec, buf, f, base, it.line)
                        data += buf
                    elif isinstance(it, Space):
                        data += bytes([it.fill]) * it.size
                    elif isinstance(it, Align):
                        data += self.pad_bytes(it)
                    elif isinstance(it, Branch):
                        data += self.encode_branch(sec, it, len(data))
                es = Section(sec.name, sec.type, sec.flags, bytes(data), sec.align)
            sec.elf = es
            out_secs[sec.name] = es
            obj.sections.append(es)
        # symbols
        osyms = {}
        file_sym = Symbol(self.filename.split("/")[-1], 0, 0, elf.STB_LOCAL, elf.STT_FILE, 0, elf.SHN_ABS)
        obj.symbols.append(file_sym)
        secsym = {}
        for sec in self.order:
            sy = Symbol("", 0, 0, elf.STB_LOCAL, elf.STT_SECTION, 0, section=sec.elf)
            secsym[sec.name] = sy
            obj.symbols.append(sy)
        for name, s in self.syms.items():
            if s.section is None and s.const is None and s.common is None and not s.referenced:
                continue
            if s.section is None and s.const is not None and s.expr is None and not s.referenced:
                pass
            if name.startswith(".L") and s.bind == elf.STB_LOCAL:
                continue
            if s.expr is not None and s.const is None and s.section is None:
                continue                      # label alias: only meaningful inside this file
            if s.section is None and s.const is None and s.common is None and s.bind == elf.STB_LOCAL \
                    and not s.referenced:
                continue
            bind = s.bind
            sy = Symbol(name, 0, s.size, bind, s.type)
            if s.section is not None:
                sy.section, sy.value = s.section.elf, s.offset
                if s.size_expr:
                    sy.size = self.size_value(s)
            elif s.common:
                sy.shndx, sy.value, sy.size = elf.SHN_COMMON, s.common[1], s.common[0]
            elif s.const is not None:
                sy.shndx, sy.value = elf.SHN_ABS, s.const
            else:
                sy.shndx = elf.SHN_UNDEF
                if bind == elf.STB_LOCAL:
                    sy.bind = elf.STB_GLOBAL      # use of an undefined symbol implies extern
            osyms[name] = sy
            obj.symbols.append(sy)
        self.osyms, self.secsym = osyms, secsym
        # relocations (second sweep now that Symbol objects exist)
        for sec in self.order:
            for (off, rtype, name, addend) in sec.relocs_pending:
                if name in osyms and osyms[name].bind != elf.STB_LOCAL or \
                        (name in osyms and osyms[name].section is None):
                    sym = osyms[name]
                else:
                    s = self.syms[name]
                    sym = secsym[s.section.name]
                    addend += s.offset
                sec.elf.relocs.append(Reloc(off, sym, rtype, addend))
        return obj

    def size_value(self, s):
        sec, e = s.size_expr
        cur = 0
        for t, c in e.terms.items():
            ts = self.syms.get(t)
            if ts is None or ts.section is not sec or ts.const is not None:
                raise AsmError(f".size of '{s.name}' must be a constant or label differences within one section",
                               None, self.filename)
            cur += c * ts.offset
        return cur + e.const

    def try_fold(self, s):
        e = s.expr
        total = e.const
        for t, c in e.terms.items():
            ts = self.syms.get(t)
            if ts is None or ts.const is None or ts.section is not None:
                return False
            total += c * ts.const
        s.const, s.expr = total, None
        return True

    def pad_bytes(self, it):
        n = it.size
        if it.fill is not None:
            return bytes([it.fill & 255]) * n
        if not it.code:
            return b"\0" * n
        out = b""
        while n > 0:
            k = min(n, 9)
            out += NOPS[k]
            n -= k
        return out

    # ---- resolving fixups
    def resolve_fix(self, sec, buf, f, base, line):
        """Patch `buf` at f.offset, or queue a relocation in sec.relocs_pending.

        Shapes handled:  const | S + c | S - L + c (L a label of this section, or '.') .
        """
        def fail(msg):
            return AsmError(msg, line, self.filename)
        e = f.expr
        field = base + f.offset
        const, pos, sub_off = e.const, [], None
        terms = dict(e.terms)
        labels = {t: self.syms[t] for t in terms if self.syms[t].section is not None
                  and self.syms[t].const is None and self.syms[t].common is None}
        for pn in [t for t, c in terms.items() if c > 0 and t in labels]:       # (A - B) inside one section
            for nn in [t for t, c in terms.items() if c < 0 and t in labels]:
                if terms.get(pn, 0) > 0 and terms.get(nn, 0) < 0 and labels[pn].section is labels[nn].section:
                    k = min(terms[pn], -terms[nn])
                    const += k * (labels[pn].offset - labels[nn].offset)
                    terms[pn] -= k
                    terms[nn] += k
        terms = {t: c for t, c in terms.items() if c}
        for t, c in terms.items():
            s = self.syms[t]
            if s.const is not None and s.section is None and s.expr is None:
                const += c * s.const
            elif c == 1:
                pos.append(s)
            elif c == -1 and s.section is sec and s.common is None and sub_off is None:
                sub_off = s.offset
            else:
                raise fail(f"cannot relocate this use of '{t}' (coefficient {c}, "
                           "or subtracted symbol outside the current section)")
        if len(pos) > 1:
            raise fail("expression has more than one relocatable symbol")
        pcrel = f.kind == "pc"
        if not pos:
            if pcrel or sub_off is not None:
                raise fail("pc-relative reference needs a symbol")
            self.patch(buf, f, const, line)
            return
        s = pos[0]
        if pcrel and sub_off is not None:
            raise fail("cannot combine a pc-relative operand with a symbol difference")
        fixed = s.section is sec and s.bind == elf.STB_LOCAL and s.common is None
        if pcrel:
            if fixed:
                self.patch(buf, f, s.offset + const - (field + f.size + f.trail), line)
                return
            addend = const - (f.size + f.trail)
            rtype = {"PLT": elf.R_X86_64_PLT32, "GOTPCREL": elf.R_X86_64_GOTPCREL}.get(e.mod, elf.R_X86_64_PC32)
        elif sub_off is not None:
            if fixed:
                self.patch(buf, f, s.offset + const - sub_off, line)
                return
            if f.size not in (4, 8):
                raise fail("symbol difference against another section needs a 4- or 8-byte field")
            addend = const + field - sub_off
            rtype = elf.R_X86_64_PC32 if f.size == 4 else elf.R_X86_64_PC64
        else:
            if e.mod == "GOTPCREL":
                raise fail("@GOTPCREL is only valid in a rip-relative memory operand")
            addend = const
            rtype = {(8, False): elf.R_X86_64_64, (8, True): elf.R_X86_64_64,
                     (4, False): elf.R_X86_64_32, (4, True): elf.R_X86_64_32S,
                     (2, False): elf.R_X86_64_16, (2, True): elf.R_X86_64_16,
                     (1, False): elf.R_X86_64_8, (1, True): elf.R_X86_64_8}[(f.size, f.signed)]
        if s.section is None and s.const is None and s.common is None:
            pass    # undefined: reloc against the (to be created) global symbol
        sec.relocs_pending.append((field, rtype, s.name, addend))

    def patch(self, buf, f, val, line):
        bits = f.size * 8
        lo = -(1 << (bits - 1))
        hi = (1 << bits) - 1 if not (f.signed or f.kind == "pc") else (1 << (bits - 1)) - 1
        if f.kind == "abs" and not f.signed:
            lo = -(1 << (bits - 1))
        if not lo <= val <= hi:
            raise AsmError(f"value {val:#x} does not fit in {f.size} byte(s)", line, self.filename)
        buf[f.offset:f.offset + f.size] = (val & ((1 << bits) - 1)).to_bytes(f.size, "little")

    def encode_branch(self, sec, it, field_start):
        e = it.target
        name = next(iter(e.terms)) if len(e.terms) == 1 else None
        if name is None or e.terms[name] != 1:
            raise AsmError("branch target must be a single symbol (plus constant)", it.line, self.filename)
        s = self.syms[name]
        if it.mnem == "call":
            opc = b"\xe8"
        elif it.mnem == "jmp":
            opc = b"\xeb" if it.size == 2 else b"\xe9"
        else:
            opc = bytes([0x70 | it.cc]) if it.size == 2 else bytes([0x0F, 0x80 | it.cc])
        if it.size == 2:
            d = s.offset + e.const - (field_start + 2)
            if not -128 <= d <= 127:
                raise AsmError("internal: short branch out of range", it.line, self.filename)
            return opc + bytes([d & 255])
        buf = bytearray(opc + b"\0\0\0\0")
        if not e.mod:
            e = Expr(e.const, e.terms, "PLT")        # calls/jumps to other symbols go through PLT32
        fix = Fix(len(opc), 4, "pc", e, signed=True, trail=0)
        self.resolve_fix(sec, buf, fix, field_start, it.line)
        return bytes(buf)


def assemble(text, filename="<asm>"):
    """Assemble source text into an ElfObject."""
    return Assembler(filename).assemble(text)


def assemble_to_bytes(text, filename="<asm>"):
    return assemble(text, filename).to_bytes()
