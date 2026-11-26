package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
)

const usage = `bluff — a poker game-theory lab

  bluff solve <kuhn|leduc> [-iters N] [-out strat.json]   solve with CFR+, print exploitability curve
  bluff exploit <kuhn|leduc> <strategy|bot> [-iters N]    exploitability of a strategy + best response
  bluff show <kuhn|leduc> [-iters N] [-strategy S]        print the strategy table
  bluff equity [-board ..] [-dead ..] [-n N] r1 r2 ...    hold'em equity of hands/ranges
  bluff play <kuhn|leduc> [-strategy S] [-iters N]        play against the solved strategy
  bluff match <kuhn|leduc> -vs BOT [-hands N]             simulate solved strategy vs a bot
  bluff pushfold [-stack BB]                              heads-up push/fold Nash ranges
  bluff report -out report.html                           write the HTML report

Strategy specs: "solved" (default), a bot name (` + "station maniac nit random" + `), or a JSON file.
`

func run(args []string) error { return runTo(args, os.Stdout, os.Stdin) }

func runTo(args []string, out io.Writer, in io.Reader) error {
	if len(args) == 0 || args[0] == "help" || args[0] == "-h" || args[0] == "--help" {
		fmt.Fprint(out, usage)
		return nil
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "solve":
		return cmdSolve(rest, out)
	case "exploit":
		return cmdExploit(rest, out)
	case "show":
		return cmdShow(rest, out)
	case "equity":
		return cmdEquity(rest, out)
	case "play":
		return cmdPlay(rest, out, in)
	case "match":
		return cmdMatch(rest, out)
	case "pushfold":
		return cmdPushFold(rest, out)
	case "report":
		return cmdReport(rest, out)
	}
	return fmt.Errorf("unknown command %q\n\n%s", cmd, usage)
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	return fs
}

// parseInterleaved lets flags appear before or after positional args.
func parseInterleaved(fs *flag.FlagSet, args []string) ([]string, error) {
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		args = fs.Args()
		if len(args) == 0 {
			return pos, nil
		}
		pos = append(pos, args[0])
		args = args[1:]
	}
}

func loadGame(name string) (Game, *Tree, error) {
	g, err := GameByName(name)
	if err != nil {
		return nil, nil, err
	}
	t, err := Compile(g)
	return g, t, err
}

func cmdSolve(args []string, out io.Writer) error {
	fs := newFlags("solve")
	iters := fs.Int("iters", 2000, "CFR+ iterations")
	save := fs.String("out", "", "write strategy JSON here")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("usage: bluff solve <kuhn|leduc> [-iters N] [-out file]")
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	_, t, err := loadGame(pos[0])
	if err != nil {
		return err
	}
	s := NewSolver(t)
	fmt.Fprintf(out, "%s: %d nodes, %d info sets\n", t.Game, len(t.Nodes), len(t.Sets))
	fmt.Fprintf(out, "%8s  %-14s %s\n", "iter", "exploitability", "(chips/hand; 0 = Nash)")
	next := 1
	for k := 1; k <= *iters; k++ {
		s.Step()
		if k == next || k == *iters {
			e, _, _ := t.Exploitability(s.Average())
			fmt.Fprintf(out, "%8d  %-14.6f\n", k, e)
			for next <= k {
				next *= 2
			}
		}
	}
	prof := s.Average()
	fmt.Fprintf(out, "game value for player 0 (first to act): %+.5f\n", t.Value(prof))
	if *save != "" {
		if err := SaveStrategy(*save, t.ToFile(prof, *iters)); err != nil {
			return err
		}
		fmt.Fprintf(out, "saved strategy to %s\n", *save)
	}
	return nil
}

func cmdExploit(args []string, out io.Writer) error {
	fs := newFlags("exploit")
	iters := fs.Int("iters", 2000, "iterations when spec is 'solved'")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 2 {
		return fmt.Errorf("usage: bluff exploit <game> <strategy|bot>")
	}
	_, t, err := loadGame(pos[0])
	if err != nil {
		return err
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	prof, err := ResolveStrategy(t, pos[1], *iters)
	if err != nil {
		return err
	}
	e, b0, b1 := t.Exploitability(prof)
	fmt.Fprintf(out, "strategy %q in %s\n", pos[1], t.Game)
	fmt.Fprintf(out, "  exploitability        %.6f chips/hand\n", e)
	fmt.Fprintf(out, "  best response as P0   %+.6f (vs this strategy as P1)\n", b0)
	fmt.Fprintf(out, "  best response as P1   %+.6f (vs this strategy as P0)\n", b1)
	return nil
}

func cmdShow(args []string, out io.Writer) error {
	fs := newFlags("show")
	iters := fs.Int("iters", 2000, "iterations when strategy is 'solved'")
	spec := fs.String("strategy", "solved", "strategy spec")
	pos, err := parseInterleaved(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return fmt.Errorf("usage: bluff show <game> [-strategy S]")
	}
	_, t, err := loadGame(pos[0])
	if err != nil {
		return err
	}
	if *iters < 1 {
		return fmt.Errorf("-iters must be ≥ 1")
	}
	prof, err := ResolveStrategy(t, *spec, *iters)
	if err != nil {
		return err
	}
	idx := make([]int, len(t.Sets))
	for i := range idx {
		idx[i] = i
	}
	sort.Slice(idx, func(a, b int) bool { return t.Sets[idx[a]].Key < t.Sets[idx[b]].Key })
	for _, i := range idx {
		s := t.Sets[i]
		var parts []string
		for a, an := range s.Actions {
			parts = append(parts, fmt.Sprintf("%s %5.1f%%", an, 100*prof[i][a]))
		}
		fmt.Fprintf(out, "%-14s %s\n", s.Key, strings.Join(parts, "  "))
	}
	return nil
}
