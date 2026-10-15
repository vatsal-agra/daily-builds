package gb

import "fmt"

// Flag bits in F.
const (
	FlagZ = 0x80
	FlagN = 0x40
	FlagH = 0x20
	FlagC = 0x10
)

// CPU holds the SM83 register file and execution state.
type CPU struct {
	a, f, b, c, d, e, h, l uint8
	sp, pc                 uint16

	ime     bool
	imeNext bool // EI takes effect after the following instruction
	halted  bool
	haltBug bool
	stopped bool
	locked  bool // executed an illegal opcode
	lockOp  byte
	lockPC  uint16
}

// Regs is a snapshot of the register file.
type Regs struct {
	A, F, B, C, D, E, H, L uint8
	SP, PC                 uint16
	IME, Halted            bool
}

// Regs returns a copy of the registers.
func (c *CPU) Regs() Regs {
	return Regs{c.a, c.f, c.b, c.c, c.d, c.e, c.h, c.l, c.sp, c.pc, c.ime, c.halted}
}

// SetRegs overwrites the register file (used by tests and the debugger).
func (c *CPU) SetRegs(r Regs) {
	c.a, c.f, c.b, c.c, c.d, c.e, c.h, c.l = r.A, r.F&0xF0, r.B, r.C, r.D, r.E, r.H, r.L
	c.sp, c.pc, c.ime, c.halted = r.SP, r.PC, r.IME, r.Halted
}

func (r Regs) String() string {
	fl := []byte("----")
	if r.F&FlagZ != 0 {
		fl[0] = 'Z'
	}
	if r.F&FlagN != 0 {
		fl[1] = 'N'
	}
	if r.F&FlagH != 0 {
		fl[2] = 'H'
	}
	if r.F&FlagC != 0 {
		fl[3] = 'C'
	}
	return fmt.Sprintf("AF=%02X%02X BC=%02X%02X DE=%02X%02X HL=%02X%02X SP=%04X PC=%04X [%s]",
		r.A, r.F, r.B, r.C, r.D, r.E, r.H, r.L, r.SP, r.PC, fl)
}

func (c *CPU) af() uint16 { return uint16(c.a)<<8 | uint16(c.f) }
func (c *CPU) bc() uint16 { return uint16(c.b)<<8 | uint16(c.c) }
func (c *CPU) de() uint16 { return uint16(c.d)<<8 | uint16(c.e) }
func (c *CPU) hl() uint16 { return uint16(c.h)<<8 | uint16(c.l) }

func (c *CPU) setBC(v uint16) { c.b, c.c = uint8(v>>8), uint8(v) }
func (c *CPU) setDE(v uint16) { c.d, c.e = uint8(v>>8), uint8(v) }
func (c *CPU) setHL(v uint16) { c.h, c.l = uint8(v>>8), uint8(v) }
func (c *CPU) setAF(v uint16) { c.a, c.f = uint8(v>>8), uint8(v)&0xF0 }

func (c *CPU) flag(m uint8) bool { return c.f&m != 0 }
func (c *CPU) setFlag(m uint8, on bool) {
	if on {
		c.f |= m
	} else {
		c.f &^= m
	}
}

// ErrIllegal is returned when the CPU executes one of the 11 undefined opcodes.
type ErrIllegal struct {
	Op byte
	PC uint16
}

func (e *ErrIllegal) Error() string {
	return fmt.Sprintf("illegal opcode 0x%02X at %04X (CPU locked up)", e.Op, e.PC)
}

func (g *GB) fetch() byte {
	v := g.read(g.pc)
	if g.haltBug {
		g.haltBug = false
	} else {
		g.pc++
	}
	return v
}

func (g *GB) fetch16() uint16 {
	lo := uint16(g.fetch())
	hi := uint16(g.fetch())
	return hi<<8 | lo
}

func (g *GB) push16(v uint16) {
	g.sp--
	g.write(g.sp, uint8(v>>8))
	g.sp--
	g.write(g.sp, uint8(v))
}

func (g *GB) pop16() uint16 {
	lo := uint16(g.read(g.sp))
	g.sp++
	hi := uint16(g.read(g.sp))
	g.sp++
	return hi<<8 | lo
}

// reg8 reads register index r (B C D E H L (HL) A).
func (g *GB) reg8(r uint8) uint8 {
	switch r {
	case 0:
		return g.b
	case 1:
		return g.c
	case 2:
		return g.d
	case 3:
		return g.e
	case 4:
		return g.h
	case 5:
		return g.l
	case 6:
		return g.read(g.hl())
	}
	return g.a
}

func (g *GB) setReg8(r uint8, v uint8) {
	switch r {
	case 0:
		g.b = v
	case 1:
		g.c = v
	case 2:
		g.d = v
	case 3:
		g.e = v
	case 4:
		g.h = v
	case 5:
		g.l = v
	case 6:
		g.write(g.hl(), v)
	default:
		g.a = v
	}
}

func (g *GB) rp(p uint8) uint16 {
	switch p {
	case 0:
		return g.bc()
	case 1:
		return g.de()
	case 2:
		return g.hl()
	}
	return g.sp
}

func (g *GB) setRP(p uint8, v uint16) {
	switch p {
	case 0:
		g.setBC(v)
	case 1:
		g.setDE(v)
	case 2:
		g.setHL(v)
	default:
		g.sp = v
	}
}

func (g *GB) cond(cc uint8) bool {
	switch cc {
	case 0:
		return !g.flag(FlagZ)
	case 1:
		return g.flag(FlagZ)
	case 2:
		return !g.flag(FlagC)
	}
	return g.flag(FlagC)
}

// ---- ALU --------------------------------------------------------------

func (g *GB) alu(op uint8, v uint8) {
	a := g.a
	switch op {
	case 0: // ADD
		r := uint16(a) + uint16(v)
		g.f = 0
		g.setFlag(FlagH, (a&0xF)+(v&0xF) > 0xF)
		g.setFlag(FlagC, r > 0xFF)
		g.a = uint8(r)
		g.setFlag(FlagZ, g.a == 0)
	case 1: // ADC
		cy := uint16(0)
		if g.flag(FlagC) {
			cy = 1
		}
		r := uint16(a) + uint16(v) + cy
		g.f = 0
		g.setFlag(FlagH, uint16(a&0xF)+uint16(v&0xF)+cy > 0xF)
		g.setFlag(FlagC, r > 0xFF)
		g.a = uint8(r)
		g.setFlag(FlagZ, g.a == 0)
	case 2, 7: // SUB, CP
		r := int(a) - int(v)
		g.f = FlagN
		g.setFlag(FlagH, int(a&0xF)-int(v&0xF) < 0)
		g.setFlag(FlagC, r < 0)
		g.setFlag(FlagZ, uint8(r) == 0)
		if op == 2 {
			g.a = uint8(r)
		}
	case 3: // SBC
		cy := 0
		if g.flag(FlagC) {
			cy = 1
		}
		r := int(a) - int(v) - cy
		g.f = FlagN
		g.setFlag(FlagH, int(a&0xF)-int(v&0xF)-cy < 0)
		g.setFlag(FlagC, r < 0)
		g.a = uint8(r)
		g.setFlag(FlagZ, g.a == 0)
	case 4: // AND
		g.a = a & v
		g.f = FlagH
		g.setFlag(FlagZ, g.a == 0)
	case 5: // XOR
		g.a = a ^ v
		g.f = 0
		g.setFlag(FlagZ, g.a == 0)
	case 6: // OR
		g.a = a | v
		g.f = 0
		g.setFlag(FlagZ, g.a == 0)
	}
}

func (g *GB) inc8(v uint8) uint8 {
	r := v + 1
	g.setFlag(FlagZ, r == 0)
	g.setFlag(FlagN, false)
	g.setFlag(FlagH, v&0xF == 0xF)
	return r
}

func (g *GB) dec8(v uint8) uint8 {
	r := v - 1
	g.setFlag(FlagZ, r == 0)
	g.setFlag(FlagN, true)
	g.setFlag(FlagH, v&0xF == 0)
	return r
}

func (g *GB) addHL(v uint16) {
	hl := g.hl()
	r := uint32(hl) + uint32(v)
	g.setFlag(FlagN, false)
	g.setFlag(FlagH, (hl&0xFFF)+(v&0xFFF) > 0xFFF)
	g.setFlag(FlagC, r > 0xFFFF)
	g.setHL(uint16(r))
}

// spPlus computes SP+e and sets the flags shared by ADD SP,e and LD HL,SP+e.
func (g *GB) spPlus(e int8) uint16 {
	sp := g.sp
	u := uint16(int16(e))
	g.f = 0
	g.setFlag(FlagH, (sp&0xF)+(u&0xF) > 0xF)
	g.setFlag(FlagC, (sp&0xFF)+(u&0xFF) > 0xFF)
	return sp + u
}

func (g *GB) daa() {
	a := uint16(g.a)
	if !g.flag(FlagN) {
		if g.flag(FlagC) || a > 0x99 {
			a += 0x60
			g.setFlag(FlagC, true)
		}
		if g.flag(FlagH) || a&0xF > 9 {
			a += 6
		}
	} else {
		if g.flag(FlagC) {
			a -= 0x60
		}
		if g.flag(FlagH) {
			a -= 6
		}
	}
	g.a = uint8(a)
	g.setFlag(FlagZ, g.a == 0)
	g.setFlag(FlagH, false)
}

// ---- rotates / shifts (CB group) --------------------------------------

func (g *GB) cbOp(op uint8, v uint8) uint8 {
	var r uint8
	var cy bool
	oldC := g.flag(FlagC)
	switch op {
	case 0: // RLC
		cy = v&0x80 != 0
		r = v<<1 | v>>7
	case 1: // RRC
		cy = v&1 != 0
		r = v>>1 | v<<7
	case 2: // RL
		cy = v&0x80 != 0
		r = v << 1
		if oldC {
			r |= 1
		}
	case 3: // RR
		cy = v&1 != 0
		r = v >> 1
		if oldC {
			r |= 0x80
		}
	case 4: // SLA
		cy = v&0x80 != 0
		r = v << 1
	case 5: // SRA
		cy = v&1 != 0
		r = v>>1 | v&0x80
	case 6: // SWAP
		r = v<<4 | v>>4
	case 7: // SRL
		cy = v&1 != 0
		r = v >> 1
	}
	g.f = 0
	g.setFlag(FlagZ, r == 0)
	g.setFlag(FlagC, cy)
	return r
}

// ---- stepping ---------------------------------------------------------

// cpuStep executes one unit of CPU work and returns M-cycles consumed.
func (g *GB) cpuStep() int {
	if g.locked {
		return 1
	}
	pending := g.ifl & g.ie & 0x1F
	if g.halted {
		if pending == 0 {
			return 1
		}
		g.halted = false
	}
	if g.ime && pending != 0 {
		g.ime = false
		g.imeNext = false
		for i := uint(0); i < 5; i++ {
			if pending&(1<<i) != 0 {
				g.ifl &^= 1 << i
				g.push16(g.pc)
				g.pc = 0x40 + uint16(i)*8
				return 5
			}
		}
	}
	enable := g.imeNext
	m := g.exec()
	if enable && g.imeNext {
		g.ime = true
		g.imeNext = false
	}
	return m
}

func (g *GB) illegal(op byte, pc uint16) int {
	g.locked, g.lockOp, g.lockPC = true, op, pc
	return 1
}

// exec fetches and executes one instruction, returning M-cycles.
func (g *GB) exec() int {
	startPC := g.pc
	op := g.fetch()
	x, y, z := op>>6, (op>>3)&7, op&7
	p, q := y>>1, y&1

	switch x {
	case 0:
		switch z {
		case 0:
			switch y {
			case 0:
				return 1
			case 1:
				a := g.fetch16()
				g.write(a, uint8(g.sp))
				g.write(a+1, uint8(g.sp>>8))
				return 5
			case 2: // STOP (2 bytes; we treat as a NOP-like idle, no speed switch on DMG)
				g.fetch()
				g.stopped = true
				return 1
			case 3:
				e := int8(g.fetch())
				g.pc += uint16(int16(e))
				return 3
			default:
				e := int8(g.fetch())
				if g.cond(y - 4) {
					g.pc += uint16(int16(e))
					return 3
				}
				return 2
			}
		case 1:
			if q == 0 {
				g.setRP(p, g.fetch16())
				return 3
			}
			g.addHL(g.rp(p))
			return 2
		case 2:
			var addr uint16
			switch p {
			case 0:
				addr = g.bc()
			case 1:
				addr = g.de()
			case 2:
				addr = g.hl()
				g.setHL(addr + 1)
			default:
				addr = g.hl()
				g.setHL(addr - 1)
			}
			if q == 0 {
				g.write(addr, g.a)
			} else {
				g.a = g.read(addr)
			}
			return 2
		case 3:
			if q == 0 {
				g.setRP(p, g.rp(p)+1)
			} else {
				g.setRP(p, g.rp(p)-1)
			}
			return 2
		case 4:
			g.setReg8(y, g.inc8(g.reg8(y)))
			if y == 6 {
				return 3
			}
			return 1
		case 5:
			g.setReg8(y, g.dec8(g.reg8(y)))
			if y == 6 {
				return 3
			}
			return 1
		case 6:
			g.setReg8(y, g.fetch())
			if y == 6 {
				return 3
			}
			return 2
		case 7:
			switch y {
			case 0: // RLCA
				g.a = g.cbOp(0, g.a)
				g.f &^= FlagZ
			case 1:
				g.a = g.cbOp(1, g.a)
				g.f &^= FlagZ
			case 2:
				g.a = g.cbOp(2, g.a)
				g.f &^= FlagZ
			case 3:
				g.a = g.cbOp(3, g.a)
				g.f &^= FlagZ
			case 4:
				g.daa()
			case 5: // CPL
				g.a = ^g.a
				g.setFlag(FlagN, true)
				g.setFlag(FlagH, true)
			case 6: // SCF
				g.setFlag(FlagN, false)
				g.setFlag(FlagH, false)
				g.setFlag(FlagC, true)
			case 7: // CCF
				g.setFlag(FlagN, false)
				g.setFlag(FlagH, false)
				g.setFlag(FlagC, !g.flag(FlagC))
			}
			return 1
		}
	case 1:
		if y == 6 && z == 6 { // HALT
			if !g.ime && g.ifl&g.ie&0x1F != 0 {
				g.haltBug = true // next opcode byte is fetched twice
			} else {
				g.halted = true
			}
			return 1
		}
		g.setReg8(y, g.reg8(z))
		if y == 6 || z == 6 {
			return 2
		}
		return 1
	case 2:
		g.alu(y, g.reg8(z))
		if z == 6 {
			return 2
		}
		return 1
	case 3:
		switch z {
		case 0:
			switch {
			case y < 4:
				if g.cond(y) {
					g.pc = g.pop16()
					return 5
				}
				return 2
			case y == 4:
				g.write(0xFF00|uint16(g.fetch()), g.a)
				return 3
			case y == 5:
				e := int8(g.fetch())
				g.sp = g.spPlus(e)
				return 4
			case y == 6:
				g.a = g.read(0xFF00 | uint16(g.fetch()))
				return 3
			default:
				e := int8(g.fetch())
				g.setHL(g.spPlus(e))
				return 3
			}
		case 1:
			if q == 0 {
				v := g.pop16()
				switch p {
				case 0:
					g.setBC(v)
				case 1:
					g.setDE(v)
				case 2:
					g.setHL(v)
				default:
					g.setAF(v)
				}
				return 3
			}
			switch p {
			case 0:
				g.pc = g.pop16()
				return 4
			case 1: // RETI
				g.pc = g.pop16()
				g.ime = true
				return 4
			case 2:
				g.pc = g.hl()
				return 1
			default:
				g.sp = g.hl()
				return 2
			}
		case 2:
			switch {
			case y < 4:
				a := g.fetch16()
				if g.cond(y) {
					g.pc = a
					return 4
				}
				return 3
			case y == 4:
				g.write(0xFF00|uint16(g.c), g.a)
				return 2
			case y == 5:
				g.write(g.fetch16(), g.a)
				return 4
			case y == 6:
				g.a = g.read(0xFF00 | uint16(g.c))
				return 2
			default:
				g.a = g.read(g.fetch16())
				return 4
			}
		case 3:
			switch y {
			case 0:
				g.pc = g.fetch16()
				return 4
			case 1:
				return g.execCB()
			case 6: // DI
				g.ime = false
				g.imeNext = false
				return 1
			case 7: // EI
				g.imeNext = true
				return 1
			}
			return g.illegal(op, startPC)
		case 4:
			if y < 4 {
				a := g.fetch16()
				if g.cond(y) {
					g.push16(g.pc)
					g.pc = a
					return 6
				}
				return 3
			}
			return g.illegal(op, startPC)
		case 5:
			if q == 0 {
				var v uint16
				switch p {
				case 0:
					v = g.bc()
				case 1:
					v = g.de()
				case 2:
					v = g.hl()
				default:
					v = g.af()
				}
				g.push16(v)
				return 4
			}
			if p == 0 {
				a := g.fetch16()
				g.push16(g.pc)
				g.pc = a
				return 6
			}
			return g.illegal(op, startPC)
		case 6:
			g.alu(y, g.fetch())
			return 2
		case 7:
			g.push16(g.pc)
			g.pc = uint16(y) * 8
			return 4
		}
	}
	return g.illegal(op, startPC)
}

func (g *GB) execCB() int {
	op := g.fetch()
	x, y, z := op>>6, (op>>3)&7, op&7
	switch x {
	case 0:
		g.setReg8(z, g.cbOp(y, g.reg8(z)))
		if z == 6 {
			return 4
		}
		return 2
	case 1: // BIT
		v := g.reg8(z)
		g.setFlag(FlagZ, v&(1<<y) == 0)
		g.setFlag(FlagN, false)
		g.setFlag(FlagH, true)
		if z == 6 {
			return 3
		}
		return 2
	case 2: // RES
		g.setReg8(z, g.reg8(z)&^(1<<y))
	default: // SET
		g.setReg8(z, g.reg8(z)|(1<<y))
	}
	if z == 6 {
		return 4
	}
	return 2
}

// Err returns the lock-up error if the CPU executed an illegal opcode.
func (g *GB) Err() error {
	if g.locked {
		return &ErrIllegal{g.lockOp, g.lockPC}
	}
	return nil
}
