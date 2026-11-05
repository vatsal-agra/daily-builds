import os, struct, subprocess, unittest
from helpers import *
from ferrule import elf
from ferrule.ar import Archive, Member
from ferrule.link import link, Options, Linker
from ferrule.errors import LinkError, FerruleError
from ferrule.elf import ElfObject

CDIR = os.path.join(HERE, "c")


def objs(*srcs):
    return [ElfObject.parse(asm_obj(s).to_bytes(), f"o{i}.o") for i, s in enumerate(srcs)]


HELLO = START + WRITE_FN + """
.text
main:
    mov edi, 1
    lea rsi, [rip+msg]
    mov edx, 13
    call sys_write
    mov eax, 7
    ret
.data
msg: .ascii "hello, ferrule"
"""


class PureAssembly(TmpCase):
    def test_hello_world_runs_in_the_kernel(self):
        res = link(objs(HELLO))
        rc, out = run_exe(res.data, self.tmp)
        self.assertEqual((rc, out), (7, b"hello, ferrul"))

    def test_data_bss_and_absolute_relocs(self):
        src = START + """
.text
main:
    mov eax, [counter]          # abs32S load from .data
    add eax, [rip+bssvar]       # bss is zero
    mov rbx, offset table       # abs32S address
    add eax, [rbx+8]            # table[1]
    lea rcx, [rip+ptrs]
    mov rcx, [rcx]              # R_X86_64_64 stored in .data
    add eax, [rcx]
    ret
.data
counter: .long 30
table:   .long 0, 0, 0, 0
         .long 5, 0, 0, 0
         .quad 0
ptrs:    .quad counter
.bss
bssvar:  .zero 4096
"""
        src = src.replace("table:   .long 0, 0, 0, 0\n         .long 5, 0, 0, 0", "table:   .quad 0\n         .quad 5")
        rc, _ = run_exe(link(objs(src)).data, self.tmp)
        self.assertEqual(rc, 30 + 0 + 5 + 30)

    def test_multiple_objects_resolve_each_other(self):
        a = START + ".text\nmain:\n  call helper\n  add eax, [shared]\n  ret\n"
        b = ".global helper, shared\n.text\nhelper:\n  mov eax, 40\n  ret\n.data\nshared: .long 2\n"
        rc, _ = run_exe(link(objs(a, b)).data, self.tmp)
        self.assertEqual(rc, 42)

    def test_jump_relaxation_and_far_jumps_execute(self):
        src = START + """
.text
main:
    xor eax, eax
    mov ecx, 3
again:
    add eax, 10
    dec ecx
    jnz again
    jmp far
    .skip 400, 0xcc
far:
    add eax, 1
    ret
"""
        rc, _ = run_exe(link(objs(src)).data, self.tmp)
        self.assertEqual(rc, 31)


class SymbolRules(TmpCase):
    def test_duplicate_strong_definition_is_an_error(self):
        with self.assertRaises(LinkError) as cm:
            link(objs(".global _start\n_start: ret", ".global _start\n_start: ret"))
        self.assertIn("multiple definition of `_start'", str(cm.exception))

    def test_undefined_reference_lists_every_site(self):
        with self.assertRaises(LinkError) as cm:
            link(objs(".global _start\n_start: call nowhere\ncall elsewhere"))
        self.assertIn("undefined reference to `nowhere'", str(cm.exception))
        self.assertIn("undefined reference to `elsewhere'", str(cm.exception))

    def test_missing_entry(self):
        with self.assertRaises(LinkError):
            link(objs(".text\nnop"))
        self.assertEqual(link(objs(".text\nnop"), Options(entry="0x401000")).entry, 0x401000)

    def test_weak_definition_overridden_by_strong(self):
        main = START + ".text\nmain:\n  call f\n  ret\n"
        weak = ".weak f\n.text\nf: mov eax, 1\nret\n"
        strong = ".global f\n.text\nf: mov eax, 2\nret\n"
        self.assertEqual(run_exe(link(objs(main, weak, strong)).data, self.tmp)[0], 2)
        self.assertEqual(run_exe(link(objs(main, strong, weak)).data, self.tmp, "p2")[0], 2)
        self.assertEqual(run_exe(link(objs(main, weak)).data, self.tmp, "p3")[0], 1)

    def test_weak_undefined_resolves_to_zero(self):
        src = START + ".weak maybe\n.text\nmain:\n  lea rax, [rip+maybe]\n  xor edi, edi\n  mov eax, offset maybe\n  ret\n"
        self.assertEqual(run_exe(link(objs(src)).data, self.tmp)[0], 0)

    def test_common_symbols_merge_to_largest_and_loaded_zeroed(self):
        main = START + """.text
main:
    mov eax, [rip+cmn]
    add eax, [rip+cmn+60]
    ret
.comm cmn, 8, 8
"""
        other = ".comm cmn, 64, 32\n.text\nnop"
        res = link(objs(main, other))
        self.assertEqual(run_exe(res.data, self.tmp)[0], 0)
        bss = next(s for s in res.sections if s["name"] == ".bss")
        self.assertGreaterEqual(bss["size"], 64)
        self.assertEqual(res.symbols["cmn"] % 32, 0)

    def test_definition_beats_common(self):
        main = START + ".text\nmain:\n  mov eax,[rip+v]\n  ret\n.comm v, 4, 4\n"
        defn = ".global v\n.data\nv: .long 9\n"
        self.assertEqual(run_exe(link(objs(main, defn)).data, self.tmp)[0], 9)

    def test_local_symbols_with_same_name_do_not_clash(self):
        a = START + ".text\nmain:\n  call fa\n  call fb\n  ret\nhelper: mov eax, 1\nret\n.global fa\nfa: jmp helper\n"
        b = ".global fb\n.text\nhelper: mov eax, 2\nret\nfb: jmp helper\n"
        self.assertEqual(run_exe(link(objs(a, b)).data, self.tmp)[0], 2)

    def test_provided_linker_symbols(self):
        src = START + """.text
main:
    lea rax, [rip+_end]
    lea rbx, [rip+_edata]
    sub rax, rbx
    mov edi, eax
    mov eax, edi
    ret
.data
d: .quad 1
.bss
b: .zero 24
"""
        res = link(objs(src))
        self.assertEqual(run_exe(res.data, self.tmp)[0], 24)
        self.assertEqual(res.symbols["_end"] - res.symbols["_edata"], 24)


class RelocationChecks(TmpCase):
    def test_pc32_and_abs32_overflow_are_reported(self):
        src = ".global _start\n_start: mov eax, offset far\n.data\n.global far\nfar: .long 1\n"
        with self.assertRaises(LinkError) as cm:
            link(objs(src), Options(base=0x100000000))
        self.assertIn("relocation truncated to fit", str(cm.exception))
        self.assertIn("far", str(cm.exception))

    def test_bad_base(self):
        with self.assertRaises(LinkError):
            link(objs(".global _start\n_start: ret"), Options(base=0x400123))

    def test_pc_relative_data_difference(self):
        src = START + """.text
main:
    mov eax, [rip+off]
    ret
.data
off: .long target - .
target: .long 0
"""
        self.assertEqual(run_exe(link(objs(src)).data, self.tmp)[0], 4)


class Archives(TmpCase):
    def archive(self, **members):
        ar = Archive("lib.a")
        ar.members = [Member(n, asm_obj(s).to_bytes()) for n, s in members.items()]
        return ar

    def test_only_needed_members_are_pulled_transitively(self):
        main = START + ".text\nmain:\n  call a\n  ret\n"
        ar = self.archive(**{"a.o": ".global a\n.text\na: call b\nret\n", "b.o": ".global b\n.text\nb: mov eax, 3\nret\n",
                             "unused.o": ".global u\n.text\nu: mov eax, 99\nret\n"})
        res = link([objs(main)[0], ar])
        pulled = [m for _, m, _ in res.pulled]
        self.assertEqual(sorted(pulled), ["a.o", "b.o"])
        self.assertEqual(run_exe(res.data, self.tmp)[0], 3)
        self.assertNotIn("u", res.symbols)

    def test_archive_before_its_user_is_not_searched(self):
        main = START + ".text\nmain:\n  call a\n  ret\n"
        ar = self.archive(**{"a.o": ".global a\n.text\na: mov eax, 1\nret\n"})
        with self.assertRaises(LinkError):
            link([ar, objs(main)[0]])                    # GNU ld semantics: order matters

    def test_weak_reference_does_not_pull_member(self):
        main = START + ".weak a\n.text\nmain:\n  xor eax, eax\n  ret\n  call a\n"
        ar = self.archive(**{"a.o": ".global a\n.text\na: ret\n"})
        self.assertEqual(link([objs(main)[0], ar]).pulled, [])

    def test_whole_archive_and_undefined_flag(self):
        main = START + ".text\nmain:\n  xor eax, eax\n  ret\n"
        ar = self.archive(**{"a.o": ".global a\n.text\na: ret\n", "b.o": ".global b\n.text\nb: ret\n"})
        self.assertEqual(len(link([objs(main)[0], ar], Options(whole_archive=True)).pulled), 2)
        self.assertEqual([m for _, m, _ in link([objs(main)[0], ar], Options(undefined=["b"])).pulled], ["b.o"])

    def test_lib_search_path(self):
        wfile(self.p("libx.a"), self.archive(**{"a.o": ".global a\n.text\na: mov eax, 5\nret\n"}).to_bytes())
        main = START + ".text\nmain:\n  jmp a\n"
        res = link([objs(main)[0], ("lib", "x")], Options(lib_dirs=[self.tmp]))
        self.assertEqual(run_exe(res.data, self.tmp)[0], 5)
        with self.assertRaises(LinkError):
            link([("lib", "nonexistent")], Options(lib_dirs=[self.tmp]))


class GcAndGot(TmpCase):
    def test_gc_sections_drops_unreachable_code(self):
        src = START + """.text
main:
    call live
    ret
live: mov eax, 4
    ret
.section .text.dead,"ax"
dead: mov eax, 99
    ret
.section .data.deaddata,"aw"
dd: .quad 1
"""
        plain = link(objs(src))
        gc = link(objs(src), Options(gc_sections=True))
        self.assertEqual(run_exe(gc.data, self.tmp)[0], 4)
        self.assertLess(len(gc.data), len(plain.data) + 1)
        reasons = {(s, why) for _, s, _, why in gc.discarded}
        self.assertIn((".text.dead", "unreferenced (--gc-sections)"), reasons)
        self.assertIn((".data.deaddata", "unreferenced (--gc-sections)"), reasons)
        self.assertNotIn("dead", gc.symbols)

    def test_gc_keeps_what_is_reached_through_data_pointers(self):
        src = START + """.text
main:
    mov rax, [rip+fp]
    jmp rax
.section .text.cb,"ax"
cb: mov eax, 12
    ret
.data
fp: .quad cb
"""
        self.assertEqual(run_exe(link(objs(src), Options(gc_sections=True)).data, self.tmp)[0], 12)

    def test_got_slots_are_synthesised_and_deduplicated(self):
        a = START + """.text
main:
    mov rax, [rip+val@GOTPCREL]
    mov rbx, [rip+val@GOTPCREL]
    mov eax, [rax]
    add eax, [rbx]
    ret
"""
        b = ".global val\n.data\nval: .long 21\n"
        res = link(objs(a, b))
        self.assertEqual(run_exe(res.data, self.tmp)[0], 42)
        self.assertEqual(list(res.got), ["val"])
        got = next(s for s in res.sections if s["name"] == ".got")
        self.assertEqual(got["size"], 8)


@need_gcc
class RealCompilerOutput(TmpCase):
    def build(self, flags=(), with_hook=True, ferrule_opts=None):
        objs_ = []
        for name in ("algo", "other", "rtlib") + (("hook",) if with_hook else ()):
            out = self.p(name + ".o")
            gcc_compile(os.path.join(CDIR, name + ".c"), out, flags)
            objs_.append(out)
        crt = self.p("crt.o")
        wfile(crt, assemble(rfile(os.path.join(CDIR, "crt.s")).decode(), "crt.s").to_bytes())
        return [crt] + objs_

    EXPECT = (b"primes<10000: 1229\n0123456789\nsquare=136 negate=94 ident=106 \n1011253147526899\n"
              b"counter=114 fib20=6765 hook=%s\n2635249153387078802\n")

    def test_gcc_program_prints_correct_results(self):
        res = link(self.build(), Options())
        rc, out = run_exe(res.data, self.tmp)
        self.assertEqual(out, self.EXPECT % b"4242")
        self.assertEqual(rc, 20)

    def test_weak_hook_absent(self):
        res = link(self.build(with_hook=False))
        rc, out = run_exe(res.data, self.tmp)
        self.assertEqual(out, self.EXPECT % b"999")

    def test_many_optimisation_and_pic_flavours(self):
        for flags in (["-O0"], ["-O1"], ["-O3"], ["-Os"], ["-O2", "-fPIE"], ["-O2", "-fpic"], ["-O2", "-g"],
                      ["-O0", "-fcf-protection=none"]):
            with self.subTest(flags=flags):
                res = link(self.build(flags))
                rc, out = run_exe(res.data, self.tmp, "p_" + "".join(flags).replace("-", ""))
                self.assertEqual((rc, out), (20, self.EXPECT % b"4242"))

    @need_gnu
    def test_fno_common_duplicate_is_rejected_like_gnu_ld(self):
        paths = self.build(["-fno-common"])
        with self.assertRaises(LinkError) as cm:
            link(paths)
        self.assertIn("multiple definition of `shared_common'", str(cm.exception))
        self.assertNotEqual(subprocess.run(["ld", "-o", self.p("g"), *paths], capture_output=True).returncode, 0)

    def test_function_sections_with_gc(self):
        paths = self.build(["-ffunction-sections", "-fdata-sections"])
        plain, gc = link(paths), link(paths, Options(gc_sections=True))
        for r, n in ((plain, "a"), (gc, "b")):
            self.assertEqual(run_exe(r.data, self.tmp, n), (20, self.EXPECT % b"4242"))
        self.assertTrue(any(s == ".text.rt_strlen" or "rt_strlen" in s for _, s, _, _ in gc.discarded))
        self.assertLess(sum(s["size"] for s in gc.sections), sum(s["size"] for s in plain.sections))

    @need_gnu
    def test_identical_behaviour_to_gnu_ld(self):
        paths = self.build(["-O2", "-ffunction-sections"])
        subprocess.run(["ld", "-o", self.p("gnu"), *paths], check=True, capture_output=True)
        theirs = subprocess.run([self.p("gnu")], capture_output=True)
        mine = run_exe(link(paths).data, self.tmp, "fer")
        self.assertEqual(mine, (theirs.returncode, theirs.stdout))

    @unittest.skipUnless(HAVE["g++"], "g++ missing")
    def test_cpp_comdat_groups_are_deduplicated(self):
        a, b = self.p("a.o"), self.p("b.o")
        wfile(self.p("a.cpp"), b'''extern "C" int main(); extern int other(int);
template <typename T> inline T twice(T x) { return x + x; }
inline int shared_inline(int x) { return twice(x) + 1; }
extern "C" int main() { return shared_inline(10) + other(3); }''')
        wfile(self.p("b.cpp"), b'''template <typename T> inline T twice(T x) { return x + x; }
inline int shared_inline(int x) { return twice(x) + 1; }
int other(int x) { return shared_inline(x); }''')
        for s, o in (("a.cpp", a), ("b.cpp", b)):
            gcc_compile(self.p(s), o, ["-O0", "-fno-exceptions", "-fno-rtti"])
        crt = self.p("crt.o")
        wfile(crt, assemble(rfile(os.path.join(CDIR, "crt.s")).decode(), "crt.s").to_bytes())
        res = link([crt, a, b])
        self.assertEqual(run_exe(res.data, self.tmp)[0], 28)
        self.assertTrue(any("duplicate COMDAT" in why for *_, why in res.discarded))


@need_readelf
class OutputFormat(TmpCase):
    def test_readelf_accepts_executable(self):
        res = link(objs(HELLO))
        wfile(self.p("x"), res.data)
        r = subprocess.run(["readelf", "-lSsW", self.p("x")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Warning", r.stdout + r.stderr)
        self.assertIn("EXEC (Executable file)", subprocess.run(["readelf", "-h", self.p("x")], capture_output=True, text=True).stdout)
        self.assertIn("LOAD", r.stdout)
        self.assertIn("GNU_STACK", r.stdout)

    def test_segments_are_page_congruent_and_nx(self):
        src = START + ".text\nmain:\n  ret\n.rodata\nr: .long 1\n.data\nd: .long 2\n.bss\nb: .zero 5000\n"
        res = link(objs(src))
        flags = [s["name"] for s in res.segments]
        self.assertEqual(flags, ["R-X", "R--", "RW-"])
        for s in res.segments:
            self.assertEqual(s["vaddr"] % 4096, s["offset"] % 4096)
            self.assertGreaterEqual(s["memsz"], s["filesz"])
        self.assertGreater(res.segments[2]["memsz"], res.segments[2]["filesz"] + 4999)   # bss is memsz-only
        self.assertTrue(all(not (s["flags"] & 1 and s["flags"] & 2) for s in res.segments))   # W^X

    def test_symbols_in_output_symtab(self):
        res = link(objs(HELLO))
        wfile(self.p("x"), res.data)
        out = subprocess.run(["nm", self.p("x")], capture_output=True, text=True).stdout
        self.assertIn(" T _start", out)
        self.assertIn(" T sys_write", out)


class ErrorsOnBadInput(TmpCase):
    def test_garbage_inputs(self):
        for blob in (b"", b"hello", b"\x7fELF" + b"\0" * 100):
            wfile(self.p("bad.o"), blob)
            with self.assertRaises(FerruleError):
                link([self.p("bad.o")])
        with self.assertRaises(LinkError):
            link([self.p("missing.o")])

    def test_unsupported_relocation_is_named(self):
        o = asm_obj(".global _start\n_start: nop\n")
        text = next(s for s in o.sections if s.name == ".text")
        sym = next(s for s in o.symbols if s.name == "_start")
        text.relocs.append(elf.Reloc(0, sym, 23, 0))         # R_X86_64_TPOFF32-ish: unsupported
        with self.assertRaises(LinkError) as cm:
            link([roundtrip(o)])
        self.assertIn("unsupported relocation", str(cm.exception))

    def test_bit_flipped_objects_never_crash(self):
        import random
        base = asm_obj(START + ".text\nmain:\n  call f\n  ret\n.global f\nf: ret\n.data\nd: .quad main\n").to_bytes()
        rng = random.Random(1234)
        for _ in range(400):
            d = bytearray(base)
            for _ in range(rng.randint(1, 5)):
                d[rng.randrange(len(d))] = rng.randrange(256)
            try:
                link([ElfObject.parse(bytes(d), "fz.o")], Options(allow_undefined=True, entry="0x400000"))
            except FerruleError:
                pass


if __name__ == "__main__":
    unittest.main()
