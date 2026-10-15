package asm

import "fmt"

// Disassemble decodes the instruction at pc using read to fetch bytes. It
// returns the text and the instruction length. Illegal opcodes decode as
// "db $XX" with length 1.
func Disassemble(read func(uint16) byte, pc uint16) (string, int) {
	op := read(pc)
	var t *Template
	b1 := read(pc + 1)
	if op == 0xCB {
		t = byOpcodeCB[b1]
	} else {
		t = byOpcode[op]
	}
	if t == nil {
		return fmt.Sprintf("db $%02X", op), 1
	}
	base := pc + 1
	if t.CB {
		base = pc + 2
	}
	vals := map[string]string{}
	for _, o := range t.Ops {
		switch o {
		case phD8:
			vals[o] = fmt.Sprintf("$%02X", read(base))
		case phA8:
			vals[o] = fmt.Sprintf("$FF%02X", read(base))
		case phD16, phA16, phJP16:
			vals[o] = fmt.Sprintf("$%04X", uint16(read(base))|uint16(read(base+1))<<8)
		case phE8:
			e := int8(read(base))
			if t.Mnemonic == "jr" {
				vals[o] = fmt.Sprintf("$%04X", pc+uint16(t.Size)+uint16(int16(e)))
			} else {
				vals[o] = fmt.Sprintf("%d", e)
			}
		case phSPE8:
			e := int8(read(base))
			if e < 0 {
				vals[o] = fmt.Sprintf("-%d", -int(e))
			} else {
				vals[o] = fmt.Sprintf("+%d", e)
			}
		}
	}
	return t.text(vals), t.Size
}

// DisassembleBytes disassembles a flat byte slice starting at origin.
func DisassembleBytes(data []byte, origin uint16) []Line {
	read := func(a uint16) byte {
		i := int(a) - int(origin)
		if i < 0 || i >= len(data) {
			return 0
		}
		return data[i]
	}
	var out []Line
	for pc := int(origin); pc < int(origin)+len(data); {
		txt, n := Disassemble(read, uint16(pc))
		out = append(out, Line{Addr: uint16(pc), Text: txt, Len: n})
		pc += n
	}
	return out
}

// Line is one disassembled instruction.
type Line struct {
	Addr uint16
	Text string
	Len  int
}
