package main

import (
	"flag"
	"fmt"
	"os"

	"spillway/sp"
)

func cmdGen(args []string) error {
	fs := flag.NewFlagSet("gen", flag.ContinueOnError)
	seed := fs.Int64("seed", 1, "random seed")
	vars := fs.Int("vars", 10, "long-lived variables (register pressure)")
	depth := fs.Int("depth", 3, "maximum if/loop nesting")
	shuffle := fs.Bool("shuffle", false, "randomly permute block layout")
	if _, err := parseFlags(fs, args, false); err != nil {
		return err
	}
	if *vars < 2 || *vars > 400 || *depth < 0 || *depth > 6 {
		return fmt.Errorf("need 2 <= -vars <= 400 and 0 <= -depth <= 6")
	}
	fmt.Print(sp.Generate(*seed, sp.GenConfig{Vars: *vars, Depth: *depth, Stmts: 6, Shuffle: *shuffle}))
	return nil
}

func cmdFuzz(args []string) error {
	fs := flag.NewFlagSet("fuzz", flag.ContinueOnError)
	n := fs.Int("n", 200, "number of random programs")
	seed := fs.Int64("seed", 1, "first seed")
	vars := fs.Int("vars", 14, "maximum variables per program")
	if _, err := parseFlags(fs, args, false); err != nil {
		return err
	}
	if *n < 1 || *vars < 2 {
		return fmt.Errorf("need -n >= 1 and -vars >= 2")
	}
	rep := sp.Fuzz(*n, *seed, []int{3, 4, 5, 8, 16}, sp.GenConfig{Vars: *vars, Depth: 3, Stmts: 6})
	fmt.Printf("fuzzed %d programs: %d allocations, %d differential executions, %d programs needed spilling\n",
		rep.Programs, rep.Allocations, rep.Executions, rep.Spilly)
	if len(rep.Failures) > 0 {
		for i, f := range rep.Failures {
			if i >= 20 {
				fmt.Printf("... and %d more\n", len(rep.Failures)-20)
				break
			}
			fmt.Println("FAIL", f)
		}
		return fmt.Errorf("%d divergence(s) found", len(rep.Failures))
	}
	fmt.Println("no divergence: every allocation matched the reference interpreter")
	return nil
}

func cmdReport(args []string) error {
	fs := flag.NewFlagSet("report", flag.ContinueOnError)
	k := fs.Int("k", 6, "number of physical registers")
	out := fs.String("o", "report.html", "output file")
	a := fs.String("args", "", "input vector(s)")
	file, err := parseFlags(fs, args, true)
	if err != nil {
		return err
	}
	f, err := load(file)
	if err != nil {
		return err
	}
	ins, err := parseInputs(*a)
	if err != nil {
		return err
	}
	if *k < sp.MinK || *k > sp.MaxK {
		return fmt.Errorf("-k must be between %d and %d", sp.MinK, sp.MaxK)
	}
	if err := sp.CheckTerminates(f, ins); err != nil {
		return err
	}
	src, _ := os.ReadFile(file)
	html, err := sp.Report(sp.ReportInput{Source: string(src), F: f, K: *k, Inputs: ins})
	if err != nil {
		return err
	}
	if err := os.WriteFile(*out, []byte(html), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d KB)\n", *out, len(html)/1024)
	return nil
}
