package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"dotmatrix/asm"
	"dotmatrix/gb"
)

// parseArgs parses flags that may appear before or after positional arguments.
func parseArgs(fs *flag.FlagSet, args []string) ([]string, error) {
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		if fs.NArg() == 0 {
			return pos, nil
		}
		pos = append(pos, fs.Arg(0))
		args = fs.Args()[1:]
	}
}

func parseAddr(s string) (int, error) {
	s = strings.TrimSpace(strings.TrimPrefix(strings.ToLower(s), "$"))
	base := 10
	if strings.HasPrefix(s, "0x") {
		s, base = s[2:], 16
	} else if strings.ContainsAny(s, "abcdef") {
		base = 16
	}
	v, err := strconv.ParseInt(s, base, 32)
	if err != nil || v < 0 || v > 0xFFFF {
		return 0, fmt.Errorf("bad address %q", s)
	}
	return int(v), nil
}

// assembleFile assembles a source file (resolving includes next to it).
func assembleFile(path string) (*asm.Result, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return asm.Assemble(filepath.Base(path), string(src), asm.Options{Include: asm.FileInclude(filepath.Dir(path))})
}

// loadROM reads a ROM image, assembling it first if the path ends in .s/.asm.
func loadROM(path string) ([]byte, *asm.Result, error) {
	ext := strings.ToLower(filepath.Ext(path))
	if ext == ".s" || ext == ".asm" {
		r, err := assembleFile(path)
		if err != nil {
			return nil, nil, err
		}
		return r.ROM, r, nil
	}
	b, err := os.ReadFile(path)
	return b, nil, err
}

func openMachine(path string) (*gb.GB, *asm.Result, error) {
	rom, res, err := loadROM(path)
	if err != nil {
		return nil, nil, err
	}
	cart, err := gb.NewCart(rom)
	if err != nil {
		return nil, nil, err
	}
	return gb.New(cart), res, nil
}

func cmdAsm(args []string) error {
	fs := flag.NewFlagSet("asm", flag.ContinueOnError)
	out := fs.String("o", "", "output ROM path (default: input with .gb)")
	sym := fs.String("sym", "", "write a symbol file")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("asm needs exactly one source file")
	}
	res, err := assembleFile(pos[0])
	if err != nil {
		return err
	}
	if *out == "" {
		*out = strings.TrimSuffix(pos[0], filepath.Ext(pos[0])) + ".gb"
	}
	if err := os.WriteFile(*out, res.ROM, 0o644); err != nil {
		return err
	}
	if *sym != "" {
		if err := os.WriteFile(*sym, []byte(res.SymFile()), 0o644); err != nil {
			return err
		}
	}
	fmt.Printf("assembled %s -> %s (%d bytes, %d symbols)\n", pos[0], *out, len(res.ROM), len(res.Symbols))
	return nil
}

func cmdDis(args []string) error {
	fs := flag.NewFlagSet("dis", flag.ContinueOnError)
	from := fs.String("from", "0x0100", "start address")
	n := fs.Int("len", 64, "bytes to disassemble")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("dis needs exactly one ROM file")
	}
	rom, _, err := loadROM(pos[0])
	if err != nil {
		return err
	}
	start, err := parseAddr(*from)
	if err != nil {
		return err
	}
	if start >= len(rom) {
		return fmt.Errorf("address %04X is past the end of the ROM (%d bytes)", start, len(rom))
	}
	end := start + *n
	if end > len(rom) {
		end = len(rom)
	}
	for _, l := range asm.DisassembleBytes(rom[start:end], uint16(start)) {
		var raw []string
		for i := 0; i < l.Len; i++ {
			raw = append(raw, fmt.Sprintf("%02X", rom[int(l.Addr)+i]))
		}
		fmt.Printf("%04X  %-9s %s\n", l.Addr, strings.Join(raw, " "), l.Text)
	}
	return nil
}

func cmdInfo(args []string) error {
	if len(args) != 1 {
		return errors.New("info needs exactly one ROM file")
	}
	rom, _, err := loadROM(args[0])
	if err != nil {
		return err
	}
	h, err := gb.ParseHeader(rom)
	if err != nil {
		return err
	}
	ok := func(b bool) string {
		if b {
			return "ok"
		}
		return "BAD"
	}
	fmt.Printf("title:            %q\n", h.Title)
	fmt.Printf("cartridge type:   0x%02X %s\n", h.Type, h.TypeName)
	fmt.Printf("ROM size:         %d KiB (declared) / %d KiB (file)\n", h.ROMSize/1024, len(rom)/1024)
	fmt.Printf("RAM size:         %d KiB\n", h.RAMSize/1024)
	fmt.Printf("header checksum:  %02X (%s)\n", h.HeaderChecksum, ok(h.HeaderOK))
	fmt.Printf("global checksum:  %04X (%s)\n", h.GlobalChecksum, ok(h.GlobalOK))
	if h.CGBFlag == 0xC0 {
		fmt.Println("note: CGB-only cartridge; this emulator is DMG-only")
	}
	if len(rom) != h.ROMSize {
		fmt.Printf("warning: file is %d bytes but header declares %d\n", len(rom), h.ROMSize)
	}
	if !h.HeaderOK {
		return errors.New("header checksum mismatch (real hardware would refuse to boot this)")
	}
	return nil
}

var buttonNames = map[string]int{
	"right": gb.BtnRight, "left": gb.BtnLeft, "up": gb.BtnUp, "down": gb.BtnDown,
	"a": gb.BtnA, "b": gb.BtnB, "select": gb.BtnSelect, "start": gb.BtnStart,
}

type keyEvent struct {
	frame int
	btn   int
	down  bool
}

// parseKeys parses "frame:button" events; a leading '-' releases the button.
func parseKeys(spec string) ([]keyEvent, error) {
	var evs []keyEvent
	if strings.TrimSpace(spec) == "" {
		return nil, nil
	}
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		fr, name, ok := strings.Cut(part, ":")
		if !ok {
			return nil, fmt.Errorf("bad key event %q (want frame:button)", part)
		}
		f, err := strconv.Atoi(fr)
		if err != nil || f < 0 {
			return nil, fmt.Errorf("bad frame number in %q", part)
		}
		down := true
		if strings.HasPrefix(name, "-") {
			down, name = false, name[1:]
		}
		b, ok := buttonNames[strings.ToLower(name)]
		if !ok {
			return nil, fmt.Errorf("unknown button %q", name)
		}
		evs = append(evs, keyEvent{f, b, down})
	}
	return evs, nil
}

func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	frames := fs.Int("frames", 60, "frames to run")
	pngOut := fs.String("png", "", "write final frame as PNG")
	scale := fs.Int("scale", 3, "PNG scale factor")
	ascii := fs.Bool("ascii", false, "print final frame as text")
	serial := fs.Bool("serial", false, "print serial output")
	keys := fs.String("keys", "", "scripted input frame:button,...")
	save := fs.String("save", "", "battery save file")
	until := fs.String("until-serial", "", "stop when serial output contains this text")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("run needs exactly one ROM file")
	}
	if *frames < 0 || *scale < 1 || *scale > 16 {
		return errors.New("-frames must be >= 0 and -scale in 1..16")
	}
	evs, err := parseKeys(*keys)
	if err != nil {
		return err
	}
	g, _, err := openMachine(pos[0])
	if err != nil {
		return err
	}
	if *save != "" && g.Cart.Battery() {
		if b, err := os.ReadFile(*save); err == nil {
			copy(g.Cart.RAM, b)
		}
	}
	var runErr error
	for f := 0; f < *frames; f++ {
		for _, e := range evs {
			if e.frame == f {
				g.SetButton(e.btn, e.down)
			}
		}
		if runErr = g.RunFrame(); runErr != nil {
			break
		}
		if *until != "" && bytes.Contains(g.Serial, []byte(*until)) {
			break
		}
	}
	if *serial {
		os.Stdout.Write(g.Serial)
		if len(g.Serial) > 0 && g.Serial[len(g.Serial)-1] != '\n' {
			fmt.Println()
		}
	}
	if *ascii {
		fmt.Print(g.ASCII())
	}
	if *pngOut != "" {
		b, err := g.PNG(*scale)
		if err != nil {
			return err
		}
		if err := os.WriteFile(*pngOut, b, 0o644); err != nil {
			return err
		}
	}
	if *save != "" && g.Cart.Battery() {
		if err := os.WriteFile(*save, g.Cart.RAM, 0o644); err != nil {
			return err
		}
	}
	fmt.Fprintf(os.Stderr, "ran %d frames (%d cycles), PC=%04X\n", g.Frames, g.Cycles, g.Regs().PC)
	return runErr
}

func cmdTrace(args []string) error {
	fs := flag.NewFlagSet("trace", flag.ContinueOnError)
	n := fs.Int("n", 50, "instructions to trace")
	from := fs.String("from", "", "start tracing when PC first reaches ADDR")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("trace needs exactly one ROM file")
	}
	g, _, err := openMachine(pos[0])
	if err != nil {
		return err
	}
	if *from != "" {
		a, err := parseAddr(*from)
		if err != nil {
			return err
		}
		for i := 0; g.Regs().PC != uint16(a); i++ {
			if i > 50_000_000 {
				return fmt.Errorf("PC never reached %04X", a)
			}
			if err := g.StepChecked(); err != nil {
				return err
			}
		}
	}
	for i := 0; i < *n; i++ {
		fmt.Println(g.TraceLine())
		if err := g.StepChecked(); err != nil {
			return err
		}
	}
	return nil
}

func cmdTest(args []string) error {
	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	frames := fs.Int("frames", 600, "maximum frames to run")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("test needs exactly one ROM file")
	}
	g, _, err := openMachine(pos[0])
	if err != nil {
		return err
	}
	shown := 0
	for f := 0; f < *frames; f++ {
		if err := g.RunFrame(); err != nil {
			os.Stdout.Write(g.Serial[shown:])
			return err
		}
		os.Stdout.Write(g.Serial[shown:])
		shown = len(g.Serial)
		for _, line := range strings.Split(string(g.Serial), "\n") {
			switch {
			case strings.HasPrefix(line, "PASS"):
				return nil
			case strings.HasPrefix(line, "FAIL total"):
				return errors.New("ROM reported FAIL")
			}
		}
	}
	return fmt.Errorf("ROM produced no PASS/FAIL verdict within %d frames", *frames)
}
