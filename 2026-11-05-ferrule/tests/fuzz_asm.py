"""Randomised differential fuzz: Ferrule's assembler vs GNU as (instruction forms + branch relaxation)."""
import os, random, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ferrule.asm import assemble
from ferrule.errors import FerruleError

R64 = "rax rcx rdx rbx rsp rbp rsi rdi r8 r9 r10 r11 r12 r13 r14 r15".split()
R32 = "eax ecx edx ebx esp ebp esi edi r8d r9d r10d r11d r12d r13d r14d r15d".split()
R16 = "ax cx dx bx sp bp si di r8w r9w r10w r11w r12w r13w r14w r15w".split()
R8 = "al cl dl bl spl bpl sil dil r8b r9b r10b r11b r12b r13b r14b r15b".split()
REGS = {64: R64, 32: R32, 16: R16, 8: R8}
PTR = {64: "qword ptr", 32: "dword ptr", 16: "word ptr", 8: "byte ptr"}
ALU = "add or adc sbb and sub xor cmp".split()


def reg(rng, size):
    return rng.choice(REGS[size])


def mem(rng, size=None):
    base = rng.choice(R64 + [None])
    idx = rng.choice([r for r in R64 if r != "rsp"] + [None, None])
    sc = rng.choice([1, 2, 4, 8])
    disp = rng.choice([None, 0, 1, -1, 127, 128, -128, -129, 0x1000, -0x1000, 0x7fffffff])
    parts = []
    if base:
        parts.append(base)
    if idx:
        parts.append(f"{idx}*{sc}")
    if disp is not None:
        parts.append(str(disp))
    if not parts:
        parts = ["0x1234"]
    body = "+".join(parts).replace("+-", "-")
    if base is None and idx is None:
        body = "0x1234"
    return (PTR[size] + " " if size else "") + f"[{body}]"


def imm(rng, size):
    lim = {8: 255, 16: 65535, 32: 0xFFFFFFFF, 64: 0x7FFFFFFF}[size]
    lo = {8: -128, 16: -32768, 32: -2**31, 64: -2**31}[size]
    c = [0, 1, -1, 5, 127, 128, -128, -129, 255, 256, 0x7FFF, 0x1000, lim, lo, lim - 1, 0x8000, 0xFFFF]
    v = rng.choice(c) if rng.random() < .7 else rng.randint(-100, 100000)
    return max(lo, min(lim, v))


def gen(rng):
    k = rng.randrange(18)
    sz = rng.choice([8, 16, 32, 64])
    if k == 0:
        return f"{rng.choice(ALU)} {reg(rng, sz)}, {reg(rng, sz)}"
    if k == 1:
        return f"{rng.choice(ALU)} {mem(rng, sz)}, {reg(rng, sz)}"
    if k == 2:
        return f"{rng.choice(ALU)} {reg(rng, sz)}, {mem(rng, sz)}"
    if k == 3:
        d = reg(rng, sz) if rng.random() < .5 else mem(rng, sz)
        return f"{rng.choice(ALU + ['mov', 'test'])} {d}, {imm(rng, sz)}"
    if k == 4:
        return f"mov {reg(rng, sz)}, {reg(rng, sz)}"
    if k == 5:
        return f"lea {reg(rng, rng.choice([16, 32, 64]))}, {mem(rng)}"
    if k == 6:
        return f"{rng.choice(['shl', 'shr', 'sar', 'rol', 'ror'])} {reg(rng, sz)}, {rng.choice(['1', '3', 'cl'])}"
    if k == 7:
        return f"{rng.choice(['inc', 'dec', 'neg', 'not', 'mul', 'div', 'idiv'])} {reg(rng, sz) if rng.random() < .5 else mem(rng, sz)}"
    if k == 8:
        return f"imul {reg(rng, sz if sz > 8 else 32)}, {reg(rng, sz if sz > 8 else 32)}"
    if k == 9:
        s = rng.choice([32, 64])
        return f"{rng.choice(['movzx', 'movsx'])} {reg(rng, s)}, {rng.choice([reg(rng, 8), mem(rng, 8)])}"
    if k == 10:
        return f"{rng.choice(['push', 'pop'])} {reg(rng, 64)}"
    if k == 11:
        return f"cmov{rng.choice(['e', 'ne', 'l', 'g', 'a', 'b', 's', 'ns', 'le', 'ge'])} {reg(rng, 32 if rng.random() < .5 else 64)}, {reg(rng, 32 if rng.random()<.5 else 64)}"
    if k == 12:
        return f"set{rng.choice(['e', 'ne', 'l', 'g', 'a', 'b'])} {reg(rng, 8)}"
    if k == 13:
        return f"test {reg(rng, sz)}, {reg(rng, sz)}"
    if k == 14:
        s2 = sz if sz > 8 else 32
        return f"imul {reg(rng, s2)}, {reg(rng, s2) if rng.random() < .5 else mem(rng, s2)}, {imm(rng, s2)}"
    if k == 15:
        return f"xchg {reg(rng, sz)}, {reg(rng, sz)}"
    if k == 16:
        s2 = sz if sz > 8 else 32
        return f"{rng.choice(['bsf', 'bsr', 'popcnt'])} {reg(rng, s2)}, {reg(rng, s2) if rng.random() < .5 else mem(rng, s2)}"
    return f"mov {mem(rng, sz)}, {reg(rng, sz)}"


def gas(lines, d):
    s, o, b = (os.path.join(d, n) for n in ("f.s", "f.o", "f.bin"))
    open(s, "w").write(".intel_syntax noprefix\n.text\n" + "\n".join(lines) + "\n")
    r = subprocess.run(["as", "--64", "-msyntax=intel", "-mnaked-reg", "-o", o, s], capture_output=True, text=True)
    if r.returncode:
        return None
    subprocess.run(["objcopy", "-O", "binary", "-j", ".text", o, b], check=True)
    return open(b, "rb").read()


def fer(lines):
    obj = assemble(".intel_syntax noprefix\n.text\n" + "\n".join(lines) + "\n")
    return next(s for s in obj.sections if s.name == ".text").data


def fuzz_instructions(n, seed):
    rng = random.Random(seed)
    stats = dict(ok=0, both_reject=0, ferrule_rejects_valid=[], mismatch=[], accepts_invalid=[])
    with tempfile.TemporaryDirectory() as d:
        for _ in range(n):
            ln = gen(rng)
            g = gas([ln], d)
            try:
                f = fer([ln])
            except FerruleError:
                f = None
            if g is None and f is None:
                stats["both_reject"] += 1
            elif g is None:
                stats["accepts_invalid"].append((ln, f.hex()))
            elif f is None:
                stats["ferrule_rejects_valid"].append(ln)
            elif g != f:
                stats["mismatch"].append((ln, g.hex(), f.hex()))
            else:
                stats["ok"] += 1
    return stats


def fuzz_branches(n, seed):
    """Random label/jump/filler programs: relaxation must reproduce gas exactly."""
    rng = random.Random(seed)
    bad = []
    with tempfile.TemporaryDirectory() as d:
        for t in range(n):
            nl = rng.randint(2, 7)
            lines = []
            for i in range(rng.randint(5, 30)):
                r = rng.random()
                if r < .35:
                    lines.append(f"L{rng.randrange(nl)}:" if rng.random() < .5 else f"{rng.choice(['jmp','je','jne','jl','jg','ja','jb','js','jns'])} L{rng.randrange(nl)}")
                elif r < .5:
                    lines.append(f".skip {rng.choice([1, 3, 20, 60, 100, 120, 126, 127, 128, 129, 250])}, 0x90")
                else:
                    lines.append(rng.choice(["nop", "mov rax, rbx", "add rax, 0x1000", "xor ecx, ecx", "call ext_fn"]))
            for i in range(nl):
                lines.append(f"L{i}:")
            lines = list(dict.fromkeys(l for l in lines if not l.endswith(":"))) and lines
            seen, out = set(), []
            for l in lines:
                if l.endswith(":"):
                    if l in seen:
                        continue
                    seen.add(l)
                out.append(l)
            g = gas(out, d)
            f = fer(out)
            if g != f:
                bad.append(out)
    return bad


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    st = fuzz_instructions(n, int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    print({k: (v if isinstance(v, int) else len(v)) for k, v in st.items()})
    for k in ("mismatch", "ferrule_rejects_valid", "accepts_invalid"):
        for x in st[k][:15]:
            print(k, x)
    bad = fuzz_branches(150, 7)
    print("branch programs mismatching:", len(bad))
    for b in bad[:2]:
        print(b)
