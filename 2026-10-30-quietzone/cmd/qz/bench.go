package main

import (
	"flag"
	"fmt"
	"os"

	"quietzone/bench"
)

func cmdBench(args []string) error {
	fs := flag.NewFlagSet("bench", flag.ContinueOnError)
	trials := fs.Int("n", 30, "trials per scenario")
	seed := fs.Int64("seed", 1, "base random seed")
	only := fs.String("only", "", "run just this scenario")
	strict := fs.Bool("strict", false, "exit non-zero when a scenario is below its floor")
	if err := fs.Parse(args); err != nil {
		return err
	}
	rows := bench.Run(*trials, *seed, *only)
	bad := 0
	fmt.Printf("%-34s %7s %9s %10s  %s\n", "scenario", "pass", "rate", "mean time", "floor")
	for _, r := range rows {
		mark := ""
		if r.Rate() < r.Floor {
			mark = "  BELOW FLOOR"
			bad++
		}
		fmt.Printf("%-34s %3d/%-3d %8.1f%% %10s  %.0f%%%s\n", r.Name, r.Pass, r.Trials, 100*r.Rate(), r.MeanTime.Round(1e6), 100*r.Floor, mark)
		for _, f := range r.Failures {
			fmt.Printf("    failed %s\n", f)
		}
	}
	if *strict && bad > 0 {
		fmt.Fprintf(os.Stderr, "%d scenario(s) below floor\n", bad)
		os.Exit(1)
	}
	return nil
}
