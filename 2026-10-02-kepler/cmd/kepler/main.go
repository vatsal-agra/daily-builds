// Command kepler discovers closed-form equations from data.
package main

import (
	"flag"
	"fmt"
	"math"
	"os"
	"strings"
	"time"

	"kepler/data"
	"kepler/expr"
	"kepler/gp"
	"kepler/report"
)

const usage = `kepler — symbolic regression: discover equations from data

usage:
  kepler fit    [flags] data.csv        search for formulas fitting a CSV (last column = target by default)
  kepler bench  [flags] [name ...]      rediscover built-in physics laws from generated data
  kepler gen    [flags] name            write a benchmark dataset as CSV to stdout
  kepler eval   "formula" k=v ...       evaluate a formula, e.g. kepler eval "2*pi*sqrt(L/g)" L=1 g=9.81
  kepler diff   "formula" var           symbolic derivative, e.g. kepler diff "sin(x)*x^2" x
  kepler datasets                       list built-in benchmarks

fit/bench flags: -pop -gens -islands -seed -maxsize -ops -holdout -report out.html -q
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "fit":
		err = cmdFit(os.Args[2:])
	case "bench":
		err = cmdBench(os.Args[2:])
	case "gen":
		err = cmdGen(os.Args[2:])
	case "eval":
		err = cmdEval(os.Args[2:])
	case "diff":
		err = cmdDiff(os.Args[2:])
	case "datasets":
		for _, b := range data.Benchmarks {
			fmt.Printf("%-9s %s\n          truth: %s = %s\n", b.Name, b.Desc, b.Target, b.Truth)
		}
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

type searchFlags struct {
	cfg    gp.Config
	ops    string
	report string
	quiet  bool
	target string
	n      int
}

func addFlags(fs *flag.FlagSet) *searchFlags {
	s := &searchFlags{cfg: gp.DefaultConfig()}
	fs.IntVar(&s.cfg.Pop, "pop", s.cfg.Pop, "population per island")
	fs.IntVar(&s.cfg.Gens, "gens", s.cfg.Gens, "generations")
	fs.IntVar(&s.cfg.Islands, "islands", s.cfg.Islands, "parallel islands")
	fs.Int64Var(&s.cfg.Seed, "seed", s.cfg.Seed, "random seed")
	fs.IntVar(&s.cfg.MaxSize, "maxsize", s.cfg.MaxSize, "max nodes per formula")
	fs.Float64Var(&s.cfg.Holdout, "holdout", s.cfg.Holdout, "holdout fraction for model selection (0 disables)")
	fs.StringVar(&s.ops, "ops", "", "comma list of enabled operators (default: + - * / ^ sqrt exp log sin cos)")
	fs.StringVar(&s.report, "report", "", "write an HTML report to this path")
	fs.BoolVar(&s.quiet, "q", false, "suppress progress")
	fs.StringVar(&s.target, "target", "", "target column (default: last)")
	fs.IntVar(&s.n, "n", 120, "bench: samples to generate")
	return s
}

func (s *searchFlags) apply() error {
	if s.ops != "" {
		s.cfg.Unary, s.cfg.Binary = nil, nil
		for _, o := range strings.Split(s.ops, ",") {
			o = strings.TrimSpace(o)
			switch o {
			case "+", "-", "*", "/", "^":
				s.cfg.Binary = append(s.cfg.Binary, o)
			case "neg", "sin", "cos", "exp", "log", "sqrt", "abs":
				s.cfg.Unary = append(s.cfg.Unary, o)
			default:
				return fmt.Errorf("unknown operator %q in -ops", o)
			}
		}
	}
	if !s.quiet {
		s.cfg.Verbose = func(m string) { fmt.Fprintln(os.Stderr, m) }
	}
	return nil
}

func cmdFit(args []string) error {
	fs := flag.NewFlagSet("fit", flag.ContinueOnError)
	s := addFlags(fs)
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return fmt.Errorf("fit needs exactly one CSV file")
	}
	if err := s.apply(); err != nil {
		return err
	}
	d, err := data.LoadCSV(fs.Arg(0), s.target)
	if err != nil {
		return err
	}
	t0 := time.Now()
	res, err := gp.Run(d, s.cfg)
	if err != nil {
		return err
	}
	printResult(d, res, time.Since(t0))
	if s.report != "" {
		if err := report.Write(s.report, d.Target, d, res, nil); err != nil {
			return err
		}
		fmt.Println("report written to", s.report)
	}
	return nil
}

func printResult(d *data.Dataset, res *gp.Result, el time.Duration) {
	fmt.Printf("\nPareto front for %s  (%d rows, %d gens, %d evals, %s)\n", d.Target, d.N(), res.Generations, res.Evals, el.Round(time.Millisecond))
	fmt.Printf("%-3s %5s %12s %12s  %s\n", "", "cplx", "train NMSE", "holdout", "formula")
	for i, m := range res.Front {
		mark := " "
		if i == res.Selected {
			mark = "*"
		}
		h := "      -"
		if !math.IsNaN(m.HoldoutNMSE) {
			h = fmt.Sprintf("%12.3e", m.HoldoutNMSE)
		}
		fmt.Printf("%-3s %5d %12.3e %12s  %s = %s\n", mark, m.Complexity, m.TrainNMSE, h, d.Target, m.Tree.Format(res.Names))
	}
	if res.Selected >= 0 {
		fmt.Printf("\nselected (*): %s = %s\n", d.Target, res.Front[res.Selected].Tree.Format(res.Names))
	}
}

func cmdBench(args []string) error {
	fs := flag.NewFlagSet("bench", flag.ContinueOnError)
	s := addFlags(fs)
	s.quiet = true
	if err := fs.Parse(args); err != nil {
		return err
	}
	s.quiet = true
	if err := s.apply(); err != nil {
		return err
	}
	var list []*data.Benchmark
	if fs.NArg() == 0 {
		for i := range data.Benchmarks {
			list = append(list, &data.Benchmarks[i])
		}
	}
	for _, n := range fs.Args() {
		b, ok := data.Find(n)
		if !ok {
			return fmt.Errorf("unknown benchmark %q (try `kepler datasets`)", n)
		}
		list = append(list, b)
	}
	var rows []report.BenchRow
	pass := 0
	for _, b := range list {
		d := b.Generate(s.n, s.cfg.Seed)
		t0 := time.Now()
		res, err := gp.Run(d, s.cfg)
		if err != nil {
			return err
		}
		sel := res.Front[res.Selected]
		// ground truth check: compare against the true formula on fresh test data
		truth, _ := expr.Parse(b.Truth, b.Names)
		test := b.Generate(300, s.cfg.Seed+999)
		tp := gp.NewProblem(test)
		// score the truth on noiseless fresh points
		clean := *b
		clean.Noise = 0
		tclean := gp.NewProblem(clean.Generate(300, s.cfg.Seed+999))
		testErr := tclean.NMSE(sel.Tree)
		_ = tp
		ok := testErr < 1e-3
		if ok {
			pass++
		}
		fmt.Printf("%-9s %s  truth: %s\n          found: %s = %s\n          complexity %d  held-out noiseless NMSE %.2e  (%s)\n",
			b.Name, status(ok), truth.Format(b.Names), b.Target, sel.Tree.Format(b.Names), sel.Complexity, testErr, time.Since(t0).Round(time.Millisecond))
		rows = append(rows, report.BenchRow{Name: b.Name, Desc: b.Desc, Truth: b.Target + " = " + b.Truth, Found: b.Target + " = " + sel.Tree.Format(b.Names), Err: testErr, OK: ok, Result: res, Data: d})
	}
	fmt.Printf("\n%d/%d laws rediscovered\n", pass, len(list))
	if s.report != "" {
		if err := report.WriteBench(s.report, rows); err != nil {
			return err
		}
		fmt.Println("report written to", s.report)
	}
	return nil
}

func status(ok bool) string {
	if ok {
		return "REDISCOVERED"
	}
	return "MISSED"
}

func cmdGen(args []string) error {
	fs := flag.NewFlagSet("gen", flag.ContinueOnError)
	s := addFlags(fs)
	if err := fs.Parse(args); err != nil {
		return err
	}
	if fs.NArg() != 1 {
		return fmt.Errorf("gen needs a benchmark name (see `kepler datasets`)")
	}
	b, ok := data.Find(fs.Arg(0))
	if !ok {
		return fmt.Errorf("unknown benchmark %q", fs.Arg(0))
	}
	return b.Generate(s.n, s.cfg.Seed).WriteCSV(os.Stdout)
}

func cmdEval(args []string) error {
	if len(args) < 1 {
		return fmt.Errorf(`eval needs a formula, e.g. kepler eval "x^2+1" x=3`)
	}
	var names []string
	var vals []float64
	for _, a := range args[1:] {
		k, v, ok := strings.Cut(a, "=")
		if !ok {
			return fmt.Errorf("bad binding %q, want name=value", a)
		}
		var f float64
		if _, err := fmt.Sscanf(v, "%g", &f); err != nil {
			return fmt.Errorf("bad value in %q", a)
		}
		names = append(names, k)
		vals = append(vals, f)
	}
	n, err := expr.Parse(args[0], names)
	if err != nil {
		return err
	}
	r := n.Eval(vals)
	if math.IsNaN(r) {
		return fmt.Errorf("result undefined (domain error: division by zero, log/sqrt of negative, overflow)")
	}
	s := expr.Simplify(n)
	fmt.Printf("%s = %.10g\n(simplified: %s)\n", n.Format(names), r, s.Format(names))
	return nil
}

func cmdDiff(args []string) error {
	if len(args) != 2 {
		return fmt.Errorf(`diff needs a formula and a variable, e.g. kepler diff "x^2*sin(x)" x`)
	}
	// every identifier is allowed: collect by trying the named variable first
	names := []string{args[1]}
	n, names, err := parseWithExtras(args[0], names)
	if err != nil {
		return err
	}
	d, err := expr.Diff(n, 0)
	if err != nil {
		return err
	}
	fmt.Printf("f(%s)  = %s\nd/d%s   = %s\n", args[1], expr.Simplify(n).Format(names), args[1], d.Format(names))
	return nil
}

// parseWithExtras lets other identifiers act as symbolic constants by
// registering them as extra variables after the differentiation variable.
func parseWithExtras(src string, names []string) (*expr.Node, []string, error) {
	for i := 0; i < 8; i++ {
		n, err := expr.Parse(src, names)
		if err == nil {
			return n, names, nil
		}
		const p = `unknown variable "`
		if j := strings.Index(err.Error(), p); j >= 0 {
			rest := err.Error()[j+len(p):]
			names = append(names, rest[:strings.Index(rest, `"`)])
			continue
		}
		return nil, nil, err
	}
	return nil, nil, fmt.Errorf("too many free symbols")
}
