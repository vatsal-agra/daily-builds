// Package asm implements an assembler and disassembler for the Sharp SM83
// (Game Boy CPU). Both directions are driven by one generated opcode table,
// so assemble -> disassemble round-trips by construction.
package asm

import (
	"fmt"
	"strings"
)

// Operand placeholder kinds appearing in templates.
const (
	phNone = ""
	phD8   = "d8"
	phD16  = "d16"
	phA8   = "[a8]"
	phA16  = "[a16]"
	phJP16 = "a16"
	phE8   = "e8"
	phSPE8 = "sp+e8"
)

// Template is one instruction form: mnemonic plus operand patterns.
type Template struct {
	Mnemonic string
	Ops      []string // literal operand text (lowercase) or a placeholder
	Opcode   byte
	CB       bool
	Implicit byte // extra constant byte after the opcode (STOP's 00), if HasImp
	HasImp   bool
	Size     int // total bytes
}

var (
	reg8   = []string{"b", "c", "d", "e", "h", "l", "[hl]", "a"}
	rpTab  = []string{"bc", "de", "hl", "sp"}
	rp2Tab = []string{"bc", "de", "hl", "af"}
	ccTab  = []string{"nz", "z", "nc", "c"}
	aluTab = []string{"add", "adc", "sub", "sbc", "and", "xor", "or", "cp"}
	rotTab = []string{"rlc", "rrc", "rl", "rr", "sla", "sra", "swap", "srl"}
)

// Templates lists every defined instruction form (244 base + 256 CB).
var Templates []Template

// byOpcode / byOpcodeCB map an opcode to its template (nil for illegal).
var byOpcode [256]*Template
var byOpcodeCB [256]*Template

// byMnemonic indexes templates for the assembler.
var byMnemonic = map[string][]*Template{}

func add(op byte, cb bool, mn string, ops ...string) {
	t := Template{Mnemonic: mn, Ops: ops, Opcode: op, CB: cb}
	t.Size = 1
	if cb {
		t.Size = 2
	}
	for _, o := range ops {
		switch o {
		case phD8, phE8, phA8, phSPE8:
			t.Size++
		case phD16, phA16, phJP16:
			t.Size += 2
		}
	}
	if mn == "stop" {
		t.HasImp, t.Implicit, t.Size = true, 0, 2
	}
	Templates = append(Templates, t)
}

func init() {
	for op := 0; op < 256; op++ {
		x, y, z := op>>6, (op>>3)&7, op&7
		p, q := y>>1, y&1
		o := byte(op)
		switch x {
		case 0:
			switch z {
			case 0:
				switch {
				case y == 0:
					add(o, false, "nop")
				case y == 1:
					add(o, false, "ld", phA16, "sp")
				case y == 2:
					add(o, false, "stop")
				case y == 3:
					add(o, false, "jr", phE8)
				default:
					add(o, false, "jr", ccTab[y-4], phE8)
				}
			case 1:
				if q == 0 {
					add(o, false, "ld", rpTab[p], phD16)
				} else {
					add(o, false, "add", "hl", rpTab[p])
				}
			case 2:
				ind := []string{"[bc]", "[de]", "[hl+]", "[hl-]"}[p]
				if q == 0 {
					add(o, false, "ld", ind, "a")
				} else {
					add(o, false, "ld", "a", ind)
				}
			case 3:
				if q == 0 {
					add(o, false, "inc", rpTab[p])
				} else {
					add(o, false, "dec", rpTab[p])
				}
			case 4:
				add(o, false, "inc", reg8[y])
			case 5:
				add(o, false, "dec", reg8[y])
			case 6:
				add(o, false, "ld", reg8[y], phD8)
			case 7:
				add(o, false, []string{"rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf"}[y])
			}
		case 1:
			if y == 6 && z == 6 {
				add(o, false, "halt")
			} else {
				add(o, false, "ld", reg8[y], reg8[z])
			}
		case 2:
			if y == 0 || y == 1 || y == 3 {
				add(o, false, aluTab[y], "a", reg8[z])
			} else {
				add(o, false, aluTab[y], reg8[z])
			}
		case 3:
			switch z {
			case 0:
				switch {
				case y < 4:
					add(o, false, "ret", ccTab[y])
				case y == 4:
					add(o, false, "ldh", phA8, "a")
				case y == 5:
					add(o, false, "add", "sp", phE8)
				case y == 6:
					add(o, false, "ldh", "a", phA8)
				default:
					add(o, false, "ld", "hl", phSPE8)
				}
			case 1:
				if q == 0 {
					add(o, false, "pop", rp2Tab[p])
				} else {
					switch p {
					case 0:
						add(o, false, "ret")
					case 1:
						add(o, false, "reti")
					case 2:
						add(o, false, "jp", "hl")
					default:
						add(o, false, "ld", "sp", "hl")
					}
				}
			case 2:
				switch {
				case y < 4:
					add(o, false, "jp", ccTab[y], phJP16)
				case y == 4:
					add(o, false, "ld", "[c]", "a")
				case y == 5:
					add(o, false, "ld", phA16, "a")
				case y == 6:
					add(o, false, "ld", "a", "[c]")
				default:
					add(o, false, "ld", "a", phA16)
				}
			case 3:
				switch y {
				case 0:
					add(o, false, "jp", phJP16)
				case 6:
					add(o, false, "di")
				case 7:
					add(o, false, "ei")
				}
			case 4:
				if y < 4 {
					add(o, false, "call", ccTab[y], phJP16)
				}
			case 5:
				if q == 0 {
					add(o, false, "push", rp2Tab[p])
				} else if p == 0 {
					add(o, false, "call", phJP16)
				}
			case 6:
				if y == 0 || y == 1 || y == 3 {
					add(o, false, aluTab[y], "a", phD8)
				} else {
					add(o, false, aluTab[y], phD8)
				}
			case 7:
				add(o, false, "rst", fmt.Sprintf("$%02X", y*8))
			}
		}
	}
	for op := 0; op < 256; op++ {
		x, y, z := op>>6, (op>>3)&7, op&7
		o := byte(op)
		switch x {
		case 0:
			add(o, true, rotTab[y], reg8[z])
		case 1:
			add(o, true, "bit", fmt.Sprintf("%d", y), reg8[z])
		case 2:
			add(o, true, "res", fmt.Sprintf("%d", y), reg8[z])
		default:
			add(o, true, "set", fmt.Sprintf("%d", y), reg8[z])
		}
	}
	for i := range Templates {
		t := &Templates[i]
		if t.CB {
			byOpcodeCB[t.Opcode] = t
		} else {
			byOpcode[t.Opcode] = t
		}
		byMnemonic[t.Mnemonic] = append(byMnemonic[t.Mnemonic], t)
	}
	// STOP is followed by a padding byte that is normally 00; "stop $xx" keeps
	// other values lossless. Only the assembler uses this form.
	byMnemonic["stop"] = append(byMnemonic["stop"], &Template{Mnemonic: "stop", Ops: []string{phD8}, Opcode: 0x10, Size: 2})
}

// Text renders a template with the given operand strings substituted for
// placeholders (used by the disassembler).
func (t *Template) text(vals map[string]string) string {
	if len(t.Ops) == 0 {
		return t.Mnemonic
	}
	parts := make([]string, len(t.Ops))
	for i, o := range t.Ops {
		switch o {
		case phD8, phD16, phJP16, phE8:
			parts[i] = vals[o]
		case phA8, phA16:
			parts[i] = "[" + vals[o] + "]"
		case phSPE8:
			parts[i] = "sp" + vals[o]
		default:
			parts[i] = o
		}
	}
	return t.Mnemonic + " " + strings.Join(parts, ", ")
}
