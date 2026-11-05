import os, struct, subprocess, unittest
from helpers import *
from ferrule import elf
from ferrule.elf import ElfObject, Section, Symbol, Reloc
from ferrule.ar import Archive, Member, read_archive
from ferrule.errors import FerruleError


class ElfObjectTests(TmpCase):
    def test_writer_output_is_parsed_back_identically(self):
        o = asm_obj(".text\n.global f\nf: call g\nret\n.data\nd: .quad f\n.comm cc, 8, 8\n")
        r = roundtrip(o)
        self.assertEqual([(s.name, s.data, s.flags) for s in o.sections], [(s.name, s.data, s.flags) for s in r.sections])
        self.assertEqual(sorted(s.name for s in o.symbols if s.name), sorted(s.name for s in r.symbols if s.name))
        rel = {(x.offset, x.type, x.addend, x.sym.name) for sec in r.sections for x in sec.relocs}
        orig = {(x.offset, x.type, x.addend, x.sym.name) for sec in o.sections for x in sec.relocs}
        self.assertEqual(rel, orig)

    @need_readelf
    def test_readelf_accepts_written_object_without_warnings(self):
        path = self.p("a.o")
        wfile(path, asm_obj(".text\n.global f\nf: call g\nlea rax,[rip+d]\n.data\nd: .long 1\n").to_bytes())
        r = subprocess.run(["readelf", "-a", path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Warning", r.stderr + r.stdout)
        self.assertIn("R_X86_64_PLT32", r.stdout)

    @need_gcc
    def test_real_gcc_object_roundtrip(self):
        gcc_compile(os.path.join(HERE, "c", "algo.c"), self.p("algo.o"))
        o = ElfObject.parse(rfile(self.p("algo.o")), "algo.o")
        names = {s.name for s in o.symbols}
        self.assertTrue({"main", "classify", "other_counter"} <= names)
        r = roundtrip(o)
        self.assertEqual(len(r.sections), len(o.sections))
        self.assertEqual(sum(len(s.relocs) for s in r.sections), sum(len(s.relocs) for s in o.sections))

    def test_locals_precede_globals_and_sh_info_set(self):
        data = asm_obj(".text\nloc: nop\n.global glob\nglob: ret\n").to_bytes()
        shoff = struct.unpack_from("<Q", data, 40)[0]
        n = struct.unpack_from("<H", data, 60)[0]
        for i in range(n):
            h = elf.SHDR.unpack_from(data, shoff + 64 * i)
            if h[1] == elf.SHT_SYMTAB:
                syms = [elf.SYM.unpack_from(data, h[4] + 24 * k) for k in range(h[5] // 24)]
                first_global = h[7]
                self.assertTrue(all((s[1] >> 4) == 0 for s in syms[:first_global]))
                self.assertTrue(all((s[1] >> 4) != 0 for s in syms[first_global:]))
                return
        self.fail("no symtab")

    def test_malformed_inputs_raise_ferrule_error(self):
        good = asm_obj(".text\nret\n").to_bytes()
        for blob in (b"", b"junk" * 40, good[:90], b"\x7fELF\x01\x01\x01" + good[7:],
                     good[:16] + struct.pack("<H", elf.ET_EXEC) + good[18:]):
            with self.assertRaises(FerruleError):
                ElfObject.parse(blob, "x.o")


class ArchiveTests(TmpCase):
    def members(self):
        return [Member("a.o", asm_obj(".text\n.global fa\nfa: ret\n").to_bytes()),
                Member("odd_size_member_with_long_name.o", asm_obj(".text\n.global fb\nfb: nop\nret\n.data\n.byte 1\n").to_bytes()),
                Member("c.o", asm_obj(".text\n.global fc\n.weak fw\nfc: ret\nfw: ret\n").to_bytes())]

    def test_roundtrip_and_index(self):
        ar = Archive("x.a")
        ar.members = self.members()
        back = Archive.parse(ar.to_bytes(), "x.a")
        self.assertEqual([m.name for m in back.members], [m.name for m in ar.members])
        self.assertEqual([m.data for m in back.members], [m.data for m in ar.members])
        self.assertEqual(back.index, {"fa": 0, "fb": 1, "fc": 2, "fw": 2})

    def test_bad_archives_rejected(self):
        for blob in (b"!<arch>X", b"!<arch>\n" + b"x" * 30, b"not an archive"):
            with self.assertRaises(FerruleError):
                Archive.parse(blob, "bad.a")

    @unittest.skipUnless(HAVE["ar"] and HAVE["nm"], "needs ar/nm")
    def test_gnu_tools_read_our_archive(self):
        ar = Archive("x.a")
        ar.members = self.members()
        wfile(self.p("x.a"), ar.to_bytes())
        t = subprocess.run(["ar", "t", self.p("x.a")], capture_output=True, text=True)
        self.assertEqual(t.stdout.split(), ["a.o", "odd_size_member_with_long_name.o", "c.o"])
        nm = subprocess.run(["nm", "-s", self.p("x.a")], capture_output=True, text=True)
        self.assertIn("fb in odd_size_member_with_long_name.o", nm.stdout)
        self.assertIn("fc in c.o", nm.stdout)

    @unittest.skipUnless(HAVE["ar"], "needs ar")
    def test_we_read_gnu_archive(self):
        for n, m in zip(("a.o", "b.o"), self.members()[:2]):
            wfile(self.p(n), m.data)
        subprocess.run(["ar", "rcs", self.p("g.a"), self.p("a.o"), self.p("b.o")], check=True)
        ar = read_archive(self.p("g.a"))
        self.assertEqual([m.name for m in ar.members], ["a.o", "b.o"])
        self.assertEqual(ar.index["fa"], 0)
        self.assertEqual(ar.index["fb"], 1)


if __name__ == "__main__":
    unittest.main()
