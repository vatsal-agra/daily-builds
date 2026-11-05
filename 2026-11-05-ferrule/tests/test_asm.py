import unittest
from helpers import *
from ferrule import elf
from ferrule.errors import AsmError, FerruleError

GOLDEN = {   # hand-verified against the Intel SDM, independent of GNU as
    "mov rax, rbx": "4889d8", "mov eax, 1": "b801000000", "mov rax, 1": "48c7c001000000",
    "xor eax, eax": "31c0", "add rax, 5": "4883c005", "add rax, 0x1000": "480500100000",
    "sub rsp, 0x28": "4883ec28", "push r12": "4154", "pop rbx": "5b", "ret": "c3", "syscall": "0f05",
    "lea rax, [rbx+rcx*4+3]": "488d448b03", "mov rax, [rsp+16]": "488b442410",
    "mov rax, [r13]": "498b4500", "mov [rbp-4], eax": "8945fc", "imul rax, rbx, 10": "486bc30a",
    "movzx eax, byte ptr [rdi]": "0fb607", "movsxd rax, ecx": "4863c1", "cqo": "4899",
    "shl rax, 1": "48d1e0", "sar r8, 63": "49c1f83f", "sete al": "0f94c0", "cmovne eax, ebx": "0f45c3",
    "mov ah, 5": "b405", "mov sil, dil": "4088fe", "rep movsb": "f3a4", "lock xadd [rdi], rax": "f0480fc107",
    "movabs rax, 0x1122334455667788": "48b88877665544332211", "bswap r9": "490fc9", "xchg rax, rbx": "4893",
}


class GoldenEncodings(unittest.TestCase):
    def test_golden(self):
        for src, hexs in GOLDEN.items():
            with self.subTest(src):
                self.assertEqual(asm_bytes(src).hex(), hexs)


@need_gnu
class AgainstGnuAs(TmpCase):
    def test_corpus_byte_identical(self):
        from gas_diff import run
        lines = rfile(os.path.join(HERE, "corpus.s")).decode().splitlines()
        self.assertEqual(run(lines), [])

    def test_random_instructions_and_relaxation(self):
        import fuzz_asm
        st = fuzz_asm.fuzz_instructions(250, 4242)
        self.assertEqual((st["mismatch"], st["ferrule_rejects_valid"], st["accepts_invalid"]), ([], [], []))
        self.assertGreater(st["ok"], 150)
        self.assertEqual(fuzz_asm.fuzz_branches(40, 99), [])

    def test_whole_program_sections_and_relocs_match_gas(self):
        import subprocess
        src = os.path.join(HERE, "prog1.s")
        subprocess.run(["as", "--64", "-msyntax=intel", "-mnaked-reg", "-o", self.p("g.o"), src], check=True)
        mine = assemble(rfile(src).decode(), "prog1.s")
        wfile(self.p("f.o"), mine.to_bytes())
        for sec in (".data", ".rodata"):
            subprocess.run(["objcopy", "-O", "binary", "-j", sec, self.p("g.o"), self.p("g.bin")], check=True)
            self.assertEqual(rfile(self.p("g.bin")), next(s for s in mine.sections if s.name == sec).data, sec)

        def relocs(path):
            out = subprocess.run(["readelf", "-rW", path], capture_output=True, text=True).stdout
            rows = [l.split() for l in out.splitlines() if "R_X86_64" in l]
            return sorted((r[2].replace("32S", "32"), r[4] if len(r) > 4 else "", r[5:] and r[5] or "", r[6:] and r[6] or "") for r in rows)
        self.assertEqual(len(relocs(self.p("g.o"))), len(relocs(self.p("f.o"))))


class DirectivesAndErrors(unittest.TestCase):
    def sec(self, src, name):
        o = asm_obj(src)
        return next(s for s in o.sections if s.name == name)

    def test_data_directives(self):
        d = self.sec('.data\n.byte 1,0xff,-1\n.word 0x1234\n.long 0xdeadbeef\n.quad -2\n.ascii "A\\n\\x41\\101"\n.asciz "z"\n.zero 3\n.fill 2,2,0x0102', ".data").data
        self.assertEqual(d, bytes([1, 255, 255, 0x34, 0x12, 0xef, 0xbe, 0xad, 0xde]) + (2**64 - 2).to_bytes(8, "little")
                         + b"A\nAA" + b"z\0" + b"\0\0\0" + b"\x02\x01\x02\x01")

    def test_align_pads_with_nops_in_text_and_zero_in_data(self):
        t = self.sec(".text\nnop\n.align 8\nret", ".text")
        self.assertEqual(len(t.data), 9)
        self.assertEqual(t.data[0], 0x90)
        self.assertEqual(t.data[1:8], b"\x0f\x1f\x80\0\0\0\0")   # canonical 7-byte NOP, not zero fill
        d = self.sec(".data\n.byte 1\n.balign 4\n.byte 2", ".data")
        self.assertEqual(d.data, b"\x01\0\0\0\x02")

    def test_relaxation_short_then_near(self):
        short = asm_bytes("a: jmp a")
        self.assertEqual(short.hex(), "ebfe")
        near = asm_bytes("jmp end\n.skip 200\nend: nop")
        self.assertEqual(near[:5].hex(), "e9c8000000")
        edge = asm_bytes("jmp end\n.skip 127\nend: nop")          # exactly in range -> short
        self.assertEqual(edge[:2].hex(), "eb7f")
        edge2 = asm_bytes("jmp end\n.skip 128\nend: nop")
        self.assertEqual(edge2[0], 0xE9)
        jcc = asm_bytes("jne end\n.skip 300\nend: nop")
        self.assertEqual(jcc[:2].hex(), "0f85")

    def test_relocation_types(self):
        o = asm_obj(".text\ncall ext\nmov rax, [rip+v]\nmov eax,[v]\nmov eax,offset v\nmov rax,[rip+g@GOTPCREL]\n"
                    "movabs rax, v\n.data\nv: .quad v\n.long v\n.long ext - .\n.long v - .\n.word v\n.byte v\n")
        got = [(r.type, r.sym.name or r.sym.section.name, r.addend) for s in o.sections for r in s.relocs]
        t = elf
        self.assertIn((t.R_X86_64_PLT32, "ext", -4), got)
        self.assertIn((t.R_X86_64_PC32, ".data", -4), got)
        self.assertIn((t.R_X86_64_32S, ".data", 0), got)
        self.assertIn((t.R_X86_64_GOTPCREL, "g", -4), got)
        self.assertIn((t.R_X86_64_64, ".data", 0), got)
        self.assertIn((t.R_X86_64_32, ".data", 0), got)
        self.assertIn((t.R_X86_64_PC32, "ext", 0), got)       # `ext - .` is PC-relative against the field itself
        data = next(s for s in o.sections if s.name == ".data").data
        self.assertEqual(int.from_bytes(data[16:20], "little", signed=True), -16)   # `v - .` folded: no reloc needed
        self.assertIn((t.R_X86_64_16, ".data", 0), got)
        self.assertIn((t.R_X86_64_8, ".data", 0), got)

    def test_equ_constants_and_label_aliases(self):
        a = asm_bytes(".equ N, 5\n.equ M, N*2+1\nmov eax, M\nmov al, N")
        self.assertEqual(a.hex(), "b80b000000b005")
        b = asm_bytes("x: nop\nnop\n.equ Y, x+1\njmp Y")
        self.assertEqual(b.hex(), "9090ebfd")   # jmp (at 2, len 2) -> alias Y = 1 : disp = 1 - 4 = -3
        with self.assertRaises(AsmError):
            asm_obj(".text\n.equ A, B\n.equ B, A\nmov eax, offset A")

    def test_dot_means_location_of_the_directive_not_end_of_section(self):
        o = asm_obj(".text\n.global f, g\n.type f, @function\nf: nop\nnop\n.size f, .-f\ng: ret\nret\nret\n.size g, .-g\n"
                    ".rodata\nmsg: .ascii \"hello\"\n.equ msg_len, . - msg\n.ascii \"more\"\n.text\nmov eax, msg_len\n")
        by = {s.name: s for s in o.symbols}
        self.assertEqual((by["f"].size, by["g"].size), (2, 3))
        text = next(s for s in o.sections if s.name == ".text").data
        self.assertEqual(text[-5:].hex(), "b805000000")                 # msg_len == 5, not 9

    def test_symbol_binding_and_types(self):
        o = asm_obj(".text\n.global g\n.weak w\n.type g, @function\ng: ret\nw: ret\nl: ret\n.size g, .-g\n.comm cc, 16, 8\n")
        by = {s.name: s for s in o.symbols}
        self.assertEqual((by["g"].bind, by["g"].type, by["g"].size), (elf.STB_GLOBAL, elf.STT_FUNC, 3))   # `.-g` evaluated at the .size directive
        self.assertEqual(by["w"].bind, elf.STB_WEAK)
        self.assertEqual(by["l"].bind, elf.STB_LOCAL)
        self.assertEqual((by["cc"].shndx, by["cc"].size, by["cc"].value), (elf.SHN_COMMON, 16, 8))

    def test_errors_carry_line_and_source(self):
        cases = ["frobnicate rax", "mov [rax], [rbx]", "mov al, 300", "mov rax, [rbx*3]", "push eax", "a:\na:",
                 '.ascii "abc', ".align 3", ".byte 256", "mov ah, sil", "jmp 5", "mov eax, rbx", ".zero 1<<40",
                 "cmovg r9, r9d", "lea rax, [rip+rax]", "inc [rax]", "mov rax, rip", ".att_syntax"]
        for src in cases:
            with self.subTest(src):
                with self.assertRaises(AsmError) as cm:
                    asm_obj(".text\n" + src + "\n")
                self.assertIsNotNone(cm.exception.line)
                self.assertTrue(str(cm.exception).startswith("t.s:"))

    def test_case_crlf_comments(self):
        a = asm_bytes("MOV RAX, RBX ; c\r\n  # full comment\r\nRET\r\n")
        self.assertEqual(a.hex(), "4889d8c3")

    def test_bss_and_sections(self):
        o = asm_obj('.bss\nb: .zero 100\n.section .rodata.str1.1,"aMS",@progbits\n.asciz "x"\n.section .mydata,"aw",@progbits\n.long 1')
        names = {s.name: s for s in o.sections}
        self.assertEqual(names[".bss"].size, 100)
        self.assertEqual(names[".bss"].type, elf.SHT_NOBITS)
        self.assertTrue(names[".mydata"].flags & elf.SHF_WRITE)
        with self.assertRaises(AsmError):
            asm_obj(".bss\n.long 1")


if __name__ == "__main__":
    unittest.main()
