"""Static linker: ELF64 x86-64 relocatable objects + archives -> ET_EXEC."""
import os
import struct
from . import elf
from .elf import (Section, Symbol, ElfObject, STB_LOCAL, STB_GLOBAL, STB_WEAK, SHN_UNDEF, SHN_ABS,
                  SHN_COMMON, STT_SECTION, STT_FILE, SHF_ALLOC, SHF_WRITE, SHF_EXECINSTR, SHF_TLS,
                  SHT_NOBITS, SHT_PROGBITS)
from .ar import Archive, is_archive
from .errors import LinkError, FerruleError

PAGE = 0x1000
PT_LOAD, PT_GNU_STACK = 1, 0x6474E551
PF_X, PF_W, PF_R = 1, 2, 4
CANON = (".text", ".rodata", ".data", ".bss")
DROPPED_NAMES = (".comment", ".note.GNU-stack", ".note.gnu.property", ".note.gnu.build-id",
                 ".gnu_debuglink")
ROOT_PREFIXES = (".init", ".fini", ".preinit_array", ".init_array", ".fini_array", ".note")
SUPPORTED = {elf.R_X86_64_NONE, elf.R_X86_64_64, elf.R_X86_64_PC32, elf.R_X86_64_PLT32,
             elf.R_X86_64_32, elf.R_X86_64_32S, elf.R_X86_64_16, elf.R_X86_64_PC16,
             elf.R_X86_64_8, elf.R_X86_64_PC8, elf.R_X86_64_PC64, elf.R_X86_64_GOTPCREL,
             elf.R_X86_64_GOTPCRELX, elf.R_X86_64_REX_GOTPCRELX}
GOT_RELOCS = {elf.R_X86_64_GOTPCREL, elf.R_X86_64_GOTPCRELX, elf.R_X86_64_REX_GOTPCRELX}


def align_up(v, a):
    return (v + a - 1) // a * a if a > 1 else v


class Options:
    def __init__(self, entry="_start", gc_sections=False, base=0x400000, undefined=(), lib_dirs=(),
                 allow_undefined=False, whole_archive=False):
        self.entry, self.gc_sections, self.base = entry, gc_sections, base
        self.undefined, self.lib_dirs = list(undefined), list(lib_dirs)
        self.allow_undefined = allow_undefined
        self.whole_archive = whole_archive


class Def:
    """Resolved definition of a global symbol."""
    def __init__(self, obj, sym, kind):
        self.obj, self.sym, self.kind = obj, sym, kind     # kind: 'strong' | 'weak' | 'common' | 'abs'
        self.addr = None

    @property
    def size(self):
        return self.sym.size


class LinkResult:
    def __init__(self):
        self.data = b""
        self.entry = 0
        self.segments = []      # dicts: name, vaddr, offset, filesz, memsz, flags
        self.sections = []      # dicts: name, addr, size, flags, align, nobits, inputs
        self.symbols = {}       # global name -> address
        self.pulled = []        # (archive, member, because-of symbol)
        self.discarded = []     # (obj, section name, size, reason)
        self.got = {}           # symbol name -> slot address
        self.objects = []

    def write(self, path):
        with open(path, "wb") as f:
            f.write(self.data)
        os.chmod(path, 0o755)


class Linker:
    def __init__(self, options=None):
        self.opt = options or Options()
        self.objects = []           # loaded ElfObject in link order
        self.table = {}             # name -> Def
        self.undef = {}             # name -> (obj, strong?) outstanding references
        self.pulled = []
        self.result = LinkResult()
        self.dropped = {}           # id(section) -> reason (comdat dup etc.)
        self.comdat_seen = {}
        self.errors = []
        self._got_locals = {}

    # ------------------------------------------------------------------ input
    def add_object(self, obj):
        self.objects.append(obj)
        self._discard_comdats(obj)
        for s in obj.symbols:
            if s.bind == STB_LOCAL or not s.name:
                continue
            if s.type == STT_FILE:
                continue
            if s.shndx == SHN_UNDEF:
                if s.name not in self.table:
                    strong = s.bind == STB_GLOBAL
                    prev = self.undef.get(s.name)
                    if prev is None or (strong and not prev[1]):
                        self.undef[s.name] = (obj, strong)
                continue
            if s.section is not None and id(s.section) in self.dropped:
                continue
            self._define(obj, s)

    def _discard_comdats(self, obj):
        for sec, sig in obj.groups.items():
            if sig in self.comdat_seen:
                self.dropped[id(sec)] = f"duplicate COMDAT group '{sig}'"
            else:
                self.comdat_seen[sig] = obj.name

    def _define(self, obj, s):
        if s.shndx == SHN_COMMON:
            kind = "common"
        elif s.shndx == SHN_ABS:
            kind = "abs"
        else:
            kind = "weak" if s.bind == STB_WEAK else "strong"
        new = Def(obj, s, kind)
        old = self.table.get(s.name)
        self.undef.pop(s.name, None)
        if old is None:
            self.table[s.name] = new
            return
        if old.kind in ("strong", "abs") and kind in ("strong", "abs"):
            self.errors.append(f"multiple definition of `{s.name}'; {obj.name}: first defined in {old.obj.name}")
            return
        if kind in ("strong", "abs"):
            self.table[s.name] = new                        # strong beats weak/common
        elif kind == "weak":
            if old.kind == "common":
                self.table[s.name] = new                    # a definition beats a common
        elif kind == "common" and old.kind == "common":
            if s.size > old.sym.size:
                new.sym = Symbol(s.name, max(s.value, old.sym.value), s.size, s.bind, s.type, 0, SHN_COMMON)
                self.table[s.name] = new
            elif s.value > old.sym.value:
                old.sym = Symbol(s.name, s.value, old.sym.size, old.sym.bind, old.sym.type, 0, SHN_COMMON)

    def add_archive(self, ar, whole=False):
        if whole:
            for i, m in enumerate(ar.members):
                self._pull(ar, i, "--whole-archive")
            return
        progress = True
        done = set()
        while progress:
            progress = False
            for name in sorted(self.undef):
                info = self.undef.get(name)
                if info is None or not info[1]:
                    continue                        # weak references never pull members
                idx = ar.index.get(name)
                if idx is None or idx in done:
                    continue
                done.add(idx)
                self._pull(ar, idx, name)
                progress = True
                break

    def _pull(self, ar, idx, because):
        m = ar.members[idx]
        try:
            obj = ElfObject.parse(m.data, f"{ar.name}({m.name})")
        except FerruleError as ex:
            raise LinkError(f"{ar.name}: member {m.name}: {ex}")
        self.pulled.append((ar.name, m.name, because))
        self.add_object(obj)

    def add_file(self, path, whole=False):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as ex:
            raise LinkError(f"cannot read {path}: {ex.strerror}")
        if is_archive(data):
            self.add_archive(Archive.parse(data, path), whole)
        else:
            self.add_object(ElfObject.parse(data, path))

    def find_lib(self, name):
        for d in self.opt.lib_dirs:
            p = os.path.join(d, f"lib{name}.a")
            if os.path.exists(p):
                return p
        raise LinkError(f"cannot find -l{name} (searched: {', '.join(self.opt.lib_dirs) or 'no -L directories'})")

    # ------------------------------------------------------------------ layout
    @staticmethod
    def _classify(sec):
        if sec.flags & SHF_TLS:
            raise LinkError(f"{sec.name}: thread-local storage is not supported")
        if sec.flags & SHF_EXECINSTR:
            return 0
        if sec.flags & SHF_WRITE:
            return 3 if sec.type == SHT_NOBITS else 2
        return 1

    @staticmethod
    def _outname(sec, cls):
        for p in CANON:
            if sec.name == p or sec.name.startswith(p + "."):
                if p == ".bss" and cls != 3:
                    continue
                if p in (".data",) and cls != 2:
                    continue
                if p == ".text" and cls != 0:
                    continue
                if p == ".rodata" and cls != 1:
                    continue
                return p
        if cls == 3:
            return ".bss"
        return sec.name

    def _live_sections(self):
        keep = []
        for obj in self.objects:
            for sec in obj.sections:
                if not (sec.flags & SHF_ALLOC):
                    continue
                if sec.name in DROPPED_NAMES:
                    continue
                if id(sec) in self.dropped:
                    self.result.discarded.append((obj.name, sec.name, sec.size, self.dropped[id(sec)]))
                    continue
                keep.append((obj, sec))
        return keep

    def _gc(self, keep):
        """Mark sections reachable from the entry point and special roots."""
        live = set()
        work = []
        by_id = {id(s): (o, s) for o, s in keep}

        def mark(sec):
            if sec is not None and id(sec) in by_id and id(sec) not in live:
                live.add(id(sec))
                work.append(sec)

        def mark_name(name):
            d = self.table.get(name)
            if d is not None and d.sym.section is not None:
                mark(d.sym.section)

        mark_name(self.opt.entry)
        for u in self.opt.undefined:
            mark_name(u)
        for o, s in keep:
            if s.name.startswith(ROOT_PREFIXES):
                mark(s)
        while work:
            sec = work.pop()
            obj = by_id[id(sec)][0]
            for r in sec.relocs:
                sym = r.sym
                if sym is None:
                    continue
                if sym.bind == STB_LOCAL or sym.shndx == SHN_UNDEF and sym.name not in self.table:
                    if sym.section is not None:
                        mark(sym.section)
                else:
                    d = self.table.get(sym.name)
                    if d is not None and d.sym.section is not None:
                        mark(d.sym.section)
        out = []
        for o, s in keep:
            if id(s) in live:
                out.append((o, s))
            else:
                if s.size:
                    self.result.discarded.append((o.name, s.name, s.size, "unreferenced (--gc-sections)"))
                self.dropped[id(s)] = "gc"
        return out

    def link(self):
        res = self.result
        if self.opt.base % PAGE or self.opt.base < 0:
            raise LinkError(f"base address {self.opt.base:#x} must be a non-negative multiple of {PAGE:#x}")
        if self.errors:
            raise LinkError("\n".join(self.errors))
        for u in self.opt.undefined:
            if u not in self.table:
                self.undef.setdefault(u, (None, True))
        entry_name = self.opt.entry
        if entry_name not in self.table and not entry_name.isdigit() and not entry_name.startswith("0x"):
            raise LinkError(f"entry symbol `{entry_name}' is not defined")
        keep = self._live_sections()
        if self.opt.gc_sections:
            keep = [(o, s) for o, s in keep if s.name != ".eh_frame"] if True else keep
            for o, s in list(self._live_sections()):
                if s.name == ".eh_frame":
                    res.discarded.append((o.name, s.name, s.size, "dropped under --gc-sections"))
            keep = self._gc(keep)
        # ---- group into output sections
        outs = {}
        order = []
        for obj, sec in keep:
            cls = self._classify(sec)
            name = self._outname(sec, cls)
            key = (cls, name)
            if key not in outs:
                outs[key] = {"name": name, "cls": cls, "inputs": [], "align": 1, "flags": 0,
                             "size": 0, "data": None}
                order.append(key)
            o = outs[key]
            o["inputs"].append((obj, sec))
            o["align"] = max(o["align"], sec.align)
            o["flags"] |= sec.flags & (SHF_WRITE | SHF_EXECINSTR | SHF_ALLOC)
        # ---- GOT
        got_keys = []
        got_index = {}
        for obj, sec in keep:
            for r in sec.relocs:
                if r.type in GOT_RELOCS:
                    k = self._got_key(obj, r.sym)
                    if k not in got_index:
                        got_index[k] = len(got_keys)
                        got_keys.append(k)
        if got_keys:
            outs[(2, ".got")] = {"name": ".got", "cls": 2, "inputs": [], "align": 8,
                                 "flags": SHF_ALLOC | SHF_WRITE, "size": 8 * len(got_keys), "data": None}
            order.append((2, ".got"))
        # ---- commons -> .bss tail
        commons = [d for d in self.table.values() if d.kind == "common"]
        # ---- sort order inside class: canonical first
        seen_pos = {k: i for i, k in enumerate(order)}

        def sort_key(k):
            cls, name = k
            return (cls, 0 if name in CANON or name == ".got" else 1, seen_pos.get(k, len(seen_pos)))
        order.sort(key=sort_key)
        # ---- assign sizes / offsets within each output section
        placed = {}                 # id(input section) -> (outsec dict, offset)
        for k in order:
            o = outs[k]
            off = 0
            for obj, sec in o["inputs"]:
                off = align_up(off, sec.align)
                placed[id(sec)] = (o, off)
                off += sec.size
            if o["name"] == ".got":
                off = o["size"]
            o["size"] = off
        # commons live at the end of .bss
        bss_key = (3, ".bss")
        if commons:
            if bss_key not in outs:
                outs[bss_key] = {"name": ".bss", "cls": 3, "inputs": [], "align": 1,
                                 "flags": SHF_ALLOC | SHF_WRITE, "size": 0, "data": None}
                order.append(bss_key)
                order.sort(key=sort_key)
            b = outs[bss_key]
            off = b["size"]
            for d in sorted(commons, key=lambda d: d.sym.name):
                al = max(d.sym.value, 1)
                off = align_up(off, al)
                d.common_off = off
                off += d.sym.size
                b["align"] = max(b["align"], al)
            b["size"] = off
        for o in outs.values():
            if o["size"] > (1 << 31):
                raise LinkError(f"output section {o['name']} would be {o['size']} bytes (limit 2 GiB)")
        # ---- segments & addresses
        segs = []
        for cls, flags in ((0, PF_R | PF_X), (1, PF_R), (2, PF_R | PF_W)):
            members = [outs[k] for k in order if k[0] == cls or (cls == 2 and k[0] == 3)]
            if members:
                segs.append((cls, flags, members))
        hdr_size = 64 + 56 * (len(segs) + 1)     # ehdr + PT_LOADs + PT_GNU_STACK
        cursor_file = 0
        seg_infos = []
        for si, (cls, flags, members) in enumerate(segs):
            if si == 0:
                seg_off = 0
                seg_vaddr = self.opt.base
                cur = hdr_size
            else:
                seg_off = align_up(cursor_file, PAGE)
                seg_vaddr = self.opt.base + seg_off
                cur = 0
            filesz_end = None
            for o in members:
                cur = align_up(seg_vaddr + cur, o["align"]) - seg_vaddr if o["align"] > 1 else cur
                o["addr"] = seg_vaddr + cur
                o["offset"] = seg_off + cur
                o["nobits"] = o["cls"] == 3
                cur += o["size"]
                if not o["nobits"]:
                    filesz_end = cur
            filesz = filesz_end if filesz_end is not None else 0
            if si == 0:
                filesz = max(filesz, hdr_size)
            seg_infos.append({"flags": flags, "offset": seg_off, "vaddr": seg_vaddr, "filesz": filesz,
                              "memsz": cur, "members": members})
            cursor_file = seg_off + filesz
        # ---- addresses of symbols
        for d in self.table.values():
            if d.kind == "common":
                d.addr = outs[bss_key]["addr"] + d.common_off
        self._placed = placed
        self._outs = outs
        for o in outs.values():
            o["buf"] = bytearray(0 if o["cls"] == 3 else o["size"])
        # copy raw section data
        for k in order:
            o = outs[k]
            if o["cls"] == 3:
                continue
            for obj, sec in o["inputs"]:
                off = placed[id(sec)][1]
                o["buf"][off:off + len(sec.data)] = sec.data
        # ---- provided symbols
        self._provide(outs, order, seg_infos)
        # ---- undefined check
        missing = []
        for obj in self.objects:
            for s in obj.symbols:
                if s.shndx == SHN_UNDEF and s.name and s.bind != STB_LOCAL and s.name not in self.table:
                    if s.bind == STB_WEAK:
                        continue
                    missing.append((s.name, obj.name))
        for name, info in self.undef.items():
            if name not in self.table and info[0] is None:
                missing.append((name, "<command line -u>"))
        if missing and not self.opt.allow_undefined:
            seen, lines = set(), []
            for name, where in missing:
                if (name, where) not in seen:
                    seen.add((name, where))
                    lines.append(f"{where}: undefined reference to `{name}'")
            raise LinkError("\n".join(lines))
        # ---- GOT contents (filled after addresses known)
        got_out = outs.get((2, ".got"))
        # ---- apply relocations
        for obj, sec in keep:
            self._apply(obj, sec, placed, got_keys, got_index, got_out)
        if got_out is not None:
            for i, k in enumerate(got_keys):
                kind, ref = k
                addr = self._key_addr(k)
                got_out["buf"][8 * i:8 * i + 8] = struct.pack("<Q", addr & 0xFFFFFFFFFFFFFFFF)
                sym = self._got_locals.get(k)
                label = k[1] if k[0] == "g" else (f"<local {sym.name or sym.section.name}>" if sym else "<null>")
                res.got[label] = got_out["addr"] + 8 * i
        # ---- entry
        if entry_name in self.table:
            entry = self.sym_addr(None, self.table[entry_name])
        else:
            entry = int(entry_name, 0)
        res.entry = entry
        res.data = self._write_exe(order, outs, seg_infos, entry)
        # ---- bookkeeping for reports
        for si in seg_infos:
            res.segments.append({"name": {PF_R | PF_X: "R-X", PF_R: "R--", PF_R | PF_W: "RW-"}[si["flags"]],
                                 "vaddr": si["vaddr"], "offset": si["offset"], "filesz": si["filesz"],
                                 "memsz": si["memsz"], "flags": si["flags"]})
        for k in order:
            o = outs[k]
            res.sections.append({"name": o["name"], "addr": o["addr"], "size": o["size"],
                                 "align": o["align"], "cls": o["cls"], "nobits": o["nobits"],
                                 "inputs": [(obj.name, sec.name, placed[id(sec)][1] + o["addr"], sec.size)
                                            for obj, sec in o["inputs"]]})
        for name, d in self.table.items():
            if d.sym.section is not None and id(d.sym.section) not in self._placed:
                continue                    # defined in a section that was garbage-collected
            res.symbols[name] = self.sym_addr(None, d)
        res.pulled = self.pulled
        res.objects = [o.name for o in self.objects]
        return res

    # ------------------------------------------------------------------ symbols
    def _provide(self, outs, order, seg_infos):
        ends = {"text": 0, "data_end": 0, "bss_start": 0, "end": 0}
        text = [outs[k] for k in order if k[0] == 0]
        if text:
            ends["text"] = max(o["addr"] + o["size"] for o in text)
        dat = [outs[k] for k in order if k[0] in (2,)]
        bss = [outs[k] for k in order if k[0] == 3]
        if dat:
            ends["data_end"] = max(o["addr"] + o["size"] for o in dat)
        if bss:
            ends["bss_start"] = min(o["addr"] for o in bss)
            ends["end"] = max(o["addr"] + o["size"] for o in bss)
        else:
            ends["bss_start"] = ends["end"] = ends["data_end"]
        if not dat and not bss:
            ends["data_end"] = ends["bss_start"] = ends["end"] = max(
                [o["addr"] + o["size"] for o in outs.values()] or [self.opt.base])
        prov = {"etext": ends["text"], "_etext": ends["text"], "edata": ends["data_end"],
                "_edata": ends["data_end"], "__bss_start": ends["bss_start"],
                "end": ends["end"], "_end": ends["end"], "__ehdr_start": self.opt.base}
        got = outs.get((2, ".got"))
        prov["_GLOBAL_OFFSET_TABLE_"] = got["addr"] if got else ends["data_end"]
        for name, addr in prov.items():
            want = name in self.undef or any(
                s.shndx == SHN_UNDEF and s.name == name for o in self.objects for s in o.symbols)
            if want and name not in self.table:
                sym = Symbol(name, addr, 0, STB_GLOBAL, 0, 0, SHN_ABS)
                d = Def(None, sym, "abs")
                self.table[name] = d
                self.undef.pop(name, None)

    def _key_addr(self, key):
        kind, ref = key
        if kind == "g":
            return self.sym_addr(None, self.table[ref]) if ref in self.table else 0
        sym = self._got_locals[key]
        return 0 if sym is None else self._local_addr(sym)

    def _local_addr(self, sym):
        if sym.shndx == SHN_ABS:
            return sym.value
        if sym.section is None:
            return 0
        pl = self._placed.get(id(sym.section))
        if pl is None:
            raise LinkError(f"symbol `{sym.name or sym.section.name}' refers to discarded section {sym.section.name}")
        return pl[0]["addr"] + pl[1] + sym.value

    def sym_addr(self, obj, d):
        if d.addr is not None:
            return d.addr
        s = d.sym
        if s.shndx == SHN_ABS:
            d.addr = s.value
        else:
            d.addr = self._local_addr(s)
        return d.addr

    def _got_key(self, obj, sym):
        """One GOT slot per distinct symbol: globals by name, locals by identity."""
        if sym is None or sym.bind == STB_LOCAL:
            key = ("l", id(sym))
            self._got_locals[key] = sym
            return key
        return ("g", sym.name)

    def _resolve(self, obj, sym):
        """Address of a symbol as referenced from `obj` (S in the relocation formulas)."""
        if sym is None:
            return 0
        if sym.bind == STB_LOCAL or (sym.shndx != SHN_UNDEF and sym.name == "" ):
            return self._local_addr(sym)
        d = self.table.get(sym.name)
        if d is None:
            if sym.bind == STB_WEAK or self.opt.allow_undefined:
                return 0
            raise LinkError(f"{obj.name}: undefined reference to `{sym.name}'")
        return self.sym_addr(obj, d)

    # ------------------------------------------------------------------ relocation
    def _apply(self, obj, sec, placed, got_keys, got_index, got_out):
        o, base = placed[id(sec)]
        buf = o["buf"]
        for r in sec.relocs:
            if r.type not in SUPPORTED:
                nm = elf.RELOC_NAMES.get(r.type, f"type {r.type}")
                raise LinkError(f"{obj.name}:({sec.name}+{r.offset:#x}): unsupported relocation {nm}")
            if r.type == elf.R_X86_64_NONE:
                continue
            if r.offset + self._rsize(r.type) > sec.size:
                raise LinkError(f"{obj.name}:({sec.name}+{r.offset:#x}): relocation lies outside its section")
            try:
                S = self._resolve(obj, r.sym)
            except LinkError as ex:
                raise LinkError(f"{obj.name}:({sec.name}+{r.offset:#x}): {ex}" if "refers to discarded" in str(ex) else str(ex))
            A = r.addend
            P = o["addr"] + base + r.offset
            pos = base + r.offset
            t = r.type
            what = f"against `{r.sym.name}'" if r.sym is not None and r.sym.name else \
                (f"against section {r.sym.section.name}" if r.sym is not None and r.sym.section else "")
            where = f"{obj.name}:({sec.name}+{r.offset:#x})"
            if t in GOT_RELOCS:
                k = self._got_key(obj, r.sym)
                G = got_out["addr"] + 8 * got_index[k]
                self._put(buf, pos, G + A - P, 4, True, where, elf.RELOC_NAMES[t], what)
            elif t in (elf.R_X86_64_PC32, elf.R_X86_64_PLT32):
                self._put(buf, pos, S + A - P, 4, True, where, elf.RELOC_NAMES[t], what)
            elif t == elf.R_X86_64_64:
                buf[pos:pos + 8] = struct.pack("<Q", (S + A) & 0xFFFFFFFFFFFFFFFF)
            elif t == elf.R_X86_64_PC64:
                buf[pos:pos + 8] = struct.pack("<Q", (S + A - P) & 0xFFFFFFFFFFFFFFFF)
            elif t == elf.R_X86_64_32:
                self._put(buf, pos, S + A, 4, False, where, "R_X86_64_32", what)
            elif t == elf.R_X86_64_32S:
                self._put(buf, pos, S + A, 4, True, where, "R_X86_64_32S", what)
            elif t == elf.R_X86_64_16:
                self._put(buf, pos, S + A, 2, False, where, "R_X86_64_16", what)
            elif t == elf.R_X86_64_PC16:
                self._put(buf, pos, S + A - P, 2, True, where, "R_X86_64_PC16", what)
            elif t == elf.R_X86_64_8:
                self._put(buf, pos, S + A, 1, False, where, "R_X86_64_8", what)
            elif t == elf.R_X86_64_PC8:
                self._put(buf, pos, S + A - P, 1, True, where, "R_X86_64_PC8", what)

    @staticmethod
    def _rsize(t):
        return {elf.R_X86_64_64: 8, elf.R_X86_64_PC64: 8, elf.R_X86_64_16: 2, elf.R_X86_64_PC16: 2,
                elf.R_X86_64_8: 1, elf.R_X86_64_PC8: 1}.get(t, 4)

    @staticmethod
    def _put(buf, pos, val, size, signed, where, rname, what):
        bits = size * 8
        lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        if not lo <= val <= hi:
            raise LinkError(f"{where}: relocation truncated to fit: {rname} {what} (value {val:#x})")
        buf[pos:pos + size] = (val & ((1 << bits) - 1)).to_bytes(size, "little")

    # ------------------------------------------------------------------ output
    def _write_exe(self, order, outs, seg_infos, entry):
        phnum = len(seg_infos) + 1
        img = bytearray(64 + 56 * phnum)
        file_end = max([s["offset"] + s["filesz"] for s in seg_infos] + [len(img)])
        body = bytearray(file_end)
        for k in order:
            o = outs[k]
            if o["cls"] != 3 and o["size"]:
                body[o["offset"]:o["offset"] + o["size"]] = o["buf"]
        # ---- symbol table
        shstr = bytearray(b"\0")
        def shname(n):
            off = len(shstr)
            shstr.extend(n.encode() + b"\0")
            return off
        strtab = bytearray(b"\0")
        symdata = bytearray(elf.SYM.pack(0, 0, 0, 0, 0, 0))
        sec_index = {}
        for i, k in enumerate(order, 1):
            sec_index[id(outs[k])] = i
        local_syms, global_syms = [], []
        for obj in self.objects:
            for s in obj.symbols:
                if s.bind != STB_LOCAL or not s.name or s.type == STT_FILE or s.type == STT_SECTION:
                    continue
                if s.section is None:
                    continue
                pl = self._placed.get(id(s.section))
                if pl is None:
                    continue
                local_syms.append((s.name, self._local_addr(s), s.size, s.type, pl[0]))
        for name, d in sorted(self.table.items()):
            if name.startswith("\0"):
                continue
            s = d.sym
            if d.kind == "common":
                ob = outs[(3, ".bss")]
                global_syms.append((name, d.addr, s.size, elf.STT_OBJECT, ob, s.bind))
            elif d.kind == "abs":
                global_syms.append((name, d.addr if d.addr is not None else s.value, s.size, s.type, None, s.bind))
            else:
                pl = self._placed.get(id(s.section)) if s.section is not None else None
                if pl is None:
                    continue
                global_syms.append((name, self.sym_addr(None, d), s.size, s.type, pl[0], s.bind))
        def add(name, addr, size, typ, osec, bind):
            nm = len(strtab)
            strtab.extend(name.encode() + b"\0")
            shndx = sec_index[id(osec)] if osec is not None else SHN_ABS
            symdata.extend(elf.SYM.pack(nm, (bind << 4) | typ, 0, shndx, addr, size))
        for name, addr, size, typ, osec in local_syms:
            add(name, addr, size, typ, osec, STB_LOCAL)
        first_global = 1 + len(local_syms)
        for name, addr, size, typ, osec, bind in global_syms:
            add(name, addr, size, typ, osec, bind)
        pos = len(body)
        def place(data, align):
            nonlocal pos
            pos = align_up(pos, align)
            off = pos
            body.extend(b"\0" * (off - len(body)))
            body.extend(data)
            pos = len(body)
            return off
        symoff = place(bytes(symdata), 8)
        stroff = place(bytes(strtab), 1)
        headers = [(0,) * 10]
        for k in order:
            o = outs[k]
            fl = o["flags"] | SHF_ALLOC
            typ = SHT_NOBITS if o["cls"] == 3 else SHT_PROGBITS
            headers.append((shname(o["name"]), typ, fl, o["addr"], o["offset"], o["size"], 0, 0, o["align"], 0))
        nsec = len(headers) + 3
        symtab_i = len(headers)
        headers.append((shname(".symtab"), elf.SHT_SYMTAB, 0, 0, symoff, len(symdata), symtab_i + 1,
                        first_global, 8, elf.SYM.size))
        headers.append((shname(".strtab"), elf.SHT_STRTAB, 0, 0, stroff, len(strtab), 0, 0, 1, 0))
        nm = shname(".shstrtab")
        shoff_str = place(bytes(shstr), 1)
        headers.append((nm, elf.SHT_STRTAB, 0, 0, shoff_str, len(shstr), 0, 0, 1, 0))
        shoff = place(b"", 8)
        for h in headers:
            body.extend(elf.SHDR.pack(*h))
        ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
        img[0:64] = elf.EHDR.pack(ident, elf.ET_EXEC, elf.EM_X86_64, 1, entry, 64, shoff, 0, 64, 56,
                                  phnum, elf.SHDR.size, len(headers), len(headers) - 1)
        p = 64
        for s in seg_infos:
            img[p:p + 56] = elf.PHDR.pack(PT_LOAD, s["flags"], s["offset"], s["vaddr"], s["vaddr"],
                                          s["filesz"], s["memsz"], PAGE)
            p += 56
        img[p:p + 56] = elf.PHDR.pack(PT_GNU_STACK, PF_R | PF_W, 0, 0, 0, 0, 0, 16)
        body[0:len(img)] = img
        return bytes(body)


def link(inputs, options=None):
    """inputs: list of paths (objects/archives) or ('lib', name) or ElfObject / Archive instances."""
    lk = Linker(options)
    for item in inputs:
        whole = lk.opt.whole_archive
        if isinstance(item, ElfObject):
            lk.add_object(item)
        elif isinstance(item, Archive):
            lk.add_archive(item, whole)
        elif isinstance(item, tuple) and item[0] == "lib":
            lk.add_file(lk.find_lib(item[1]), whole)
        else:
            lk.add_file(item, whole)
    return lk.link()
