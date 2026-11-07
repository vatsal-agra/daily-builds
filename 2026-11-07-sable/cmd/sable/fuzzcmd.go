package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	"sable"
)

func cmdFuzz(args []string) error {
	fs := flag.NewFlagSet("fuzz", flag.ContinueOnError)
	n := fs.Int("n", 500, "number of random programs")
	seed := fs.Int64("seed", 1, "first seed")
	show := fs.Bool("show", false, "print the generated program for -seed and exit")
	maxShow := fs.Int("max-findings", 3, "stop after this many findings")
	funcs := fs.Int("funcs", 3, "helper functions per program")
	if err := fs.Parse(args); err != nil {
		return err
	}
	cfg := sable.DefaultGen()
	cfg.Funcs = *funcs
	if *show {
		fmt.Print(sable.GenProgram(*seed, cfg))
		return nil
	}
	start := time.Now()
	found := 0
	traps := 0
	for i := 0; i < *n; i++ {
		s := *seed + int64(i)
		if f := sable.FuzzOne(s, cfg); f != nil {
			fmt.Println(f)
			found++
			if found >= *maxShow {
				break
			}
		}
		if i%100 == 99 {
			fmt.Fprintf(os.Stderr, "  ... %d programs, %d findings, %.1fs\n", i+1, found, time.Since(start).Seconds())
		}
	}
	_ = traps
	fmt.Printf("fuzz: %d programs (seeds %d..%d), %d findings, %.1fs\n", *n, *seed, *seed+int64(*n)-1, found, time.Since(start).Seconds())
	if found > 0 {
		return fmt.Errorf("fuzzing found %d divergence(s)", found)
	}
	return nil
}
