package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"dominion/fuzz"
)

func cmdFuzz(args []string) {
	fs := flag.NewFlagSet("fuzz", flag.ExitOnError)
	n := fs.Int("n", 500, "number of programs")
	seed := fs.Int64("seed", 1, "first seed")
	regs := fs.String("regs", "4,6,12", "comma-separated register-file sizes")
	show := fs.Bool("show", false, "print the generated program for -seed and exit")
	noReduce := fs.Bool("no-reduce", false, "do not minimise failures")
	mutants := fs.Bool("ir", false, "fuzz mutated IR (hostile CFGs/phis) instead of generated source")
	fs.Parse(normArgs(args))
	if *show {
		fmt.Print(fuzz.Generate(*seed))
		return
	}
	cfg := fuzz.DefaultConfig
	cfg.Regs = nil
	for _, s := range strings.Split(*regs, ",") {
		v, err := strconv.Atoi(strings.TrimSpace(s))
		if err != nil {
			die("bad -regs value %q", s)
		}
		cfg.Regs = append(cfg.Regs, v)
	}
	start := time.Now()
	var ok, skipped, trapped, failed int
	for i := 0; i < *n; i++ {
		s := *seed + int64(i)
		var o fuzz.Outcome
		if *mutants {
			o = fuzz.CheckMutant(s, cfg)
		} else {
			o = fuzz.Check(s, cfg)
		}
		switch {
		case o.Fail != nil:
			failed++
			fmt.Printf("FAIL %v\n", o.Fail)
			src := o.Fail.Src
			if !*noReduce && !*mutants {
				src = fuzz.Reduce(o.Fail, cfg)
			}
			fmt.Printf("--- %s program ---\n%s", map[bool]string{true: "original", false: "minimised"}[*noReduce || *mutants], src)
		case o.Skipped:
			skipped++
		case o.Trapped:
			trapped++
			ok++
		default:
			ok++
		}
		if failed > 0 {
			break
		}
	}
	fmt.Printf("fuzz: %d programs from seed %d in %v: %d agreed everywhere (%d of them trap identically), %d skipped (invalid, UB or non-terminating), %d FAILED\n",
		ok+skipped+failed, *seed, time.Since(start).Round(time.Millisecond), ok, trapped, skipped, failed)
	if failed > 0 {
		os.Exit(1)
	}
}
