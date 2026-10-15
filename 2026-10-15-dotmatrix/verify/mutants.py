#!/usr/bin/env python3
"""Mutation testing: break the emulator/assembler in small, plausible ways and
confirm the test suite (Go tests + in-emulator ROMs) notices every time."""
import os, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (name, file, old, new, count)  — old must occur exactly `count` times (default 1)
M = [
 ("cpu: ADC ignores carry in half-carry", "gb/cpu.go", "uint16(a&0xF)+uint16(v&0xF)+cy > 0xF", "uint16(a&0xF)+uint16(v&0xF) > 0xF"),
 ("cpu: SBC ignores carry in half-borrow", "gb/cpu.go", "int(a&0xF)-int(v&0xF)-cy < 0", "int(a&0xF)-int(v&0xF) < 0"),
 ("cpu: DAA low-nibble threshold", "gb/cpu.go", "g.flag(FlagH) || a&0xF > 9", "g.flag(FlagH) || a&0xF > 10"),
 ("cpu: INC half-carry", "gb/cpu.go", "g.setFlag(FlagH, v&0xF == 0xF)", "g.setFlag(FlagH, v&0xF == 0xE)"),
 ("cpu: DEC half-borrow", "gb/cpu.go", "g.setFlag(FlagH, v&0xF == 0)", "g.setFlag(FlagH, v&0xF == 1)"),
 ("cpu: ADD SP carry from low byte", "gb/cpu.go", "(sp&0xFF)+(u&0xFF) > 0xFF", "(sp&0xFF)+(u&0xFF) > 0x100"),
 ("cpu: RLCA/RRCA/RLA/RRA no longer clear Z", "gb/cpu.go", "g.f &^= FlagZ", "_ = 0", 4),
 ("cpu: HALT bug becomes plain halt", "gb/cpu.go", "g.haltBug = true // next opcode byte is fetched twice", "g.halted = true"),
 ("cpu: EI takes effect immediately", "gb/cpu.go", "g.imeNext = true\n\t\t\t\treturn 1", "g.ime = true\n\t\t\t\treturn 1"),
 ("cpu: interrupt vector spacing", "gb/cpu.go", "g.pc = 0x40 + uint16(i)*8", "g.pc = 0x40 + uint16(i)*4"),
 ("cpu: POP AF keeps low nibble", "gb/cpu.go", "c.a, c.f = uint8(v>>8), uint8(v)&0xF0", "c.a, c.f = uint8(v>>8), uint8(v)"),
 ("cpu: interrupt dispatch cost", "gb/cpu.go", "g.pc = 0x40 + uint16(i)*8\n\t\t\t\treturn 5", "g.pc = 0x40 + uint16(i)*8\n\t\t\t\treturn 4"),
 ("cpu: taken JR cc cycle count", "gb/cpu.go", "g.pc += uint16(int16(e))\n\t\t\t\t\treturn 3\n\t\t\t\t}\n\t\t\t\treturn 2", "g.pc += uint16(int16(e))\n\t\t\t\t\treturn 2\n\t\t\t\t}\n\t\t\t\treturn 2"),
 ("cpu: LD A,(HL-) increments", "gb/cpu.go", "g.setHL(addr - 1)", "g.setHL(addr + 1)"),
 ("cpu: SRA loses sign bit", "gb/cpu.go", "r = v>>1 | v&0x80", "r = v >> 1"),
 ("timer: TAC 11 selects wrong bit", "gb/timer.go", "{9, 3, 5, 7}", "{9, 3, 5, 6}"),
 ("timer: TIMA reload value", "gb/timer.go", "t.tima = t.tma\n\t\tg.ifl |= IntTimer", "t.tima = 0\n\t\tg.ifl |= IntTimer"),
 ("timer: DIV write skips falling edge", "gb/timer.go", "t.counter = 0\n\tif old && !t.signal() {\n\t\tg.timerIncrement()\n\t}", "t.counter = 0\n\t_ = old"),
 ("bus: echo RAM offset", "gb/bus.go", "return g.wram[addr-0xE000]", "return g.wram[(addr-0xE000)&0xFFF]"),
 ("bus: IF upper bits", "gb/bus.go", "return g.ifl | 0xE0", "return g.ifl"),
 ("bus: VRAM not blocked in mode 3 (read)", "gb/bus.go", "if g.PPU.lcdOn() && g.PPU.mode == 3 {\n\t\t\treturn 0xFF", "if g.PPU.lcdOn() && g.PPU.mode == 9 {\n\t\t\treturn 0xFF"),
 ("bus: OAM DMA length", "gb/bus.go", "if g.dma.idx >= 0xA0 {", "if g.dma.idx >= 0x9F {"),
 ("bus: serial result byte", "gb/bus.go", "g.io[1] = 0xFF // nothing connected", "g.io[1] = 0x00 // nothing connected"),
 ("ppu: mode 3 base length", "gb/ppu.go", "n := 172 +", "n := 170 +"),
 ("ppu: sprite X flip ignored", "gb/render.go", "bit = uint(i)", "bit = uint(7 - i)"),
 ("ppu: 11 sprites per line", "gb/render.go", "len(out) < 10", "len(out) < 11"),
 ("ppu: signed tile addressing", "gb/render.go", "base = 0x1000 + int(int8(idx))*16", "base = 0x1000 + int(idx)*16"),
 ("ppu: sprite priority order", "gb/render.go", "return sp[i].x < sp[j].x", "return sp[i].x > sp[j].x"),
 ("ppu: window line counter", "gb/ppu.go", "p.winLine++", "_ = p.winLine"),
 ("ppu: STAT LYC coincidence", "gb/ppu.go", "if p.ly == p.lyc && p.stat&0x40 != 0 {", "if p.ly == p.lyc+1 && p.stat&0x40 != 0 {"),
 ("ppu: OBJ priority bit", "gb/render.go", "if s.attr&0x80 != 0 && p.bgRaw[x] != 0 {", "if s.attr&0x80 != 0 && p.bgRaw[x] == 9 {"),
 ("cart: MBC1 bank 0 maps to 1", "gb/cart.go", "if b == 0 {\n\t\t\tb = 1\n\t\t}\n\t\treturn (b | c.ramBank<<5)", "if b == 99 {\n\t\t\tb = 1\n\t\t}\n\t\treturn (b | c.ramBank<<5)"),
 ("cart: RAM enable value", "gb/cart.go", "c.ramEnable = v&0x0F == 0x0A", "c.ramEnable = v&0x0F != 0", 3),
 ("cart: RTC seconds rollover", "gb/cart.go", "if c.rtc[0] < 60 {", "if c.rtc[0] < 61 {"),
 ("cart: header checksum", "gb/cart.go", "x = x - rom[i] - 1\n\t}\n\th.HeaderOK", "x = x - rom[i]\n\t}\n\th.HeaderOK"),
 ("apu: 25% duty pattern", "gb/apu.go", "{1, 0, 0, 0, 0, 0, 0, 1}, // 25%", "{1, 1, 0, 0, 0, 0, 0, 1}, // 25%"),
 ("apu: envelope direction", "gb/apu.go", "if add && *vol < 15 {", "if !add && *vol < 15 {"),
 ("apu: noise 7-bit mode", "gb/apu.go", "c.lfsr = c.lfsr&^(1<<6) | x<<6", "c.lfsr = c.lfsr&^(1<<5) | x<<5"),
 ("apu: pan right channel", "gb/apu.go", "if a.pan&(1<<uint(i)) != 0 {\n\t\t\tr += v", "if a.pan&(1<<uint(i)) == 0 {\n\t\t\tr += v"),
 ("apu: sweep direction", "gb/apu.go", "n := c.shadow + d\n\tif c.sweepNeg {\n\t\tn = c.shadow - d\n\t}", "n := c.shadow - d\n\tif c.sweepNeg {\n\t\tn = c.shadow + d\n\t}"),
 ("apu: wave volume code 2", "gb/apu.go", "case 2:\n\t\t\ts >>= 1", "case 2:\n\t\t\ts >>= 2"),
 ("asm: JR offset base", "asm/asm.go", "rel := v - (it.pc + t.Size)", "rel := v - (it.pc + 1)"),
 ("asm: header checksum", "asm/asm.go", "x = x - rom[i] - 1\n\t\t}\n\t\trom[0x14D] = x", "x = x - rom[i]\n\t\t}\n\t\trom[0x14D] = x"),
 ("asm: .db range check", "asm/asm.go", "if v < -128 || v > 255 {\n\t\t\t\t\ta.errf(it.loc, \"value %d does not fit in a byte\"", "if v < -128 || v > 65535 {\n\t\t\t\t\ta.errf(it.loc, \"value %d does not fit in a byte\""),
 ("asm: overlap detection", "asm/asm.go", "if _, dup := a.rom[off]; dup {", "if _, dup := a.rom[off]; dup && false {"),
 ("asm: shift operator precedence", "asm/expr.go", "v := p.parseAdd()\n\tfor p.err == nil {\n\t\tswitch {\n\t\tcase p.peek2(\"<<\")", "v := p.parseMul()\n\tfor p.err == nil {\n\t\tswitch {\n\t\tcase p.peek2(\"<<\")"),
 ("dbg: condition <= operator", "gb/debug.go", "case \"<=\":\n\t\t\tok = have <= t.want", "case \"<=\":\n\t\t\tok = have < t.want"),
 ("state: cartridge identity check", "gb/state.go", "if c.err == nil && id != g.cartID() {", "if c.err == nil && id != g.cartID() && false {"),
 ("state: trailing data check", "gb/state.go", "if c.pos != len(data) {", "if c.pos != len(data) && false {"),
]
M = [m for m in M if m]

def run(m):
    name, f, old, new = m[:4]
    count = m[4] if len(m) > 4 else 1
    tmp = tempfile.mkdtemp(prefix="mut-")
    try:
        dst = os.path.join(tmp, "src")
        shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "verify", "node_modules"))
        p = os.path.join(dst, f)
        s = open(p).read()
        if s.count(old) != count:
            return (name, "BAD-MUTANT", f"pattern occurs {s.count(old)}x, expected {count}")
        open(p, "w").write(s.replace(old, new))
        r = subprocess.run(["go", "test", "./...", "-count=1", "-timeout", "300s"], cwd=dst, capture_output=True, text=True)
        if r.returncode == 0:
            return (name, "SURVIVED", "")
        if "build failed" in r.stdout + r.stderr or "[build failed]" in r.stdout:
            return (name, "BAD-MUTANT", "does not compile")
        first = next((l.strip() for l in (r.stdout + r.stderr).splitlines() if "FAIL" in l or "--- FAIL" in l or "error" in l.lower()), "")
        return (name, "killed", first[:90])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    only = sys.argv[1:] 
    sel = [m for m in M if not only or any(o in m[0] for o in only)]
    with ThreadPoolExecutor(max_workers=int(os.environ.get("JOBS", "4"))) as ex:
        res = list(ex.map(run, sel))
    killed = survived = bad = 0
    for name, status, info in res:
        print(f"{status:10} {name}" + (f"   [{info}]" if info and status != "killed" else ""))
        killed += status == "killed"; survived += status == "SURVIVED"; bad += status == "BAD-MUTANT"
    total = killed + survived
    print(f"\n{killed}/{total} mutants killed" + (f", {bad} invalid mutant definitions" if bad else ""))
    sys.exit(1 if survived or bad else 0)
