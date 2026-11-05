"""readelf/nm-style inspectors and the linker map file."""
from . import elf
from .elf import ElfObject
from .ar import Archive, is_archive

_BIND = {0: "LOCAL", 1: "GLOBAL", 2: "WEAK"}
_TYPE = {0: "NOTYPE", 1: "OBJECT", 2: "FUNC", 3: "SECTION", 4: "FILE", 5: "COMMON", 6: "TLS"}


def _flags(f):
    return "".join(c for bit, c in ((elf.SHF_WRITE, "W"), (elf.SHF_ALLOC, "A"), (elf.SHF_EXECINSTR, "X")) if f & bit)


def dump_object(obj):
    lines = [f"Object {obj.name}", "", "Sections:"]
    lines.append(f"  {'#':>2} {'name':<22}{'size':>8} {'align':>5}  flags")
    for i, s in enumerate(obj.sections, 1):
        lines.append(f"  {i:>2} {s.name:<22}{s.size:>8} {s.align:>5}  {_flags(s.flags)}"
                     f"{' NOBITS' if s.type == elf.SHT_NOBITS else ''}")
    lines += ["", "Symbols:"]
    lines.append(f"  {'value':>16} {'size':>6} {'type':<8}{'bind':<7}{'section':<16}name")
    for s in obj.symbols:
        if s.type == elf.STT_FILE:
            sec = "ABS"
        elif s.section is not None:
            sec = s.section.name
        else:
            sec = {elf.SHN_UNDEF: "UND", elf.SHN_ABS: "ABS", elf.SHN_COMMON: "COM"}.get(s.shndx, str(s.shndx))
        lines.append(f"  {s.value:016x} {s.size:>6} {_TYPE.get(s.type, s.type):<8}{_BIND.get(s.bind, s.bind):<7}"
                     f"{sec:<16}{s.name or '(section)'}")
    any_rel = False
    for s in obj.sections:
        if s.relocs:
            if not any_rel:
                lines += ["", "Relocations:"]
                any_rel = True
            lines.append(f"  [{s.name}]")
            for r in s.relocs:
                nm = r.sym.name if r.sym is not None and r.sym.name else (r.sym.section.name if r.sym is not None and r.sym.section else "-")
                lines.append(f"    {r.offset:08x}  {elf.RELOC_NAMES.get(r.type, r.type):<22} {nm}{r.addend:+d}")
    return "\n".join(lines)


def dump_archive(ar):
    lines = [f"Archive {ar.name}: {len(ar.members)} member(s)"]
    for i, m in enumerate(ar.members):
        syms = sorted(n for n, k in ar.index.items() if k == i)
        lines.append(f"  {m.name:<28}{len(m.data):>8} B   defines: {' '.join(syms) or '-'}")
    return "\n".join(lines)


def parse_exe(data):
    """Minimal ET_EXEC parser: returns (entry, segments, sections, symbols)."""
    import struct
    h = elf.EHDR.unpack_from(data, 0)
    if data[:4] != b"\x7fELF" or h[1] != elf.ET_EXEC:
        raise ValueError("not an ET_EXEC ELF file")
    entry, phoff, shoff, phnum, shnum, shstrndx = h[4], h[5], h[6], h[10], h[12], h[13]
    segs = [elf.PHDR.unpack_from(data, phoff + i * 56) for i in range(phnum)]
    raw = [elf.SHDR.unpack_from(data, shoff + i * 64) for i in range(shnum)]
    shstr = data[raw[shstrndx][4]:raw[shstrndx][4] + raw[shstrndx][5]]
    def nm(t, o):
        return t[o:t.index(b"\0", o)].decode()
    secs = [(nm(shstr, r[0]), r) for r in raw[1:]]
    syms = []
    for name, r in secs:
        if name == ".symtab":
            st = data[raw[r[6]][4]:raw[raw[r[6]] and r[6]][4] + raw[r[6]][5]]
            sd = data[r[4]:r[4] + r[5]]
            for i in range(1, len(sd) // 24):
                n, info, other, shndx, val, size = elf.SYM.unpack_from(sd, i * 24)
                syms.append((nm(st, n), val, size, info >> 4, info & 15, shndx))
    return entry, segs, secs, syms


def dump_exe(data, name="a.out"):
    entry, segs, secs, syms = parse_exe(data)
    lines = [f"Executable {name}  entry={entry:#x}  size={len(data)} B", "", "Segments:"]
    for p in segs:
        t, fl, off, va, _pa, fsz, msz, al = p
        tn = {1: "LOAD", 0x6474e551: "GNU_STACK"}.get(t, hex(t))
        f = ("R" if fl & 4 else "-") + ("W" if fl & 2 else "-") + ("X" if fl & 1 else "-")
        lines.append(f"  {tn:<10} {f}  off={off:#08x} vaddr={va:#010x} filesz={fsz:#x} memsz={msz:#x}")
    lines += ["", "Sections:"]
    for n, r in secs:
        lines.append(f"  {n:<12} addr={r[3]:#010x} off={r[4]:#08x} size={r[5]:#x}")
    return "\n".join(lines)


def nm(data_or_obj):
    """Return nm-style lines for an object, archive bytes or executable bytes."""
    out = []
    if isinstance(data_or_obj, ElfObject):
        for s in data_or_obj.symbols:
            if not s.name or s.type in (elf.STT_FILE, elf.STT_SECTION):
                continue
            letter = _nm_letter(s, data_or_obj)
            out.append((s.value if s.shndx != elf.SHN_UNDEF else None, letter, s.name))
        return [f"{'' if v is None else format(v, '016x'):>16} {l} {n}" for v, l, n in sorted(out, key=lambda x: (x[2]))]
    entry, segs, secs, syms = parse_exe(data_or_obj)
    names = [n for n, _ in secs]
    for name, val, size, bind, typ, shndx in syms:
        if typ in (elf.STT_FILE, elf.STT_SECTION):
            continue
        sec = names[shndx - 1] if 0 < shndx <= len(names) else ""
        base = "T" if sec == ".text" else "R" if sec.startswith((".rodata", ".eh")) else "D" if sec in (".data", ".got") else "B" if sec == ".bss" else "A"
        out.append((val, base if bind != 0 else base.lower(), name))
    return [f"{v:016x} {l} {n}" for v, l, n in sorted(out)]


def _nm_letter(s, obj):
    if s.shndx == elf.SHN_UNDEF:
        return "w" if s.bind == elf.STB_WEAK else "U"
    if s.shndx == elf.SHN_COMMON:
        return "C"
    if s.shndx == elf.SHN_ABS:
        c = "A"
    else:
        sec = s.section
        if sec is None:
            c = "?"
        elif sec.flags & elf.SHF_EXECINSTR:
            c = "T"
        elif sec.type == elf.SHT_NOBITS:
            c = "B"
        elif sec.flags & elf.SHF_WRITE:
            c = "D"
        else:
            c = "R"
    if s.bind == elf.STB_WEAK:
        return "W" if c == "T" else "V"
    return c if s.bind != elf.STB_LOCAL else c.lower()


def link_map(res, out_name="a.out"):
    L = [f"Ferrule link map for {out_name}", f"Entry point: {res.entry:#x}", ""]
    if res.pulled:
        L.append("Archive members pulled in:")
        for ar, mem, why in res.pulled:
            L.append(f"  {ar}({mem})  <- {why}")
        L.append("")
    L.append("Segments:")
    for s in res.segments:
        L.append(f"  {s['name']}  vaddr={s['vaddr']:#010x} offset={s['offset']:#07x} filesz={s['filesz']:#x} memsz={s['memsz']:#x}")
    L += ["", "Memory map:"]
    for s in res.sections:
        L.append(f"{s['name']:<12} {s['addr']:#010x} {s['size']:#8x}  align={s['align']}{'  (NOBITS)' if s['nobits'] else ''}")
        for (obj, sec, addr, size) in s["inputs"]:
            L.append(f"    {addr:#010x} {size:#8x}  {obj}({sec})")
    if res.discarded:
        L += ["", "Discarded input sections:"]
        for obj, sec, size, why in res.discarded:
            L.append(f"  {obj}({sec})  {size} B  — {why}")
    L += ["", "Global symbols:"]
    for name, addr in sorted(res.symbols.items(), key=lambda kv: (kv[1], kv[0])):
        if name.startswith("\0"):
            continue
        L.append(f"  {addr:#010x}  {name}")
    return "\n".join(L) + "\n"
