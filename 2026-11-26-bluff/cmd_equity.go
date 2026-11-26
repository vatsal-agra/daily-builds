package main

import (
	"fmt"
	"io"
	"strings"
)

func cmdEquity(args []string, out io.Writer) error {
	fs := newFlags("equity")
	board := fs.String("board", "", "community cards, e.g. Ah7d2c")
	dead := fs.String("dead", "", "known dead cards")
	n := fs.Int("n", 200000, "Monte-Carlo samples when exact enumeration is too large")
	seed := fs.Int64("seed", 1, "RNG seed")
	limit := fs.Int64("exact-limit", 4_000_000, "max evaluations to enumerate exactly")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if *n < 1 {
		return fmt.Errorf("-n must be ≥ 1")
	}
	if len(pos) < 2 {
		return fmt.Errorf("usage: bluff equity [-board Ah7d2c] [-dead ..] <range1> <range2> [...]\n  e.g. bluff equity AhAs KdKc    |   bluff equity \"QQ+,AKs\" random")
	}
	var bc, dc []int
	if *board != "" {
		if bc, err = ParseCards(*board); err != nil {
			return fmt.Errorf("-board: %w", err)
		}
	}
	if *dead != "" {
		if dc, err = ParseCards(*dead); err != nil {
			return fmt.Errorf("-dead: %w", err)
		}
	}
	var ranges [][]Combo
	for i, spec := range pos {
		r, err := ParseRange(spec)
		if err != nil {
			return fmt.Errorf("player %d: %w", i+1, err)
		}
		ranges = append(ranges, r)
	}
	res, err := Equity(ranges, EquityOpts{Board: bc, Dead: dc, Samples: *n, Seed: *seed, ExactLimit: *limit})
	if err != nil {
		return err
	}
	if len(bc) > 0 {
		var s []string
		for _, c := range bc {
			s = append(s, CardString(c))
		}
		fmt.Fprintf(out, "board: %s\n", strings.Join(s, " "))
	}
	mode := fmt.Sprintf("exact, %d deals enumerated", res.Samples)
	if !res.Exact {
		mode = fmt.Sprintf("Monte Carlo, %d samples, seed %d", res.Samples, *seed)
	}
	fmt.Fprintf(out, "%s\n", mode)
	fmt.Fprintf(out, "%-3s %-22s %8s %8s %8s", "#", "range", "equity", "win", "tie")
	if !res.Exact {
		fmt.Fprintf(out, "  %s", "±stderr")
	}
	fmt.Fprintln(out)
	for i, spec := range pos {
		label := spec
		if len(label) > 22 {
			label = label[:19] + "..."
		}
		fmt.Fprintf(out, "%-3d %-22s %7.2f%% %7.2f%% %7.2f%%", i+1, label, 100*res.Equity[i], 100*res.Win[i], 100*res.Tie[i])
		if !res.Exact {
			fmt.Fprintf(out, "  ±%.2f%%", 100*res.StdErr[i])
		}
		fmt.Fprintln(out)
	}
	return nil
}
