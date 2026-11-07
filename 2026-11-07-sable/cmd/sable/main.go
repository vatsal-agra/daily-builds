// Command sable compiles and runs Sable programs and inspects every compiler stage.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"sable"
)

const usage = `sable — an SSA optimizing compiler with register allocation

usage: sable <command> [flags] <file.sb | ->

commands:
  run     compile and execute (-engine vm|ast|ir)
  check   run every executor (AST, IR, SSA, optimised SSA, VM) and compare with the oracle
  ir      print IR  (-stage lowered|ssa|opt)
  asm     print allocated machine code
  stats   optimiser pass table + allocator comparison across register counts
  fuzz    differential-test random programs (no file argument)
  report  write a self-contained HTML report

common flags: -O 0|1|2   -k <registers>   -alg ls|gc   -noinline
`

type common struct {
	opt      int
	k        int
	alg      string
	noinline bool
}

func (c *common) register(fs *flag.FlagSet) {
	fs.IntVar(&c.opt, "O", 2, "optimisation level 0..2")
	fs.IntVar(&c.k, "k", 8, "allocatable registers (>= 2)")
	fs.StringVar(&c.alg, "alg", "ls", "register allocator: ls (linear scan) or gc (graph colouring)")
	fs.BoolVar(&c.noinline, "noinline", false, "disable inlining")
}

func (c common) config() (sable.Config, error) {
	cfg := sable.Config{OptLevel: c.opt, Regs: c.k, NoInline: c.noinline, Verify: true}
	switch c.alg {
	case "ls", "linear", "linear-scan":
		cfg.Alg = sable.LinearScan
	case "gc", "color", "graph-color":
		cfg.Alg = sable.GraphColor
	default:
		return cfg, fmt.Errorf("unknown allocator %q (use ls or gc)", c.alg)
	}
	if c.opt < 0 || c.opt > 2 {
		return cfg, fmt.Errorf("-O must be 0, 1 or 2")
	}
	if c.k < 2 || c.k > 64 {
		return cfg, fmt.Errorf("-k must be between 2 and 64")
	}
	return cfg, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "run":
		err = cmdRun(args)
	case "check":
		err = cmdCheck(args)
	case "ir":
		err = cmdIR(args)
	case "asm":
		err = cmdAsm(args)
	case "stats":
		err = cmdStats(args)
	case "fuzz":
		err = cmdFuzz(args)
	case "report":
		err = cmdReport(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "sable: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func readSource(fs *flag.FlagSet) (name, src string, err error) {
	if fs.NArg() != 1 {
		return "", "", fmt.Errorf("expected exactly one source file (or - for stdin)")
	}
	name = fs.Arg(0)
	var b []byte
	if name == "-" {
		b, err = io.ReadAll(os.Stdin)
		name = "<stdin>"
	} else {
		b, err = os.ReadFile(name)
	}
	return name, string(b), err
}

// parseFlags allows flags before or after the file argument.
func parseFlags(fs *flag.FlagSet, args []string) error {
	var flags, rest []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") && a != "-" {
			flags = append(flags, a)
			if !strings.Contains(a, "=") && needsValue(fs, a) && i+1 < len(args) {
				i++
				flags = append(flags, args[i])
			}
		} else {
			rest = append(rest, a)
		}
	}
	return fs.Parse(append(flags, rest...))
}

func needsValue(fs *flag.FlagSet, a string) bool {
	f := fs.Lookup(strings.TrimLeft(a, "-"))
	if f == nil {
		return false
	}
	if bf, ok := f.Value.(interface{ IsBoolFlag() bool }); ok && bf.IsBoolFlag() {
		return false
	}
	return true
}

// showError prints a compile error with the offending source line.
func showError(name, src string, err error) error {
	e, ok := err.(*sable.Error)
	if !ok {
		return fmt.Errorf("%s: %v", name, err)
	}
	lines := strings.Split(src, "\n")
	msg := fmt.Sprintf("%s:%s: error: %s", name, e.Pos, e.Msg)
	if e.Pos.Line >= 1 && e.Pos.Line <= len(lines) {
		l := strings.ReplaceAll(lines[e.Pos.Line-1], "\t", " ")
		msg += fmt.Sprintf("\n  %s\n  %s^", l, strings.Repeat(" ", max(e.Pos.Col-1, 0)))
	}
	return fmt.Errorf("%s", msg)
}

func printOutcome(o sable.Outcome) int {
	for _, v := range o.Output {
		fmt.Println(v)
	}
	if o.Trap != "" {
		fmt.Fprintf(os.Stderr, "runtime error: %s\n", o.Trap)
		return 3
	}
	fmt.Fprintf(os.Stderr, "exit value: %d\n", o.Ret)
	return 0
}

func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	var c common
	c.register(fs)
	engine := fs.String("engine", "vm", "executor: vm, ast or ir")
	fuel := fs.Int64("fuel", 2_000_000_000, "instruction budget")
	stats := fs.Bool("stats", false, "print VM counters")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	cfg, err := c.config()
	if err != nil {
		return err
	}
	prog, err := sable.Parse(src)
	if err != nil {
		return showError(name, src, err)
	}
	var code int
	switch *engine {
	case "ast":
		code = printOutcome(sable.RunAST(prog, *fuel))
	case "ir":
		comp, err := sable.CompileAST(prog, cfg)
		if err != nil {
			return err
		}
		code = printOutcome(sable.RunIR(comp.Opt, *fuel))
	case "vm":
		comp, err := sable.CompileAST(prog, cfg)
		if err != nil {
			return err
		}
		out, st := sable.RunProgram(comp.Prog, *fuel)
		code = printOutcome(out)
		if *stats {
			fmt.Fprintf(os.Stderr, "instrs=%d cycles=%d calls=%d moves=%d mem-loads=%d mem-stores=%d\n",
				st.Instrs, st.Cycles, st.Calls, st.Moves, st.SpillLoads, st.SpillStores)
		}
	default:
		return fmt.Errorf("unknown engine %q", *engine)
	}
	os.Exit(code)
	return nil
}

func cmdIR(args []string) error {
	fs := flag.NewFlagSet("ir", flag.ContinueOnError)
	var c common
	c.register(fs)
	stage := fs.String("stage", "opt", "lowered, ssa or opt")
	only := fs.String("func", "", "print only this function")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	cfg, err := c.config()
	if err != nil {
		return err
	}
	prog, err := sable.Parse(src)
	if err != nil {
		return showError(name, src, err)
	}
	var m *sable.Module
	switch *stage {
	case "lowered":
		m = sable.Lower(prog)
	case "ssa", "opt":
		comp, err := sable.CompileAST(prog, cfg)
		if err != nil {
			return err
		}
		m = comp.SSA
		if *stage == "opt" {
			m = comp.Opt
		}
	default:
		return fmt.Errorf("unknown stage %q", *stage)
	}
	for _, f := range m.Funcs {
		if *only == "" || *only == f.Name {
			fmt.Print(f)
		}
	}
	return nil
}

func cmdAsm(args []string) error {
	fs := flag.NewFlagSet("asm", flag.ContinueOnError)
	var c common
	c.register(fs)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	cfg, err := c.config()
	if err != nil {
		return err
	}
	comp, err := sable.Compile(src, cfg)
	if err != nil {
		return showError(name, src, err)
	}
	t := comp.Prog.Target
	fmt.Printf("; target: %d registers (r0-r%d caller-saved, r%d-r%d callee-saved, r%d/r%d scratch), %v, -O%d\n",
		t.K, t.Caller-1, t.Caller, t.K-1, t.K, t.K+1, cfg.Alg, cfg.OptLevel)
	for _, f := range comp.Prog.Funcs {
		st := comp.Prog.Stats[f.Name]
		fmt.Printf("; %s: %d instructions, %d spilled values, %d callee-saved used, %d moves removed\n",
			f.Name, f.StaticSize(), st.Spilled, st.CalleeSaved, st.MovesRemoved)
		fmt.Print(f)
	}
	return nil
}

func cmdStats(args []string) error {
	fs := flag.NewFlagSet("stats", flag.ContinueOnError)
	var c common
	c.register(fs)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	cfg, err := c.config()
	if err != nil {
		return err
	}
	prog, err := sable.Parse(src)
	if err != nil {
		return showError(name, src, err)
	}
	oracle := sable.RunAST(prog, 2_000_000_000)
	fmt.Printf("oracle: %v   (AST steps %d)\n\n", oracle, oracle.Steps)
	comp, err := sable.CompileAST(prog, cfg)
	if err != nil {
		return err
	}
	fmt.Println("optimiser passes (-O" + fmt.Sprint(cfg.OptLevel) + "):")
	fmt.Print(comp.Passes.Summary())
	ssaN, optN := 0, 0
	for _, f := range comp.SSA.Funcs {
		ssaN += f.NumInstrs()
	}
	for _, f := range comp.Opt.Funcs {
		optN += f.NumInstrs()
	}
	fmt.Printf("static IR instructions: %d -> %d\n", ssaN, optN)
	ir0 := sable.RunIR(comp.SSA, 4_000_000_000)
	ir1 := sable.RunIR(comp.Opt, 4_000_000_000)
	fmt.Printf("dynamic IR instructions: %d -> %d\n\n", ir0.Steps, ir1.Steps)

	fmt.Println("register allocation (dynamic counts from the VM; mem = loads+stores incl. callee-save traffic):")
	fmt.Printf("%4s  %-12s %10s %10s %10s %8s %7s\n", "K", "allocator", "instrs", "cycles", "mem ops", "spilled", "static")
	ok := true
	for _, k := range []int{2, 3, 4, 6, 8, 12, 16} {
		for _, alg := range []sable.Alg{sable.LinearScan, sable.GraphColor} {
			cc := cfg
			cc.Regs, cc.Alg = k, alg
			cm, err := sable.CompileAST(prog, cc)
			if err != nil {
				return err
			}
			out, st := sable.RunProgram(cm.Prog, 4_000_000_000)
			spilled, static := 0, 0
			for _, f := range cm.Prog.Funcs {
				spilled += cm.Prog.Stats[f.Name].Spilled
				static += f.StaticSize()
			}
			mark := ""
			if !out.Resource() && !oracle.Resource() && !out.Same(oracle) {
				mark, ok = "  <-- MISMATCH", false
			}
			fmt.Printf("%4d  %-12v %10d %10d %10d %8d %7d%s\n", k, alg, st.Instrs, st.Cycles, st.SpillLoads+st.SpillStores, spilled, static, mark)
		}
	}
	if !ok {
		return fmt.Errorf("some configuration disagreed with the oracle")
	}
	return nil
}

func cmdCheck(args []string) error {
	fs := flag.NewFlagSet("check", flag.ContinueOnError)
	var c common
	c.register(fs)
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	name, src, err := readSource(fs)
	if err != nil {
		return err
	}
	if _, err := c.config(); err != nil {
		return err
	}
	res, err := sable.CheckAll(src)
	if err != nil {
		return showError(name, src, err)
	}
	bad := 0
	for _, r := range res.Rows {
		status := "ok"
		if r.Skipped != "" {
			status = "skipped (" + r.Skipped + ")"
		} else if !r.Match {
			status, bad = "MISMATCH: "+r.Outcome.String(), bad+1
		}
		fmt.Printf("  %-34s %s\n", r.Name, status)
	}
	fmt.Printf("oracle: %v\n", res.Oracle)
	if bad > 0 {
		return fmt.Errorf("%d executor(s) disagree with the oracle", bad)
	}
	fmt.Printf("all %d executors agree\n", len(res.Rows))
	return nil
}
