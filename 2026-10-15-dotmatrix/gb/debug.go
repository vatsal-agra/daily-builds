package gb

import (
	"fmt"
	"strconv"
	"strings"

	"dotmatrix/asm"
)

// Condition is a conjunction of simple comparisons evaluated against machine
// state, e.g. "a == 0x10 && [0xC000] != 0".
type Condition struct {
	src   string
	terms []condTerm
}

type condTerm struct {
	reg  string // register name, or "" when mem is used
	mem  int    // memory address when reg == ""
	op   string
	want int
}

var condOps = []string{"==", "!=", "<=", ">=", "<", ">"}

// ParseCondition compiles a condition string. Values accept 0x / $ hex or decimal.
func ParseCondition(s string) (*Condition, error) {
	c := &Condition{src: s}
	for _, part := range strings.Split(s, "&&") {
		part = strings.TrimSpace(part)
		var op string
		idx := -1
		for _, o := range condOps {
			if i := strings.Index(part, o); i >= 0 && (idx < 0 || i < idx) {
				op, idx = o, i
			}
		}
		if idx < 0 {
			return nil, fmt.Errorf("condition %q: expected a comparison like a==5", part)
		}
		lhs := strings.ToLower(strings.TrimSpace(part[:idx]))
		rhs := strings.TrimSpace(part[idx+len(op):])
		want, err := parseNum(rhs)
		if err != nil {
			return nil, fmt.Errorf("condition %q: bad value %q", part, rhs)
		}
		t := condTerm{op: op, want: want}
		if strings.HasPrefix(lhs, "[") && strings.HasSuffix(lhs, "]") {
			a, err := parseNum(lhs[1 : len(lhs)-1])
			if err != nil || a < 0 || a > 0xFFFF {
				return nil, fmt.Errorf("condition %q: bad address %q", part, lhs)
			}
			t.mem = a
		} else {
			switch lhs {
			case "a", "f", "b", "c", "d", "e", "h", "l", "af", "bc", "de", "hl", "sp", "pc":
				t.reg = lhs
			default:
				return nil, fmt.Errorf("condition %q: unknown register %q", part, lhs)
			}
		}
		c.terms = append(c.terms, t)
	}
	return c, nil
}

func parseNum(s string) (int, error) {
	s = strings.TrimSpace(s)
	neg := false
	if strings.HasPrefix(s, "-") {
		neg, s = true, s[1:]
	}
	base := 10
	switch {
	case strings.HasPrefix(s, "0x") || strings.HasPrefix(s, "0X"):
		s, base = s[2:], 16
	case strings.HasPrefix(s, "$"):
		s, base = s[1:], 16
	}
	v, err := strconv.ParseInt(s, base, 32)
	if neg {
		v = -v
	}
	return int(v), err
}

func (c *Condition) String() string { return c.src }

// Eval reports whether the condition holds on g.
func (c *Condition) Eval(g *GB) bool {
	for _, t := range c.terms {
		var have int
		if t.reg == "" {
			have = int(g.peek(uint16(t.mem)))
		} else {
			have = int(g.RegByName(t.reg))
		}
		ok := false
		switch t.op {
		case "==":
			ok = have == t.want
		case "!=":
			ok = have != t.want
		case "<":
			ok = have < t.want
		case ">":
			ok = have > t.want
		case "<=":
			ok = have <= t.want
		case ">=":
			ok = have >= t.want
		}
		if !ok {
			return false
		}
	}
	return true
}

// RegByName reads a register (8- or 16-bit) by lower-case name.
func (g *GB) RegByName(n string) uint16 {
	switch n {
	case "a":
		return uint16(g.a)
	case "f":
		return uint16(g.f)
	case "b":
		return uint16(g.b)
	case "c":
		return uint16(g.c)
	case "d":
		return uint16(g.d)
	case "e":
		return uint16(g.e)
	case "h":
		return uint16(g.h)
	case "l":
		return uint16(g.l)
	case "af":
		return g.af()
	case "bc":
		return g.bc()
	case "de":
		return g.de()
	case "hl":
		return g.hl()
	case "sp":
		return g.sp
	case "pc":
		return g.pc
	}
	return 0
}

// SetReg writes a register by name. 8-bit values must fit in a byte.
func (g *GB) SetReg(n string, v int) error {
	if v < 0 || v > 0xFFFF {
		return fmt.Errorf("value %d out of range", v)
	}
	b := func() error {
		if v > 0xFF {
			return fmt.Errorf("register %s is 8-bit; %d does not fit", n, v)
		}
		return nil
	}
	switch n {
	case "a", "b", "c", "d", "e", "h", "l", "f":
		if err := b(); err != nil {
			return err
		}
	}
	switch n {
	case "a":
		g.a = uint8(v)
	case "f":
		g.f = uint8(v) & 0xF0
	case "b":
		g.b = uint8(v)
	case "c":
		g.c = uint8(v)
	case "d":
		g.d = uint8(v)
	case "e":
		g.e = uint8(v)
	case "h":
		g.h = uint8(v)
	case "l":
		g.l = uint8(v)
	case "af":
		g.setAF(uint16(v))
	case "bc":
		g.setBC(uint16(v))
	case "de":
		g.setDE(uint16(v))
	case "hl":
		g.setHL(uint16(v))
	case "sp":
		g.sp = uint16(v)
	case "pc":
		g.pc = uint16(v)
	default:
		return fmt.Errorf("unknown register %q", n)
	}
	return nil
}

// Breakpoint stops execution when PC reaches Addr (and Cond, if any, holds).
type Breakpoint struct {
	ID   int
	Addr uint16
	Cond *Condition
	Hits int
}

// WatchKind selects which accesses a watchpoint reacts to.
type WatchKind int

const (
	WatchWrite WatchKind = 1 << iota
	WatchRead
)

// Watchpoint stops execution on a memory access.
type Watchpoint struct {
	ID   int
	Addr uint16
	Kind WatchKind
	Hits int
}

// Debugger holds breakpoints, watchpoints and a ring of recently executed PCs.
type Debugger struct {
	Breaks  []*Breakpoint
	Watches []*Watchpoint
	nextID  int

	history [256]uint16
	histN   int

	skipBreak bool // do not re-trigger the breakpoint we are sitting on
	hit       *StopError
}

// NewDebugger creates an empty debugger.
func NewDebugger() *Debugger { return &Debugger{nextID: 1} }

// AddBreak registers a breakpoint and returns it.
func (d *Debugger) AddBreak(addr uint16, cond *Condition) *Breakpoint {
	b := &Breakpoint{ID: d.nextID, Addr: addr, Cond: cond}
	d.nextID++
	d.Breaks = append(d.Breaks, b)
	return b
}

// AddWatch registers a watchpoint and returns it.
func (d *Debugger) AddWatch(addr uint16, kind WatchKind) *Watchpoint {
	w := &Watchpoint{ID: d.nextID, Addr: addr, Kind: kind}
	d.nextID++
	d.Watches = append(d.Watches, w)
	return w
}

// Delete removes the breakpoint or watchpoint with the given ID.
func (d *Debugger) Delete(id int) bool {
	for i, b := range d.Breaks {
		if b.ID == id {
			d.Breaks = append(d.Breaks[:i], d.Breaks[i+1:]...)
			return true
		}
	}
	for i, w := range d.Watches {
		if w.ID == id {
			d.Watches = append(d.Watches[:i], d.Watches[i+1:]...)
			return true
		}
	}
	return false
}

// History returns up to n most recently executed instruction addresses, oldest first.
func (d *Debugger) History(n int) []uint16 {
	if n > len(d.history) {
		n = len(d.history)
	}
	if n > d.histN {
		n = d.histN
	}
	out := make([]uint16, n)
	for i := 0; i < n; i++ {
		out[i] = d.history[(d.histN-n+i)&255]
	}
	return out
}

// StopError is returned by StepChecked when the debugger halts execution.
type StopError struct {
	Kind string // "breakpoint", "watchpoint"
	Addr uint16
	Msg  string
}

func (e *StopError) Error() string { return e.Msg }

func (d *Debugger) noteWrite(g *GB, addr uint16, v byte) {
	for _, w := range d.Watches {
		if w.Kind&WatchWrite != 0 && w.Addr == addr && d.hit == nil {
			w.Hits++
			d.hit = &StopError{"watchpoint", addr, fmt.Sprintf("watchpoint %d: write %02X -> [%04X] (was %02X)", w.ID, v, addr, g.peek(addr))}
		}
	}
}

func (d *Debugger) noteRead(g *GB, addr uint16) {
	for _, w := range d.Watches {
		if w.Kind&WatchRead != 0 && w.Addr == addr && d.hit == nil {
			w.Hits++
			d.hit = &StopError{"watchpoint", addr, fmt.Sprintf("watchpoint %d: read [%04X] = %02X", w.ID, addr, g.peek(addr))}
		}
	}
}

// StepChecked executes one step like Step, but honours the debugger (when
// attached) and reports CPU lock-ups. A breakpoint at the current PC fires
// *before* the instruction runs.
func (g *GB) StepChecked() error {
	if g.locked {
		return g.Err()
	}
	if d := g.Dbg; d != nil {
		if !d.skipBreak {
			for _, b := range d.Breaks {
				if b.Addr == g.pc && !g.halted && (b.Cond == nil || b.Cond.Eval(g)) {
					b.Hits++
					return &StopError{"breakpoint", g.pc, fmt.Sprintf("breakpoint %d at %04X", b.ID, g.pc)}
				}
			}
		}
		d.skipBreak = false
		d.history[d.histN&255] = g.pc
		d.histN++
		d.hit = nil
	}
	g.Step()
	if d := g.Dbg; d != nil {
		d.skipBreak = true // resuming from a stop must not re-trigger at the same PC
		if d.hit != nil {
			h := d.hit
			d.hit = nil
			return h
		}
		d.skipBreak = false
	}
	return g.Err()
}

// ResumeFromStop tells the debugger the next StepChecked is a deliberate
// resume, so a breakpoint at the current PC is skipped once.
func (d *Debugger) ResumeFromStop() { d.skipBreak = true }

// TraceLine formats the next instruction with registers, bgb-style.
func (g *GB) TraceLine() string {
	r := g.Regs()
	txt, _ := asm.Disassemble(g.peek, r.PC)
	return fmt.Sprintf("%s  LY=%03d  %04X: %s", r, g.PPU.ly, r.PC, txt)
}
