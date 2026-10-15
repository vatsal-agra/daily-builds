package gb

import (
	"fmt"

	"dotmatrix/asm"
)

// Debugger holds breakpoints and watchpoints.
type Debugger struct {
	Breaks  map[uint16]bool
	hitAddr uint16
	hitKind string
}

// StopError is returned by StepChecked when the debugger halts execution.
type StopError struct {
	Kind string
	Addr uint16
}

func (e *StopError) Error() string { return e.Kind }

func (d *Debugger) noteWrite(addr uint16, v byte) {}

// StepChecked is Step plus lock-up and breakpoint detection.
func (g *GB) StepChecked() error {
	if g.locked {
		return g.Err()
	}
	g.Step()
	return g.Err()
}

// TraceLine formats the next instruction with registers, bgb-style.
func (g *GB) TraceLine() string {
	r := g.Regs()
	txt, _ := asm.Disassemble(g.peek, r.PC)
	return fmt.Sprintf("%s  LY=%03d  %04X: %s", r, g.PPU.ly, r.PC, txt)
}
