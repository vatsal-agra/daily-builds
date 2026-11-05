"""ELF64 little-endian x86-64 relocatable-object reader and writer."""
import struct
from .errors import FerruleError

# e_type / machine
ET_REL, ET_EXEC = 1, 2
EM_X86_64 = 62
# section types
SHT_NULL, SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB, SHT_RELA = 0, 1, 2, 3, 4
SHT_NOBITS, SHT_GROUP, SHT_X86_64_UNWIND = 8, 17, 0x70000001
# section flags
SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 1, 2, 4
SHF_MERGE, SHF_STRINGS, SHF_INFO_LINK, SHF_GROUP, SHF_TLS = 0x10, 0x20, 0x40, 0x200, 0x400
# symbols
STB_LOCAL, STB_GLOBAL, STB_WEAK = 0, 1, 2
STT_NOTYPE, STT_OBJECT, STT_FUNC, STT_SECTION, STT_FILE, STT_COMMON, STT_TLS = 0, 1, 2, 3, 4, 5, 6
SHN_UNDEF, SHN_ABS, SHN_COMMON = 0, 0xFFF1, 0xFFF2
# relocation types
R_X86_64_NONE, R_X86_64_64, R_X86_64_PC32, R_X86_64_GOT32 = 0, 1, 2, 3
R_X86_64_PLT32, R_X86_64_GOTPCREL = 4, 9
R_X86_64_32, R_X86_64_32S, R_X86_64_16, R_X86_64_PC16 = 10, 11, 12, 13
R_X86_64_8, R_X86_64_PC8, R_X86_64_PC64 = 14, 15, 24
R_X86_64_GOTPCRELX, R_X86_64_REX_GOTPCRELX = 41, 42

RELOC_NAMES = {0: "R_X86_64_NONE", 1: "R_X86_64_64", 2: "R_X86_64_PC32", 3: "R_X86_64_GOT32",
               4: "R_X86_64_PLT32", 9: "R_X86_64_GOTPCREL", 10: "R_X86_64_32",
               11: "R_X86_64_32S", 12: "R_X86_64_16", 13: "R_X86_64_PC16", 14: "R_X86_64_8",
               15: "R_X86_64_PC8", 24: "R_X86_64_PC64", 41: "R_X86_64_GOTPCRELX",
               42: "R_X86_64_REX_GOTPCRELX"}

EHDR = struct.Struct("<16sHHIQQQIHHHHHH")   # 64 bytes
SHDR = struct.Struct("<IIQQQQIIQQ")         # 64 bytes
PHDR = struct.Struct("<IIQQQQQQ")           # 56 bytes
SYM = struct.Struct("<IBBHQQ")              # 24 bytes
RELA = struct.Struct("<QQq")                # 24 bytes


class Section:
    def __init__(self, name, type=SHT_PROGBITS, flags=0, data=b"", align=1, size=None,
                 link=0, info=0, entsize=0):
        self.name, self.type, self.flags = name, type, flags
        self.data = bytes(data)
        self.size = len(self.data) if size is None else size   # NOBITS has size but no data
        self.align, self.link, self.info, self.entsize = max(align, 1), link, info, entsize
        self.index = 0
        self.relocs = []          # list[Reloc] applying to this section

    def __repr__(self):
        return f"<Section {self.name} sz={self.size}>"


class Symbol:
    def __init__(self, name="", value=0, size=0, bind=STB_LOCAL, type=STT_NOTYPE,
                 other=0, shndx=SHN_UNDEF, section=None):
        self.name, self.value, self.size = name, value, size
        self.bind, self.type, self.other = bind, type, other
        self._shndx = shndx
        self.section = section    # Section object for regular defined symbols

    @property
    def shndx(self):
        """Section index; for symbols bound to a Section object it is that section's index."""
        if self.section is not None:
            return self.section.index or 1
        return self._shndx

    @shndx.setter
    def shndx(self, v):
        self._shndx = v

    @property
    def defined(self):
        return self.shndx != SHN_UNDEF

    def __repr__(self):
        return f"<Symbol {self.name!r} b{self.bind} t{self.type} sh{self.shndx} v{self.value:#x}>"


class Reloc:
    def __init__(self, offset, sym, type, addend):
        self.offset, self.sym, self.type, self.addend = offset, sym, type, addend


class ElfObject:
    """A parsed or constructed relocatable object."""

    def __init__(self, name="<obj>"):
        self.name = name
        self.sections = []        # real sections only (no null, symtab, strtab, rela)
        self.symbols = []         # no null symbol
        self.groups = {}          # section -> signature (COMDAT)

    # ------------------------------------------------------------------ parsing
    @classmethod
    def parse(cls, data, name="<obj>"):
        def bad(msg):
            raise FerruleError(f"{name}: {msg}")
        if len(data) < 64 or data[:4] != b"\x7fELF":
            bad("not an ELF file")
        if data[4] != 2 or data[5] != 1:
            bad("not a 64-bit little-endian ELF file")
        (_, etype, machine, _v, _entry, _phoff, shoff, _fl, _ehs, _phes, _phn,
         shentsize, shnum, shstrndx) = EHDR.unpack_from(data, 0)
        if etype != ET_REL:
            bad("not a relocatable object (ET_REL)")
        if machine != EM_X86_64:
            bad(f"unsupported machine {machine} (only x86-64)")
        if shoff == 0 or shentsize != SHDR.size:
            bad("missing or malformed section header table")
        if shoff + shnum * SHDR.size > len(data):
            bad("section header table extends past end of file")
        raw = []
        for i in range(shnum):
            raw.append(SHDR.unpack_from(data, shoff + i * SHDR.size))
        if shstrndx >= shnum:
            bad("bad section-name string table index")

        def blob(h):
            off, size = h[4], h[5]
            if h[1] == SHT_NOBITS:
                return b""
            if off + size > len(data):
                bad("section data extends past end of file")
            return data[off:off + size]

        def cstr(tab, off):
            if off >= len(tab):
                bad("string table offset out of range")
            end = tab.index(b"\0", off) if b"\0" in tab[off:] else len(tab)
            return tab[off:end].decode("utf-8", "replace")

        shstr = blob(raw[shstrndx])
        obj = cls(name)
        by_index = {}
        symtab_h = strtab = None
        symtab_idx = None
        for i, h in enumerate(raw):
            (nm, typ, flags, _addr, _off, size, link, info, align, entsize) = h
            if typ == SHT_NULL:
                continue
            if typ == SHT_SYMTAB:
                symtab_h, symtab_idx = h, i
                continue
            if typ in (SHT_STRTAB, SHT_RELA):
                continue
            if typ == SHT_GROUP:
                gd = blob(h)
                by_index[i] = ("group", h, gd)
                continue
            sec = Section(cstr(shstr, nm), typ, flags, blob(h), align,
                          size=size if typ == SHT_NOBITS else None, entsize=entsize)
            sec.index = i
            by_index[i] = sec
            obj.sections.append(sec)
        if symtab_h is None:
            symtab_h = None
        syms = [None]
        if symtab_h is not None:
            strtab = blob(raw[symtab_h[6]])
            sd = blob(symtab_h)
            n = len(sd) // SYM.size
            for k in range(1, n):
                (stn, sinfo, sother, shndx, value, size) = SYM.unpack_from(sd, k * SYM.size)
                s = Symbol(cstr(strtab, stn), value, size, sinfo >> 4, sinfo & 15, sother, shndx)
                if 0 < shndx < 0xFF00:
                    sec = by_index.get(shndx)
                    if not isinstance(sec, Section):
                        # symbol in a section we do not model (e.g. group) -> treat as undefined-free abs
                        sec = None
                    s.section = sec
                syms.append(s)
            obj.symbols = syms[1:]
        for i, h in enumerate(raw):
            if h[1] != SHT_RELA:
                continue
            target = by_index.get(h[7])
            if h[6] != symtab_idx:
                bad("relocation section refers to an unexpected symbol table")
            rd = blob(h)
            if not isinstance(target, Section):
                continue
            for k in range(len(rd) // RELA.size):
                off, rinfo, addend = RELA.unpack_from(rd, k * RELA.size)
                si = rinfo >> 32
                if si >= len(syms):
                    bad(f"relocation refers to symbol index {si} out of range")
                target.relocs.append(Reloc(off, syms[si] if si else None, rinfo & 0xFFFFFFFF, addend))
        for i, ent in by_index.items():
            if isinstance(ent, tuple):
                _, h, gd = ent
                if len(gd) >= 4 and h[7] < len(syms) and syms[h[7]] is not None:
                    flags = struct.unpack_from("<I", gd, 0)[0]
                    if flags & 1:  # GRP_COMDAT
                        members = [by_index[m] for m in struct.unpack_from(f"<{(len(gd)-4)//4}I", gd, 4)
                                   if isinstance(by_index.get(m), Section)]
                        for m in members:
                            obj.groups[m] = syms[h[7]].name
        return obj

    # ------------------------------------------------------------------ writing
    def to_bytes(self):
        return write_object(self)


class _StrTab:
    def __init__(self):
        self.buf = bytearray(b"\0")
        self.cache = {"": 0}

    def add(self, s):
        if s in self.cache:
            return self.cache[s]
        off = len(self.buf)
        self.buf += s.encode() + b"\0"
        self.cache[s] = off
        return off


def write_object(obj):
    """Serialise an ElfObject to ELF64 ET_REL bytes (locals-first symtab, .rela.* sections)."""
    shstr = _StrTab()
    strtab = _StrTab()
    # ---- symbol ordering: locals first
    syms = obj.symbols
    locals_ = [s for s in syms if s.bind == STB_LOCAL]
    globals_ = [s for s in syms if s.bind != STB_LOCAL]
    ordered = locals_ + globals_
    sym_index = {id(s): i + 1 for i, s in enumerate(ordered)}
    secs = list(obj.sections)
    # section header layout: null, secs..., rela..., symtab, strtab, shstrtab
    out_secs = [None] + secs
    for i, s in enumerate(secs):
        s.index = i + 1
    rela_secs = []
    for s in secs:
        if s.relocs:
            rela_secs.append(s)
    nsec = 1 + len(secs) + len(rela_secs) + 3
    symtab_i = 1 + len(secs) + len(rela_secs)
    strtab_i, shstr_i = symtab_i + 1, symtab_i + 2

    body = bytearray(b"\0" * 64)
    headers = [None] * nsec
    headers[0] = (0,) * 10

    def place(data, align):
        while len(body) % align:
            body.append(0)
        off = len(body)
        body.extend(data)
        return off

    for i, s in enumerate(secs, 1):
        if s.type == SHT_NOBITS:
            off = place(b"", s.align)
            size = s.size
        else:
            off = place(s.data, s.align)
            size = len(s.data)
        headers[i] = (shstr.add(s.name), s.type, s.flags, 0, off, size, 0, 0, s.align, s.entsize)
    for j, s in enumerate(rela_secs):
        data = bytearray()
        for r in s.relocs:
            si = sym_index[id(r.sym)] if r.sym is not None else 0
            data += RELA.pack(r.offset, (si << 32) | r.type, r.addend)
        off = place(bytes(data), 8)
        headers[1 + len(secs) + j] = (shstr.add(".rela" + s.name), SHT_RELA, SHF_INFO_LINK, 0, off,
                                      len(data), symtab_i, s.index, 8, RELA.size)
    sd = bytearray(SYM.pack(0, 0, 0, 0, 0, 0))
    for s in ordered:
        if s.section is not None:
            shndx = s.section.index
        else:
            shndx = s.shndx
        sd += SYM.pack(strtab.add(s.name), (s.bind << 4) | s.type, s.other, shndx, s.value, s.size)
    off = place(bytes(sd), 8)
    headers[symtab_i] = (shstr.add(".symtab"), SHT_SYMTAB, 0, 0, off, len(sd), strtab_i,
                         len(locals_) + 1, 8, SYM.size)
    off = place(bytes(strtab.buf), 1)
    headers[strtab_i] = (shstr.add(".strtab"), SHT_STRTAB, 0, 0, off, len(strtab.buf), 0, 0, 1, 0)
    nm = shstr.add(".shstrtab")
    off = place(bytes(shstr.buf), 1)
    headers[shstr_i] = (nm, SHT_STRTAB, 0, 0, off, len(shstr.buf), 0, 0, 1, 0)
    shoff = place(b"", 8)
    for h in headers:
        body += SHDR.pack(*h)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    body[0:64] = EHDR.pack(ident, ET_REL, EM_X86_64, 1, 0, 0, shoff, 0, 64, 0, 0, SHDR.size,
                           nsec, shstr_i)
    return bytes(body)


def read_object(path):
    with open(path, "rb") as f:
        return ElfObject.parse(f.read(), path)
