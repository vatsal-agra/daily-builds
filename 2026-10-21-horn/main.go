package main

import (
	_ "embed"
	"fmt"
	"os"
	"runtime/debug"
	"runtime/pprof"
	"strings"
)

//go:embed lib.pl
var libSource string

func (m *Machine) loadLibrary() {
	m.flags["double_quotes"] = "codes"
	if err := m.consultReader(strings.NewReader(libSource), "library", true); err != nil {
		fmt.Fprintln(os.Stderr, "library load error:", err)
		os.Exit(2)
	}
	m.flags["double_quotes"] = "string"
	for _, at := range atomTable {
		for _, p := range at.preds {
			if p != nil && len(p.clauses) > 0 && !p.isBuiltin() {
				p.library = true
			}
		}
	}
}

const usage = `Horn Prolog 1.0 — a from-scratch Prolog in Go

usage: horn [options] [file.pl ...]

  -g GOAL     run GOAL after loading the files (repeatable); a failing/raising goal exits 1/2
  -t GOAL     run GOAL instead of entering the interactive toplevel (e.g. -t halt)
  --all       toplevel: print every solution instead of the first one when stdin is not a tty
  -q          quiet: no banner
  --version   print the version
  -h, --help  this text

With no -t goal Horn reads queries from standard input (prompting with "?- " on a terminal):
    ?- member(X, [a,b,c]).        % ';' asks for more answers on a terminal

Environment: HORN_PROF=file writes a CPU profile.
`

func isTTY(f *os.File) bool {
	st, err := f.Stat()
	return err == nil && st.Mode()&os.ModeCharDevice != 0
}

func main() {
	debug.SetMaxStack(1 << 32)
	if pf := os.Getenv("HORN_PROF"); pf != "" {
		f, _ := os.Create(pf)
		pprof.StartCPUProfile(f)
		defer pprof.StopCPUProfile()
		code := realMain(os.Args[1:])
		pprof.StopCPUProfile()
		os.Exit(code)
	}
	debug.SetGCPercent(400)
	debug.SetMemoryLimit(2 << 30)
	os.Exit(realMain(os.Args[1:]))
}

func realMain(args []string) (code int) {
	m := newMachine()
	m.loadLibrary()
	defer m.out.Flush()
	var files []string
	var goals []string
	topGoal := ""
	all := false
	quiet := false
	for i := 0; i < len(args); i++ {
		switch a := args[i]; a {
		case "-g":
			i++
			if i < len(args) {
				goals = append(goals, args[i])
			}
		case "-t":
			i++
			if i < len(args) {
				topGoal = args[i]
			}
		case "--all":
			all = true
		case "-q", "--quiet":
			quiet = true
		case "-h", "--help":
			fmt.Print(usage)
			return 0
		case "--version":
			fmt.Println("Horn Prolog 1.0")
			return 0
		case "--":
			files = append(files, args[i+1:]...)
			i = len(args)
		default:
			files = append(files, a)
		}
	}
	defer func() {
		if r := recover(); r != nil {
			m.out.Flush()
			fmt.Fprintf(os.Stderr, "internal error: %v\n", r)
			code = 2
		}
	}()
	handleHalt := func(err error) (int, bool) {
		if h, ok := err.(*haltSignal); ok {
			return h.code, true
		}
		return 0, false
	}
	for _, f := range files {
		if err := m.consultFile(f); err != nil {
			if c, ok := handleHalt(err); ok {
				return c
			}
			if pe, ok := err.(*PrologError); ok {
				m.printMessage("ERROR", messageText(pe.Ball), "")
			}
		}
	}
	for _, g := range goals {
		t, _, err := m.parseTermFromText(g)
		if err != nil {
			m.printMessage("ERROR", messageText(err.(*PrologError).Ball), "")
			return 1
		}
		ok, err := m.solveOnce(t)
		if err != nil {
			if c, ok := handleHalt(err); ok {
				return c
			}
			if pe, ok := err.(*PrologError); ok {
				m.printMessage("ERROR", messageText(pe.Ball), "")
			}
			return 2
		}
		if !ok {
			m.printMessage("Warning", "goal (initialization) failed", "")
			return 1
		}
	}
	if topGoal != "" {
		t, _, err := m.parseTermFromText(topGoal)
		if err != nil {
			return 1
		}
		if _, err := m.solveOnce(t); err != nil {
			if c, ok := handleHalt(err); ok {
				return c
			}
		}
		return 0
	}
	interactive := isTTY(os.Stdin)
	if interactive && !quiet {
		fmt.Println("Horn Prolog 1.0 — a from-scratch Prolog in Go. Type halt. to exit.")
	}
	if err := m.toplevel(interactive, all); err != nil {
		if c, ok := handleHalt(err); ok {
			return c
		}
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	return 0
}
