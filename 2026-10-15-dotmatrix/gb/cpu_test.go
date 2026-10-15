package gb

import (
	"fmt"
	"testing"
)

func flags(z, n, h, c bool) uint8 {
	var f uint8
	if z {
		f |= FlagZ
	}
	if n {
		f |= FlagN
	}
	if h {
		f |= FlagH
	}
	if c {
		f |= FlagC
	}
	return f
}

// Reference ALU written independently from the implementation (wide integer
// arithmetic with explicit nibble carries).
func refALU(op int, a, v uint8, cin bool) (res, f uint8) {
	ci := 0
	if cin {
		ci = 1
	}
	switch op {
	case 0, 1: // add / adc
		if op == 0 {
			ci = 0
		}
		sum := int(a) + int(v) + ci
		low := int(a&15) + int(v&15) + ci
		r := uint8(sum)
		return r, flags(r == 0, false, low > 15, sum > 255)
	case 2, 3, 7: // sub / sbc / cp
		if op != 3 {
			ci = 0
		}
		diff := int(a) - int(v) - ci
		low := int(a&15) - int(v&15) - ci
		r := uint8(diff)
		if op == 7 {
			return a, flags(r == 0, true, low < 0, diff < 0)
		}
		return r, flags(r == 0, true, low < 0, diff < 0)
	case 4:
		r := a & v
		return r, flags(r == 0, false, true, false)
	case 5:
		r := a ^ v
		return r, flags(r == 0, false, false, false)
	}
	r := a | v
	return r, flags(r == 0, false, false, false)
}

func TestALUExhaustive(t *testing.T) {
	names := []string{"add", "adc", "sub", "sbc", "and", "xor", "or", "cp"}
	for op := 0; op < 8; op++ {
		// ALU A,B : opcode 0x80 | op<<3 | 0
		g := onlyOp(t, byte(0x80|op<<3))
		for carry := 0; carry < 2; carry++ {
			for a := 0; a < 256; a++ {
				for v := 0; v < 256; v++ {
					g.pc = 0x150
					g.a, g.b = uint8(a), uint8(v)
					g.f = 0
					if carry == 1 {
						g.f = FlagC
					}
					g.Step()
					wantR, wantF := refALU(op, uint8(a), uint8(v), carry == 1)
					if g.a != wantR || g.f != wantF {
						t.Fatalf("%s a=%02X v=%02X cin=%d: got A=%02X F=%02X want A=%02X F=%02X",
							names[op], a, v, carry, g.a, g.f, wantR, wantF)
					}
				}
			}
		}
	}
}

func TestIncDecFlags(t *testing.T) {
	inc := onlyOp(t, 0x04) // INC B
	dec := onlyOp(t, 0x05) // DEC B
	for v := 0; v < 256; v++ {
		for _, cin := range []uint8{0, FlagC} {
			inc.pc, inc.b, inc.f = 0x150, uint8(v), cin
			inc.Step()
			r := uint8(v + 1)
			want := flags(r == 0, false, v&15 == 15, false) | cin
			if inc.b != r || inc.f != want {
				t.Fatalf("inc %02X: got %02X/%02X want %02X/%02X", v, inc.b, inc.f, r, want)
			}
			dec.pc, dec.b, dec.f = 0x150, uint8(v), cin
			dec.Step()
			r = uint8(v - 1)
			want = flags(r == 0, true, v&15 == 0, false) | cin
			if dec.b != r || dec.f != want {
				t.Fatalf("dec %02X: got %02X/%02X want %02X/%02X", v, dec.b, dec.f, r, want)
			}
		}
	}
}

func bcd(n int) uint8 { return uint8(n/10<<4 | n%10) }

func TestDAAProperties(t *testing.T) {
	// ADD then DAA must equal decimal addition; same for ADC and SUB/SBC.
	g := onlyOp(t, 0x80, 0x27) // ADD A,B ; DAA
	gc := onlyOp(t, 0x88, 0x27)
	gs := onlyOp(t, 0x90, 0x27)
	gsc := onlyOp(t, 0x98, 0x27)
	for x := 0; x < 100; x++ {
		for y := 0; y < 100; y++ {
			g.pc, g.a, g.b, g.f = 0x150, bcd(x), bcd(y), 0
			stepN(t, g, 2)
			sum := x + y
			if g.a != bcd(sum%100) || (g.f&FlagC != 0) != (sum >= 100) || (g.f&FlagZ != 0) != (sum%100 == 0) || g.f&(FlagN|FlagH) != 0 {
				t.Fatalf("%d+%d: A=%02X F=%02X", x, y, g.a, g.f)
			}
			gc.pc, gc.a, gc.b, gc.f = 0x150, bcd(x), bcd(y), FlagC
			stepN(t, gc, 2)
			sum++
			if gc.a != bcd(sum%100) || (gc.f&FlagC != 0) != (sum >= 100) {
				t.Fatalf("%d+%d+1: A=%02X F=%02X", x, y, gc.a, gc.f)
			}
			gs.pc, gs.a, gs.b, gs.f = 0x150, bcd(x), bcd(y), 0
			stepN(t, gs, 2)
			d := x - y
			if d < 0 {
				d += 100
			}
			if gs.a != bcd(d) || (gs.f&FlagC != 0) != (x < y) || gs.f&FlagN == 0 || (gs.f&FlagZ != 0) != (d == 0) {
				t.Fatalf("%d-%d: A=%02X F=%02X", x, y, gs.a, gs.f)
			}
			gsc.pc, gsc.a, gsc.b, gsc.f = 0x150, bcd(x), bcd(y), FlagC
			stepN(t, gsc, 2)
			d = x - y - 1
			borrow := d < 0
			if d < 0 {
				d += 100
			}
			if gsc.a != bcd(d) || (gsc.f&FlagC != 0) != borrow {
				t.Fatalf("%d-%d-1: A=%02X F=%02X", x, y, gsc.a, gsc.f)
			}
		}
	}
}

func TestDAAKnownValues(t *testing.T) {
	// Values checked against the Pan Docs algorithm for non-BCD inputs.
	type tc struct{ a, f, wa, wf uint8 }
	cases := []tc{
		{0x0A, 0x00, 0x10, 0x00},
		{0x9A, 0x00, 0x00, FlagZ | FlagC},
		{0x00, FlagH, 0x06, 0x00},
		{0x00, FlagC, 0x60, FlagC},
		{0x66, FlagN | FlagH | FlagC, 0x00, FlagN | FlagC | FlagZ},
		{0x0F, FlagN | FlagH, 0x09, FlagN},
		{0xA0, FlagN, 0xA0, FlagN},
		{0xFF, FlagC | FlagH, 0x65, FlagC},
	}
	g := onlyOp(t, 0x27)
	for _, c := range cases {
		g.pc, g.a, g.f = 0x150, c.a, c.f
		g.Step()
		if g.a != c.wa || g.f != c.wf {
			t.Errorf("DAA a=%02X f=%02X: got %02X/%02X want %02X/%02X", c.a, c.f, g.a, g.f, c.wa, c.wf)
		}
	}
}

func TestCBExhaustive(t *testing.T) {
	ref := func(op int, v uint8, cin bool) (uint8, uint8) {
		var r uint8
		var c bool
		switch op {
		case 0:
			r, c = v<<1|v>>7, v&0x80 != 0
		case 1:
			r, c = v>>1|v<<7, v&1 != 0
		case 2:
			r, c = v<<1, v&0x80 != 0
			if cin {
				r |= 1
			}
		case 3:
			r, c = v>>1, v&1 != 0
			if cin {
				r |= 0x80
			}
		case 4:
			r, c = v<<1, v&0x80 != 0
		case 5:
			r, c = uint8(int8(v)>>1), v&1 != 0
		case 6:
			r, c = v>>4|v<<4, false
		case 7:
			r, c = v>>1, v&1 != 0
		}
		return r, flags(r == 0, false, false, c)
	}
	for op := 0; op < 8; op++ {
		g := onlyOp(t, 0xCB, byte(op<<3|0)) // op B
		for v := 0; v < 256; v++ {
			for _, cin := range []bool{false, true} {
				g.pc, g.b, g.f = 0x150, uint8(v), 0
				if cin {
					g.f = FlagC
				}
				g.f |= FlagN | FlagH // must be cleared
				g.Step()
				wr, wf := ref(op, uint8(v), cin)
				if g.b != wr || g.f != wf {
					t.Fatalf("cb op %d v=%02X cin=%v: got %02X/%02X want %02X/%02X", op, v, cin, g.b, g.f, wr, wf)
				}
			}
		}
	}
	// BIT / RES / SET on every register encoding incl. (HL)
	for bit := 0; bit < 8; bit++ {
		for z := 0; z < 8; z++ {
			for v := 0; v < 256; v += 5 {
				gb := onlyOp(t, 0xCB, byte(0x40|bit<<3|z))
				gr := onlyOp(t, 0xCB, byte(0x80|bit<<3|z))
				gs := onlyOp(t, 0xCB, byte(0xC0|bit<<3|z))
				for i, m := range []*GB{gb, gr, gs} {
					m.pc, m.f = 0x150, FlagC
					m.setHL(0xC123)
					m.setReg8(uint8(z), uint8(v))
					if z == 6 {
						m.write(0xC123, uint8(v))
					}
					m.Step()
					got := m.reg8(uint8(z))
					switch i {
					case 0:
						wantZ := v&(1<<bit) == 0
						if m.f != flags(wantZ, false, true, true) {
							t.Fatalf("bit %d,%d v=%02X F=%02X", bit, z, v, m.f)
						}
						if got != uint8(v) {
							t.Fatalf("BIT modified operand")
						}
					case 1:
						if got != uint8(v)&^(1<<bit) || m.f != FlagC {
							t.Fatalf("res %d,%d v=%02X got %02X F=%02X", bit, z, v, got, m.f)
						}
					case 2:
						if got != uint8(v)|1<<bit || m.f != FlagC {
							t.Fatalf("set %d,%d v=%02X got %02X F=%02X", bit, z, v, got, m.f)
						}
					}
				}
			}
		}
	}
}

func TestAccumulatorRotatesClearZ(t *testing.T) {
	// RLCA/RRCA/RLA/RRA always clear Z, unlike their CB forms.
	for i, op := range []byte{0x07, 0x0F, 0x17, 0x1F} {
		g := onlyOp(t, op)
		g.a, g.f = 0, FlagZ|FlagN|FlagH
		g.Step()
		if g.f != 0 {
			t.Errorf("op %02X (#%d): F=%02X, want 0", op, i, g.f)
		}
	}
	g := onlyOp(t, 0x17) // RLA
	g.a, g.f = 0x80, FlagC
	g.Step()
	if g.a != 1 || g.f != FlagC {
		t.Errorf("RLA: A=%02X F=%02X", g.a, g.f)
	}
}

func TestSixteenBit(t *testing.T) {
	// ADD HL,BC
	g := onlyOp(t, 0x09)
	for _, hl := range []uint16{0, 1, 0x0FFF, 0x1000, 0x7FFF, 0x8000, 0xFFFF, 0x1234} {
		for _, bc := range []uint16{0, 1, 0x0001, 0x0FFF, 0x8000, 0xFFFF, 0x4321} {
			g.pc, g.f = 0x150, FlagZ
			g.setHL(hl)
			g.setBC(bc)
			g.Step()
			sum := uint32(hl) + uint32(bc)
			want := flags(true, false, (hl&0xFFF)+(bc&0xFFF) > 0xFFF, sum > 0xFFFF)
			if g.hl() != uint16(sum) || g.f != want {
				t.Errorf("ADD HL,BC %04X+%04X: HL=%04X F=%02X want %04X/%02X", hl, bc, g.hl(), g.f, uint16(sum), want)
			}
		}
	}
	// ADD SP,e and LD HL,SP+e: flags from the low byte, Z and N cleared.
	for _, spv := range []uint16{0x0000, 0x000F, 0x00FF, 0x0100, 0xFFF8, 0xFFFF, 0x1234, 0x12F8} {
		for e := -128; e < 128; e++ {
			ga := onlyOp(t, 0xE8, byte(int8(e)))
			ga.pc, ga.sp, ga.f = 0x150, spv, FlagZ|FlagN
			ga.Step()
			gl := onlyOp(t, 0xF8, byte(int8(e)))
			gl.pc, gl.sp, gl.f = 0x150, spv, FlagZ|FlagN
			gl.Step()
			u := uint16(int16(e))
			want := flags(false, false, (spv&0xF)+(u&0xF) > 0xF, (spv&0xFF)+(u&0xFF) > 0xFF)
			if ga.sp != spv+u || ga.f != want || gl.hl() != spv+u || gl.f != want || gl.sp != spv {
				t.Fatalf("sp=%04X e=%d: add sp -> %04X/%02X; ld hl -> %04X/%02X; want %04X/%02X",
					spv, e, ga.sp, ga.f, gl.hl(), gl.f, spv+u, want)
			}
		}
	}
	// INC/DEC rr do not touch flags
	gi := onlyOp(t, 0x03, 0x0B)
	gi.f = 0xF0
	gi.setBC(0xFFFF)
	stepN(t, gi, 1)
	if gi.bc() != 0 || gi.f != 0xF0 {
		t.Errorf("INC BC wrap: %04X F=%02X", gi.bc(), gi.f)
	}
	stepN(t, gi, 1)
	if gi.bc() != 0xFFFF || gi.f != 0xF0 {
		t.Errorf("DEC BC wrap: %04X F=%02X", gi.bc(), gi.f)
	}
}

func TestMiscFlagOps(t *testing.T) {
	g := onlyOp(t, 0x2F) // CPL
	g.a, g.f = 0x35, FlagZ|FlagC
	g.Step()
	if g.a != 0xCA || g.f != FlagZ|FlagC|FlagN|FlagH {
		t.Errorf("CPL: %02X/%02X", g.a, g.f)
	}
	g = onlyOp(t, 0x37) // SCF
	g.f = FlagZ | FlagN | FlagH
	g.Step()
	if g.f != FlagZ|FlagC {
		t.Errorf("SCF: %02X", g.f)
	}
	g = onlyOp(t, 0x3F) // CCF
	g.f = FlagZ | FlagN | FlagH | FlagC
	g.Step()
	if g.f != FlagZ {
		t.Errorf("CCF set->clear: %02X", g.f)
	}
	g.pc = 0x150
	g.Step()
	if g.f != FlagZ|FlagC {
		t.Errorf("CCF clear->set: %02X", g.f)
	}
}

func TestPushPopAF(t *testing.T) {
	g := build(t, `
	ld sp, 0xDFF0
	ld bc, 0x12FF
	push bc
	pop af
	push af
	pop de
	halt
`)
	runUntilHalt(t, g, 10000)
	if g.a != 0x12 || g.f != 0xF0 || g.d != 0x12 || g.e != 0xF0 {
		t.Errorf("POP AF must mask F low nibble: A=%02X F=%02X DE=%04X", g.a, g.f, g.de())
	}
}

// Expected machine-cycle counts for a spread of instructions.
func TestInstructionCycles(t *testing.T) {
	type tc struct {
		bytes []byte
		m     int
		setup func(*GB)
	}
	taken := func(g *GB) { g.f = 0 } // Z,C clear
	notTaken := func(g *GB) { g.f = FlagZ | FlagC }
	cases := []tc{
		{[]byte{0x00}, 1, nil}, {[]byte{0x01, 1, 2}, 3, nil}, {[]byte{0x02}, 2, nil}, {[]byte{0x03}, 2, nil},
		{[]byte{0x04}, 1, nil}, {[]byte{0x06, 1}, 2, nil}, {[]byte{0x08, 0, 0xC0}, 5, nil}, {[]byte{0x09}, 2, nil},
		{[]byte{0x18, 0}, 3, nil}, {[]byte{0x20, 0}, 3, taken}, {[]byte{0x20, 0}, 2, notTaken},
		{[]byte{0x30, 0}, 3, taken}, {[]byte{0x38, 0}, 2, taken}, {[]byte{0x28, 0}, 2, taken},
		{[]byte{0x34}, 3, nil}, {[]byte{0x35}, 3, nil}, {[]byte{0x36, 1}, 3, nil},
		{[]byte{0x46}, 2, nil}, {[]byte{0x70}, 2, nil}, {[]byte{0x41}, 1, nil},
		{[]byte{0x86}, 2, nil}, {[]byte{0x80}, 1, nil}, {[]byte{0xBE}, 2, nil},
		{[]byte{0xC0}, 5, taken}, {[]byte{0xC0}, 2, notTaken}, {[]byte{0xC1}, 3, nil},
		{[]byte{0xC2, 0, 0}, 4, taken}, {[]byte{0xC2, 0, 0}, 3, notTaken}, {[]byte{0xC3, 0, 0}, 4, nil},
		{[]byte{0xC4, 0, 0xC0}, 6, taken}, {[]byte{0xC4, 0, 0}, 3, notTaken}, {[]byte{0xC5}, 4, nil},
		{[]byte{0xC6, 1}, 2, nil}, {[]byte{0xC7}, 4, nil}, {[]byte{0xC9}, 4, nil}, {[]byte{0xCD, 0, 0}, 6, nil},
		{[]byte{0xD9}, 4, nil}, {[]byte{0xE0, 0x80}, 3, nil}, {[]byte{0xE2}, 2, nil}, {[]byte{0xE8, 1}, 4, nil},
		{[]byte{0xE9}, 1, nil}, {[]byte{0xEA, 0, 0xC0}, 4, nil}, {[]byte{0xF0, 0x80}, 3, nil}, {[]byte{0xF8, 1}, 3, nil},
		{[]byte{0xF9}, 2, nil}, {[]byte{0xFA, 0, 0xC0}, 4, nil},
		{[]byte{0xCB, 0x00}, 2, nil}, {[]byte{0xCB, 0x06}, 4, nil}, {[]byte{0xCB, 0x46}, 3, nil},
		{[]byte{0xCB, 0x86}, 4, nil}, {[]byte{0xCB, 0xC6}, 4, nil}, {[]byte{0xCB, 0x47}, 2, nil},
		{[]byte{0x2A}, 2, nil}, {[]byte{0x22}, 2, nil}, {[]byte{0x76}, 1, nil}, {[]byte{0xF3}, 1, nil},
	}
	for i, c := range cases {
		g := onlyOp(t, c.bytes...)
		g.setHL(0xC000)
		g.sp = 0xDFF0
		if c.setup != nil {
			c.setup(g)
		}
		if m := g.cpuStep(); m != c.m {
			t.Errorf("case %d op % X: %d M-cycles, want %d", i, c.bytes, m, c.m)
		}
	}
}

func TestIllegalOpcodesLockUp(t *testing.T) {
	for _, op := range []byte{0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD} {
		g := onlyOp(t, op)
		g.Step()
		err := g.Err()
		ie, ok := err.(*ErrIllegal)
		if !ok || ie.Op != op || ie.PC != 0x150 {
			t.Errorf("op %02X: err=%v", op, err)
		}
		pc := g.pc
		g.Step()
		if g.pc != pc {
			t.Errorf("op %02X: CPU kept running after lock-up", op)
		}
	}
}

// Every one of the 244 defined base opcodes must be consumed with the right
// length (PC advance) when no jump is involved: cross-checked against the
// assembler's table.
func TestInstructionLengths(t *testing.T) {
	jumps := map[byte]bool{0x18: true, 0x20: true, 0x28: true, 0x30: true, 0x38: true, 0xC0: true, 0xC2: true, 0xC3: true,
		0xC4: true, 0xC7: true, 0xC8: true, 0xC9: true, 0xCA: true, 0xCC: true, 0xCD: true, 0xCF: true, 0xD0: true, 0xD2: true,
		0xD4: true, 0xD7: true, 0xD8: true, 0xD9: true, 0xDA: true, 0xDC: true, 0xDF: true, 0xE7: true, 0xE9: true, 0xEF: true,
		0xF7: true, 0xFF: true, 0x76: true, 0x10: true}
	for op := 0; op < 256; op++ {
		if jumps[byte(op)] || op == 0xCB {
			continue
		}
		g := onlyOp(t, byte(op), 0x01, 0xC0, 0, 0)
		g.sp = 0xDFF0
		g.setHL(0xC000)
		g.Step()
		if g.Err() != nil {
			continue // illegal opcode
		}
		want := instrLen[op]
		if int(g.pc-0x150) != want {
			t.Errorf("op %02X advanced PC by %d, want %d", op, g.pc-0x150, want)
		}
	}
	_ = fmt.Sprint
}

var instrLen = func() [256]int {
	var l [256]int
	for i := range l {
		l[i] = 1
	}
	for _, op := range []int{0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x36, 0x3E, 0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE, 0xE0, 0xF0, 0xE8, 0xF8} {
		l[op] = 2
	}
	for _, op := range []int{0x01, 0x11, 0x21, 0x31, 0x08, 0xEA, 0xFA} {
		l[op] = 3
	}
	return l
}()
