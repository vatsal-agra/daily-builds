package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"dotmatrix/asm"
	"dotmatrix/gb"
)

const debugHelp = `commands:
  s [n]            step n instructions (default 1)
  n                step over CALL/RST
  c [frames]       continue until a breakpoint/watchpoint (default cap: 600 frames)
  f [n]            run n frames
  finish           run until the current subroutine returns
  until ADDR       run until PC == ADDR
  b ADDR [if COND] set a breakpoint (ADDR: number, label, label+N); COND e.g. "a==0x10 && [0xC000]!=0"
  w ADDR           break when ADDR is written       rw ADDR   break when ADDR is read
  bl               list breakpoints and watchpoints   d ID   delete one
  r                registers                          set REG VALUE
  x ADDR [n]       hex dump                           poke ADDR VALUE
  u [ADDR] [n]     disassemble (default: at PC)
  hist [n]         last executed instructions
  io               key hardware registers             ppu   decoded LCD state
  screen           ASCII render of the screen         png FILE   save screenshot
  sym [text]       list symbols                       key BTN [up|down]   press a button
  save FILE        write a save state                 load FILE   restore one
  q                quit
`

func cmdDebug(args []string) error {
	fs := flag.NewFlagSet("debug", flag.ContinueOnError)
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("debug needs exactly one ROM file")
	}
	g, res, err := openMachine(pos[0])
	if err != nil {
		return err
	}
	var syms map[string]int
	if res != nil {
		syms = res.Symbols
	}
	return runDebugger(g, syms, os.Stdin, os.Stdout, isTerminal(os.Stdin))
}

func isTerminal(f *os.File) bool {
	st, err := f.Stat()
	return err == nil && st.Mode()&os.ModeCharDevice != 0
}

type debugSession struct {
	g    *gb.GB
	syms map[string]int
	byAd map[int][]string
	out  io.Writer
}

func runDebugger(g *gb.GB, syms map[string]int, in io.Reader, out io.Writer, prompt bool) error {
	s := &debugSession{g: g, syms: syms, byAd: map[int][]string{}, out: out}
	for n, a := range syms {
		if a >= 0 && a <= 0xFFFF {
			s.byAd[a] = append(s.byAd[a], n)
		}
	}
	for _, l := range s.byAd {
		sort.Strings(l)
	}
	g.Dbg = gb.NewDebugger()
	fmt.Fprintf(out, "dotmatrix debugger — %q, type 'help'\n", g.Cart.Info.Title)
	fmt.Fprintln(out, g.TraceLine())
	sc := bufio.NewScanner(in)
	for {
		if prompt {
			fmt.Fprint(out, "(dm) ")
		}
		if !sc.Scan() {
			return nil
		}
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		if !prompt {
			fmt.Fprintf(out, "(dm) %s\n", line)
		}
		if quit := s.exec(line); quit {
			return nil
		}
	}
}

func (s *debugSession) printf(f string, a ...any) { fmt.Fprintf(s.out, f, a...) }

// resolve parses a number, a symbol, or symbol+offset into an address.
func (s *debugSession) resolve(t string) (uint16, error) {
	t = strings.TrimSpace(t)
	if v, ok := s.syms[t]; ok {
		return uint16(v), nil
	}
	if i := strings.IndexAny(t, "+-"); i > 0 {
		if base, ok := s.syms[strings.TrimSpace(t[:i])]; ok {
			off, err := parseAddr(strings.TrimLeft(t[i+1:], " "))
			if err == nil {
				if t[i] == '-' {
					off = -off
				}
				return uint16(base + off), nil
			}
		}
	}
	a, err := parseAddr(t)
	if err != nil {
		return 0, fmt.Errorf("%q is not an address or known symbol", t)
	}
	return uint16(a), nil
}

func (s *debugSession) label(a uint16) string {
	if l := s.byAd[int(a)]; len(l) > 0 {
		return l[0]
	}
	return ""
}

func (s *debugSession) show() {
	pc := s.g.Regs().PC
	if l := s.label(pc); l != "" {
		s.printf("%s:\n", l)
	}
	s.printf("%s\n", s.g.TraceLine())
}

// run steps until a stop condition or the cycle budget is exhausted.
func (s *debugSession) run(maxCycles uint64, stopAt func() bool) {
	s.g.Dbg.ResumeFromStop()
	end := s.g.Cycles + maxCycles
	for s.g.Cycles < end {
		if err := s.g.StepChecked(); err != nil {
			var st *gb.StopError
			if errors.As(err, &st) {
				s.printf("** %s\n", st.Msg)
			} else {
				s.printf("** %v\n", err)
			}
			s.show()
			return
		}
		if stopAt != nil && stopAt() {
			s.show()
			return
		}
	}
	s.printf("** gave up after %d cycles without a stop\n", maxCycles)
	s.show()
}

func isCall(op byte) bool {
	switch op {
	case 0xCD, 0xC4, 0xCC, 0xD4, 0xDC:
		return true
	}
	return op&0xC7 == 0xC7 // RST
}

func (s *debugSession) exec(line string) (quit bool) {
	f := strings.Fields(line)
	cmd, args := f[0], f[1:]
	g := s.g
	num := func(i, def int) (int, bool) {
		if i >= len(args) {
			return def, true
		}
		v, err := parseAddr(args[i])
		if err != nil {
			s.printf("bad number %q\n", args[i])
			return 0, false
		}
		return v, true
	}
	switch cmd {
	case "q", "quit", "exit":
		return true
	case "h", "help", "?":
		s.printf("%s", debugHelp)
	case "r", "regs":
		s.printf("%s  IF=%02X IE=%02X\n", g.Regs(), g.Peek(0xFF0F), g.Peek(0xFFFF))
	case "s", "step":
		n, ok := num(0, 1)
		if !ok {
			return
		}
		for i := 0; i < n; i++ {
			g.Dbg.ResumeFromStop()
			if err := g.StepChecked(); err != nil {
				s.printf("** %v\n", err)
				break
			}
		}
		s.show()
	case "n", "next":
		pc := g.Regs().PC
		op := g.Peek(pc)
		if !isCall(op) {
			g.Dbg.ResumeFromStop()
			if err := g.StepChecked(); err != nil {
				s.printf("** %v\n", err)
			}
			s.show()
			return
		}
		_, n := asm.Disassemble(g.Peek, pc)
		ret := pc + uint16(n)
		s.run(200_000_000, func() bool { return g.Regs().PC == ret })
	case "c", "cont", "continue":
		fr, ok := num(0, 600)
		if !ok {
			return
		}
		s.run(uint64(fr)*gb.CyclesPerFrame, nil)
	case "f", "frames":
		fr, ok := num(0, 1)
		if !ok {
			return
		}
		target := g.Frames + uint64(fr)
		s.run(uint64(fr+2)*gb.CyclesPerFrame, func() bool { return g.Frames >= target })
	case "finish":
		sp0 := g.Regs().SP
		s.run(200_000_000, func() bool {
			op := g.Peek(g.Regs().PC)
			_ = op
			return g.Regs().SP > sp0 && s.lastWasRet()
		})
	case "until":
		if len(args) < 1 {
			s.printf("usage: until ADDR\n")
			return
		}
		a, err := s.resolve(args[0])
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		s.run(200_000_000, func() bool { return g.Regs().PC == a })
	case "b", "break":
		if len(args) < 1 {
			s.printf("usage: b ADDR [if COND]\n")
			return
		}
		a, err := s.resolve(args[0])
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		var cond *gb.Condition
		if len(args) > 1 {
			if args[1] != "if" || len(args) < 3 {
				s.printf("usage: b ADDR if COND\n")
				return
			}
			cond, err = gb.ParseCondition(strings.Join(args[2:], " "))
			if err != nil {
				s.printf("%v\n", err)
				return
			}
		}
		b := g.Dbg.AddBreak(a, cond)
		s.printf("breakpoint %d at %04X\n", b.ID, a)
	case "w", "watch", "rw":
		if len(args) < 1 {
			s.printf("usage: w ADDR\n")
			return
		}
		a, err := s.resolve(args[0])
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		kind := gb.WatchWrite
		if cmd == "rw" {
			kind = gb.WatchRead
		}
		w := g.Dbg.AddWatch(a, kind)
		s.printf("watchpoint %d at %04X\n", w.ID, a)
	case "bl", "info":
		for _, b := range g.Dbg.Breaks {
			c := ""
			if b.Cond != nil {
				c = " if " + b.Cond.String()
			}
			s.printf("%d: break %04X%s (hit %d)\n", b.ID, b.Addr, c, b.Hits)
		}
		for _, w := range g.Dbg.Watches {
			k := "write"
			if w.Kind == gb.WatchRead {
				k = "read"
			}
			s.printf("%d: watch %s %04X (hit %d)\n", w.ID, k, w.Addr, w.Hits)
		}
	case "d", "del", "delete":
		id, ok := num(0, -1)
		if !ok {
			return
		}
		if !g.Dbg.Delete(id) {
			s.printf("no breakpoint or watchpoint %d\n", id)
		}
	case "set":
		if len(args) != 2 {
			s.printf("usage: set REG VALUE\n")
			return
		}
		v, err := parseAddr(args[1])
		if err != nil {
			s.printf("bad value %q\n", args[1])
			return
		}
		if err := g.SetReg(strings.ToLower(args[0]), v); err != nil {
			s.printf("%v\n", err)
			return
		}
		s.printf("%s\n", g.Regs())
	case "poke":
		if len(args) != 2 {
			s.printf("usage: poke ADDR VALUE\n")
			return
		}
		a, err := s.resolve(args[0])
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		v, err := parseAddr(args[1])
		if err != nil || v > 0xFF {
			s.printf("bad byte value %q\n", args[1])
			return
		}
		g.Poke(a, byte(v))
	case "x":
		if len(args) < 1 {
			s.printf("usage: x ADDR [n]\n")
			return
		}
		a, err := s.resolve(args[0])
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		n, ok := num(1, 64)
		if !ok {
			return
		}
		for i := 0; i < n; i += 16 {
			s.printf("%04X ", int(a)+i)
			var asc strings.Builder
			for j := 0; j < 16 && i+j < n; j++ {
				b := g.Peek(uint16(int(a) + i + j))
				s.printf(" %02X", b)
				if b >= 32 && b < 127 {
					asc.WriteByte(b)
				} else {
					asc.WriteByte('.')
				}
			}
			s.printf("  |%s|\n", asc.String())
		}
	case "u":
		a := g.Regs().PC
		if len(args) >= 1 {
			var err error
			if a, err = s.resolve(args[0]); err != nil {
				s.printf("%v\n", err)
				return
			}
		}
		n, ok := num(1, 10)
		if !ok {
			return
		}
		for i := 0; i < n; i++ {
			if l := s.label(a); l != "" {
				s.printf("%s:\n", l)
			}
			txt, ln := asm.Disassemble(g.Peek, a)
			var raw []string
			for k := 0; k < ln; k++ {
				raw = append(raw, fmt.Sprintf("%02X", g.Peek(a+uint16(k))))
			}
			mark := " "
			if a == g.Regs().PC {
				mark = ">"
			}
			s.printf("%s %04X  %-9s %s\n", mark, a, strings.Join(raw, " "), txt)
			a += uint16(ln)
		}
	case "hist":
		n, ok := num(0, 10)
		if !ok {
			return
		}
		for _, pc := range g.Dbg.History(n) {
			txt, _ := asm.Disassemble(g.Peek, pc)
			s.printf("  %04X  %s\n", pc, txt)
		}
	case "io":
		regs := []struct {
			n string
			a uint16
		}{{"P1", 0xFF00}, {"DIV", 0xFF04}, {"TIMA", 0xFF05}, {"TMA", 0xFF06}, {"TAC", 0xFF07}, {"IF", 0xFF0F},
			{"LCDC", 0xFF40}, {"STAT", 0xFF41}, {"SCY", 0xFF42}, {"SCX", 0xFF43}, {"LY", 0xFF44}, {"LYC", 0xFF45},
			{"BGP", 0xFF47}, {"OBP0", 0xFF48}, {"OBP1", 0xFF49}, {"WY", 0xFF4A}, {"WX", 0xFF4B}, {"IE", 0xFFFF},
			{"NR50", 0xFF24}, {"NR51", 0xFF25}, {"NR52", 0xFF26}}
		for i, r := range regs {
			s.printf("%-5s %02X   ", r.n, g.Peek(r.a))
			if i%4 == 3 {
				s.printf("\n")
			}
		}
		s.printf("\n")
	case "ppu":
		lcdc := g.Peek(0xFF40)
		bit := func(b uint, on, off string) string {
			if lcdc&(1<<b) != 0 {
				return on
			}
			return off
		}
		s.printf("LCDC=%02X  LCD %s  BG %s  OBJ %s (%s)  window %s  tiles@%s  BGmap@%s  WINmap@%s\n", lcdc,
			bit(7, "on", "off"), bit(0, "on", "off"), bit(1, "on", "off"), bit(2, "8x16", "8x8"), bit(5, "on", "off"),
			bit(4, "8000", "8800"), bit(3, "9C00", "9800"), bit(6, "9C00", "9800"))
		s.printf("LY=%d LYC=%d mode=%d SCX=%d SCY=%d WX=%d WY=%d frame=%d\n", g.Peek(0xFF44), g.Peek(0xFF45), g.Peek(0xFF41)&3,
			g.Peek(0xFF43), g.Peek(0xFF42), g.Peek(0xFF4B), g.Peek(0xFF4A), g.Frames)
	case "screen":
		fmt.Fprint(s.out, g.ASCII())
	case "png":
		if len(args) != 1 {
			s.printf("usage: png FILE\n")
			return
		}
		b, err := g.PNG(3)
		if err == nil {
			err = os.WriteFile(args[0], b, 0o644)
		}
		if err != nil {
			s.printf("%v\n", err)
		}
	case "sym":
		var names []string
		for n, a := range s.syms {
			if len(args) == 0 || strings.Contains(n, args[0]) {
				names = append(names, fmt.Sprintf("%04X %s", a, n))
			}
		}
		sort.Strings(names)
		for _, n := range names {
			s.printf("%s\n", n)
		}
		if len(names) == 0 {
			s.printf("(no symbols — assemble from a .s file to get labels)\n")
		}
	case "save", "load":
		if len(args) != 1 {
			s.printf("usage: %s FILE\n", cmd)
			return
		}
		if cmd == "save" {
			if err := os.WriteFile(args[0], g.SaveState(), 0o644); err != nil {
				s.printf("%v\n", err)
			}
			return
		}
		b, err := os.ReadFile(args[0])
		if err == nil {
			err = g.LoadState(b)
		}
		if err != nil {
			s.printf("%v\n", err)
			return
		}
		s.show()
	case "key":
		if len(args) < 1 {
			s.printf("usage: key BUTTON [up|down]\n")
			return
		}
		b, ok := buttonNames[strings.ToLower(args[0])]
		if !ok {
			s.printf("unknown button %q\n", args[0])
			return
		}
		down := !(len(args) > 1 && args[1] == "up")
		g.SetButton(b, down)
	default:
		s.printf("unknown command %q (try 'help')\n", cmd)
	}
	return false
}

// lastWasRet reports whether the instruction just executed was a RET/RETI
// (detected from the history ring: the most recent entry is the instruction
// that ran last).
func (s *debugSession) lastWasRet() bool {
	h := s.g.Dbg.History(1)
	if len(h) == 0 {
		return false
	}
	op := s.g.Peek(h[0])
	return op == 0xC9 || op == 0xD9 || (op&0xE7 == 0xC0)
}
