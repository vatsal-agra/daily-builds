import sys, os, traceback, struct, random
from ferrule.asm import assemble
from ferrule.elf import ElfObject
from ferrule.ar import Archive
from ferrule.link import link, Options
from ferrule.errors import FerruleError
res = []
def attempt(name, fn):
    try:
        r = fn()
        res.append((name, "OK", str(r)[:60]))
    except FerruleError as e:
        res.append((name, "clean-error", str(e).splitlines()[0][:90]))
    except Exception as e:
        res.append((name, "CRASH " + type(e).__name__, str(e)[:90]))

H = ".intel_syntax noprefix\n.text\n"
asm_cases = {
 "unknown insn": "frobnicate rax",
 "mem,mem": "mov [rax], [rbx]",
 "trailing comma": "mov rax,",
 "size mismatch": "mov eax, rbx",
 "push eax": "push eax",
 "imm too big byte": "mov al, 300",
 "imm too big 32": "add eax, 0x100000000",
 "dup label": "a:\na:",
 "unterminated string": '.ascii "abc',
 "bad escape": '.ascii "a\\qb"',
 "align 3": ".align 3",
 "byte 256": ".byte 256",
 "byte -129": ".byte -129",
 "quad neg": ".quad -1",
 "huge zero": ".zero 1<<40",
 "neg zero": ".zero -5",
 "equ forward chain": ".equ A, B+1\n.equ B, C+1\n.equ C, 5\nmov eax, offset A",
 "equ label": "x:\n.equ Y, x+4\nmov eax, offset Y",
 "div by zero": ".long 1/0",
 "unbalanced paren": ".long (1+2",
 "empty operand": "mov rax,,rbx",
 "rip alone": "mov rax, rip",
 "rip+rax": "lea rax, [rip+rax]",
 "two idx": "mov rax, [rax*2+rbx*2]",
 "bad scale": "mov rax, [rax*3]",
 "rsp index": "mov rax, [rbx+rsp*2]",
 "ah+rex": "mov ah, sil",
 "ah+r8": "mov ah, r8b",
 "mem no size": "mov [rax], 5",
 "inc no size": "inc [rax]",
 "movzx amb": "movzx eax, [rax]",
 "jmp const": "jmp 5",
 "att syntax": ".att_syntax\nmovq %rax,%rbx",
 "crlf": "mov rax, rbx\r\nret\r\n",
 "upper": "MOV RAX, RBX\nRET",
 "label+insn": "l: mov rax, 1",
 "unicode": "mov rax, 1 ; é",
 "non-const align": ".align foo",
 "sub sym diff other section": ".data\nd: .long 1\n.text\nt: .long t - d",
 "sym - . ": "t: .long ext - .",
 "sym*2": ".long ext*2",
 "size sym": "foo: ret\n.size foo, .-foo",
 "type": ".type foo, @function\nfoo: ret",
 "comm dup": "x: .long 1\n.comm x, 4",
 "fill": ".fill 3, 1, 0",
 "huge align": ".balign 1<<20",
 "bss data": ".bss\n.long 1",
 "section unknown type": '.section .foo,"a",@note',
 "mov rax,[sym]": "mov rax, [ext]",
 "call [ext]": "call [rip+ext@GOTPCREL]",
 "2gb disp": "mov rax,[rbx+0x80000000]",
 "neg rip": "lea rax,[rip-0x10]",
 "ret imm": "ret 8",
 "int": "int 0x80",
 "push imm big": "push 0x100000000",
}
for n, src in asm_cases.items():
    attempt("asm: " + n, lambda s=src: assemble(H + s + "\n").to_bytes()[:0] or "ok")

def mk(src): return assemble(H + src + "\n")
obj_ok = mk(".global _start\n_start: ret").to_bytes()
good = obj_ok
blobs = {
 "empty": b"", "garbage": b"hello world"*10, "elf magic only": b"\x7fELF",
 "truncated obj": good[:100], "truncated obj2": good[:len(good)-30],
 "32-bit class": b"\x7fELF\x01\x01\x01" + good[7:],
 "bad shoff": good[:40] + struct.pack("<Q", 10**9) + good[48:],
 "bad shnum": good[:60] + struct.pack("<H", 5000) + good[62:],
 "shstrndx oob": good[:62] + struct.pack("<H", 99) + good[64:],
}
for n, b in blobs.items():
    attempt("parse: " + n, lambda b=b: ElfObject.parse(b, "x.o"))
rng = random.Random(5)
crash = 0
for i in range(300):   # random byte flips in a real gcc object
    data = bytearray(open("/tmp/c1/util.o", "rb").read())
    for _ in range(rng.randint(1, 8)):
        data[rng.randrange(len(data))] = rng.randrange(256)
    try:
        o = ElfObject.parse(bytes(data), "fz.o")
        try:
            link([o], Options(allow_undefined=True, entry="0x400000"))
        except FerruleError:
            pass
    except FerruleError:
        pass
    except Exception as e:
        crash += 1
        if crash <= 3: res.append(("bitflip", "CRASH " + type(e).__name__, str(e)[:80]))
res.append(("bitflip fuzz (300)", "crashes=%d" % crash, ""))
ar_bad = {"bad magic": b"!<arch>X", "trunc hdr": b"!<arch>\n" + b"a/" * 10, "bad size": b"!<arch>\n" + b"x/".ljust(16) + b"0".ljust(12) * 1 + b"0".ljust(6) * 2 + b"644".ljust(8) + b"zzzz".ljust(10) + b"`\n"}
for n, b in ar_bad.items():
    attempt("archive: " + n, lambda b=b: Archive.parse(b, "x.a"))
# link semantics
a = mk(".global f\nf: ret").to_bytes(); 
def L(*srcs, **kw):
    objs = [ElfObject.parse(mk(s).to_bytes(), f"o{i}.o") for i, s in enumerate(srcs)]
    return link(objs, Options(**kw))
attempt("link: dup strong", lambda: L(".global _start\n_start: ret", ".global _start\n_start: ret"))
attempt("link: undefined", lambda: L(".global _start\n_start: call nowhere"))
attempt("link: weak undef -> 0", lambda: L(".global _start\n.weak w\n_start: lea rax, [rip+w]\nret").entry)
attempt("link: no entry", lambda: L("nop"))
attempt("link: numeric entry", lambda: L("nop", entry="0x401000").entry)
attempt("link: PC32 overflow", lambda: L(".global _start\n_start: mov eax, far\n.data\n.global far\nfar: .long 1", base=0x100000000))
attempt("link: abs32 overflow", lambda: L(".global _start\n_start: mov eax, offset far\n.data\n.global far\nfar: .long 1", base=0x100000000))
attempt("link: local name clash", lambda: L(".global _start\n_start: call a\nret\na: ret", "a: ret\n.global g\ng: call a").entry if False else L(".global _start\n_start: ret\nloc: ret", "loc: ret").entry)
attempt("link: only bss", lambda: L(".global _start\n_start: ret\n.bss\nb: .zero 1000").segments)
attempt("link: only data no text", lambda: L(".data\n.global _start\n_start: .long 1").segments)
attempt("link: align 4096 data", lambda: L('.global _start\n_start: ret\n.section .data.x,"aw"\n.balign 4096\nx: .long 1'))
attempt("link: .long sym in rodata", lambda: L(".global _start\n_start: ret\n.rodata\n.long _start"))
attempt("link: empty text", lambda: L(".global _start\n.set _start, 0"))
attempt("link: base unaligned", lambda: L(".global _start\n_start: ret", base=0x400123))
attempt("link: gc keep entry", lambda: L(".global _start\n_start: ret\n.section .text.dead,\"ax\"\ndead: ret", gc_sections=True).discarded)
for n, s, d in res:
    flag = "  <-- BAD" if s.startswith("CRASH") else ""
    print(f"{n:34s} {s:22s} {d}{flag}")
