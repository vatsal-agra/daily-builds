// Command dom is the Dominion compiler driver.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

const usage = `dom — Dominion SSA optimizing compiler

usage:
  dom run    [-O n] [-regs n] [-interp] [-stats] file.{dom,ir}   compile and execute @main
  dom ir     [-O n] [-passes a,b,c] [-trace] [-stats] file       print (optimised) SSA IR
  dom asm    [-O n] [-regs n] [-report] file                     print DVM assembly
  dom check  file                                                parse, verify and interpret
  dom bench  [-regs n] file...                                   cycles/instrs for -O0..-O3
  dom passes                                                     list optimisation passes
  dom fuzz   [-n N] [-seed S] [-regs list]                       differential fuzzer
  dom report [-O n] [-o out.html] file                           HTML CFG/dominator/pass report

optimisation levels: -O0 none · -O1 basic · -O2 full (inlining, GVN, LICM) · -O3 adds tail-recursion elimination and unrolling
`

const fuel = 2_000_000_000

func die(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "dom: "+format+"\n", a...)
	os.Exit(1)
}

func load(path string) *ir.Module {
	b, err := os.ReadFile(path)
	if err != nil {
		die("%v", err)
	}
	var m *ir.Module
	if strings.HasSuffix(path, ".ir") {
		m, err = ir.Parse(string(b))
	} else {
		m, err = front.Compile(string(b))
	}
	if err != nil {
		die("%s:%v", filepath.Base(path), err)
	}
	if err := m.Verify(); err != nil {
		die("%v", err)
	}
	return m
}

func main() {
	if len(os.Args) < 2 {
		fmt.Print(usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "run":
		cmdRun(args)
	case "ir":
		cmdIR(args)
	case "asm":
		cmdAsm(args)
	case "check":
		cmdCheck(args)
	case "bench":
		cmdBench(args)
	case "passes":
		fmt.Println(strings.Join(opt.PassNames(), "\n"))
	case "fuzz":
		cmdFuzz(args)
	case "report":
		cmdReport(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "dom: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
}

// normArgs rewrites -O2 into -O 2 so the conventional spelling works.
func normArgs(args []string) []string {
	var out []string
	for _, a := range args {
		if len(a) == 3 && a[0] == '-' && a[1] == 'O' && a[2] >= '0' && a[2] <= '9' {
			out = append(out, "-O", a[2:])
		} else {
			out = append(out, a)
		}
	}
	return out
}

func parseFlags(name string, args []string, setup func(fs *flag.FlagSet)) (*flag.FlagSet, string) {
	args = normArgs(args)
	fs := flag.NewFlagSet(name, flag.ExitOnError)
	setup(fs)
	// allow flags after the file name
	var pos []string
	for len(args) > 0 {
		fs.Parse(args)
		args = fs.Args()
		if len(args) > 0 {
			pos = append(pos, args[0])
			args = args[1:]
		}
	}
	if len(pos) != 1 {
		die("%s: expected exactly one input file", name)
	}
	return fs, pos[0]
}

func optimize(m *ir.Module, level int, passes string, trace bool) opt.Stats {
	list := opt.Level(level)
	if passes != "" {
		list = strings.Split(passes, ",")
	}
	var hook func(string, *ir.Module, int)
	if trace {
		hook = func(p string, _ *ir.Module, n int) { fmt.Fprintf(os.Stderr, "  [pass] %-12s %d change(s)\n", p, n) }
	}
	st, err := opt.Run(m, list, opt.Options{Verify: true, Hook: hook})
	if err != nil {
		die("%v", err)
	}
	return st
}

func cmdRun(args []string) {
	var lvl, regs int
	var interp, stats bool
	_, file := parseFlags("run", args, func(fs *flag.FlagSet) {
		fs.IntVar(&lvl, "O", 2, "optimisation level 0-3")
		fs.IntVar(&regs, "regs", 12, "allocatable registers")
		fs.BoolVar(&interp, "interp", false, "use the IR interpreter instead of the VM")
		fs.BoolVar(&stats, "stats", false, "print execution statistics")
	})
	m := load(file)
	optimize(m, lvl, "", false)
	var res ir.Result
	if interp {
		res = m.Run(fuel)
		if stats {
			fmt.Fprintf(os.Stderr, "[interp] %d IR steps\n", res.Steps)
		}
	} else {
		out, err := backend.Compile(m, backend.Config{NumRegs: regs})
		if err != nil {
			die("%v", err)
		}
		var st = struct{ c, i, mem, calls int64 }{}
		r, s := out.Prog.Run(fuel)
		res = r
		st.c, st.i, st.mem, st.calls = s.Cycles, s.Instrs, s.MemOps, s.Calls
		if stats {
			fmt.Fprintf(os.Stderr, "[vm] %d cycles, %d instrs, %d frame loads/stores, %d calls\n", st.c, st.i, st.mem, st.calls)
		}
	}
	fmt.Print(res.Out)
	if res.Trap != "" {
		fmt.Fprintf(os.Stderr, "trap: %s\n", res.Trap)
		os.Exit(3)
	}
	fmt.Fprintf(os.Stderr, "exit value: %d\n", res.Ret)
}

func cmdIR(args []string) {
	var lvl int
	var passes string
	var trace, stats bool
	_, file := parseFlags("ir", args, func(fs *flag.FlagSet) {
		fs.IntVar(&lvl, "O", 2, "optimisation level 0-3")
		fs.StringVar(&passes, "passes", "", "explicit comma-separated pass list (overrides -O)")
		fs.BoolVar(&trace, "trace", false, "log each pass")
		fs.BoolVar(&stats, "stats", false, "print per-pass change counts")
	})
	m := load(file)
	st := optimize(m, lvl, passes, trace)
	if stats {
		fmt.Fprintln(os.Stderr, st)
	}
	fmt.Print(m)
}

func cmdAsm(args []string) {
	var lvl, regs int
	var report bool
	_, file := parseFlags("asm", args, func(fs *flag.FlagSet) {
		fs.IntVar(&lvl, "O", 2, "optimisation level 0-3")
		fs.IntVar(&regs, "regs", 12, "allocatable registers")
		fs.BoolVar(&report, "report", false, "print register allocation report")
	})
	m := load(file)
	optimize(m, lvl, "", false)
	out, err := backend.Compile(m, backend.Config{NumRegs: regs})
	if err != nil {
		die("%v", err)
	}
	fmt.Print(out.Prog.Disasm())
	if report {
		fmt.Fprint(os.Stderr, "\n", out.ReportString())
	}
}

func cmdCheck(args []string) {
	_, file := parseFlags("check", args, func(fs *flag.FlagSet) {})
	m := load(file)
	res := m.Run(fuel)
	fmt.Printf("ok: %d function(s) verified; interpreter: %v\n", len(m.Funcs), res)
}

func cmdBench(args []string) {
	fs := flag.NewFlagSet("bench", flag.ExitOnError)
	regs := fs.Int("regs", 12, "allocatable registers")
	fs.Parse(args)
	files := fs.Args()
	if len(files) == 0 {
		die("bench: no input files")
	}
	fmt.Printf("%-14s %12s %12s %12s %12s   %s\n", "program", "O0 cycles", "O1", "O2", "O3", "O0→O3")
	for _, f := range files {
		var cyc [4]int64
		var want ir.Result
		for l := 0; l <= 3; l++ {
			m := load(f)
			if l == 0 {
				want = m.Run(fuel)
			}
			optimize(m, l, "", false)
			out, err := backend.Compile(m, backend.Config{NumRegs: *regs})
			if err != nil {
				die("%v", err)
			}
			r, s := out.Prog.Run(fuel)
			if !r.Same(want) {
				die("%s -O%d: MISCOMPILE: vm %v, interpreter(O0) %v", f, l, r, want)
			}
			cyc[l] = s.Cycles
		}
		name := strings.TrimSuffix(filepath.Base(f), filepath.Ext(f))
		fmt.Printf("%-14s %12d %12d %12d %12d   %.2fx\n", name, cyc[0], cyc[1], cyc[2], cyc[3], float64(cyc[0])/float64(cyc[3]))
	}
}
