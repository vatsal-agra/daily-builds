"""GNU/SysV `ar` archive reader and writer (symbol index + long-name table)."""
import struct
from .errors import FerruleError
from .elf import ElfObject, STB_LOCAL, SHN_UNDEF, SHN_COMMON

MAGIC = b"!<arch>\n"


class Member:
    def __init__(self, name, data):
        self.name, self.data = name, data

    def __repr__(self):
        return f"<Member {self.name} {len(self.data)}B>"


class Archive:
    def __init__(self, name="<archive>"):
        self.name = name
        self.members = []
        self._index = None     # symbol name -> member position; built on first use

    @property
    def index(self):
        """Symbol -> member index. Rebuilt on demand so hand-assembled archives work too."""
        if self._index is None or any(i >= len(self.members) for i in self._index.values()):
            self.rebuild_index()
        return self._index

    @index.setter
    def index(self, v):
        self._index = v

    # ------------------------------------------------------------------ reading
    @classmethod
    def parse(cls, data, name="<archive>"):
        if not data.startswith(MAGIC):
            raise FerruleError(f"{name}: not an archive (bad magic)")
        ar = cls(name)
        pos, longnames, sym_table = len(MAGIC), b"", None
        offset_to_member = {}
        while pos < len(data):
            if pos + 60 > len(data):
                raise FerruleError(f"{name}: truncated member header at offset {pos}")
            hdr = data[pos:pos + 60]
            if hdr[58:60] != b"`\n":
                raise FerruleError(f"{name}: bad member header terminator at offset {pos}")
            raw_name = hdr[0:16].decode("latin-1").rstrip()
            try:
                size = int(hdr[48:58].decode("latin-1").strip())
            except ValueError:
                raise FerruleError(f"{name}: bad member size at offset {pos}")
            body_start = pos + 60
            if body_start + size > len(data):
                raise FerruleError(f"{name}: member at offset {pos} extends past end of file")
            body = data[body_start:body_start + size]
            hdr_pos = pos
            pos = body_start + size + (size & 1)
            if raw_name == "/":
                sym_table = body
                continue
            if raw_name == "//":
                longnames = body
                continue
            if raw_name in ("/SYM64/", "/<SYM64>/"):
                raise FerruleError(f"{name}: 64-bit archive symbol tables are not supported")
            if raw_name.startswith("/") and raw_name[1:].isdigit():
                off = int(raw_name[1:])
                end = longnames.find(b"/\n", off)
                if off >= len(longnames) or end < 0:
                    raise FerruleError(f"{name}: bad long-name reference {raw_name}")
                mname = longnames[off:end].decode("latin-1")
            else:
                mname = raw_name[:-1] if raw_name.endswith("/") else raw_name
            offset_to_member[hdr_pos] = len(ar.members)
            ar.members.append(Member(mname, body))
        # symbol index: trust the archive's own table when present and sane
        if sym_table is not None and len(sym_table) >= 4:
            n = struct.unpack_from(">I", sym_table, 0)[0]
            if 4 + 4 * n <= len(sym_table):
                names = sym_table[4 + 4 * n:].split(b"\0")
                ok = True
                tmp = {}
                for i in range(n):
                    off = struct.unpack_from(">I", sym_table, 4 + 4 * i)[0]
                    if off not in offset_to_member or i >= len(names):
                        ok = False
                        break
                    tmp.setdefault(names[i].decode("latin-1"), offset_to_member[off])
                if ok:
                    ar._index = tmp
                    return ar
        ar.rebuild_index()
        return ar

    def rebuild_index(self):
        idx = {}
        for i, m in enumerate(self.members):
            for s in defined_globals(m):
                idx.setdefault(s, i)
        self._index = idx

    # ------------------------------------------------------------------ writing
    def to_bytes(self):
        long_tab = bytearray()
        names = []
        for m in self.members:
            if len(m.name) < 16:
                names.append((m.name + "/").ljust(16))
            else:
                names.append(("/%d" % len(long_tab)).ljust(16))
                long_tab += m.name.encode() + b"/\n"
        self.rebuild_index()
        sym_entries = []   # (name, member_index)
        for i, m in enumerate(self.members):
            for s in sorted(defined_globals(m)):
                sym_entries.append((s, i))

        def header(name, size):
            return (name.ljust(16).encode() + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6)
                    + b"644".ljust(8) + str(size).ljust(10).encode() + b"`\n")

        def pad(b):
            return b + (b"\n" if len(b) & 1 else b"")

        strs = b"".join(n.encode() + b"\0" for n, _ in sym_entries)
        sym_body_len = 4 + 4 * len(sym_entries) + len(strs)
        lt = bytes(long_tab)
        prefix = len(MAGIC)
        if sym_entries:
            prefix += 60 + len(pad(b"x" * sym_body_len))
        if lt:
            prefix += 60 + len(pad(lt))
        offsets, pos = [], prefix
        for m in self.members:
            offsets.append(pos)
            pos += 60 + len(pad(m.data))
        out = bytearray(MAGIC)
        if sym_entries:
            body = struct.pack(">I", len(sym_entries))
            body += b"".join(struct.pack(">I", offsets[i]) for _, i in sym_entries) + strs
            out += header("/", len(body)) + pad(body)
        if lt:
            out += header("//", len(lt)) + pad(lt)
        for m, nm in zip(self.members, names):
            out += header(nm.rstrip(), len(m.data)) + pad(m.data)
        return bytes(out)


def defined_globals(member):
    """Names a member would satisfy (global/weak definitions incl. commons)."""
    try:
        obj = ElfObject.parse(member.data, member.name)
    except FerruleError:
        return []
    return [s.name for s in obj.symbols
            if s.bind != STB_LOCAL and s.shndx != SHN_UNDEF and s.name and s.type != 4]


def read_archive(path):
    with open(path, "rb") as f:
        return Archive.parse(f.read(), path)


def is_archive(data):
    return data.startswith(MAGIC)
