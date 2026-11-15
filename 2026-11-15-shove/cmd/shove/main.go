// Command shove is a Sokoban toolkit: solve, generate, verify, replay, export, bench.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"shove/sok"
)

const usage = `shove — a Sokoban toolkit

usage:
  shove solve  <pack.txt> [-n N] [-nodes N] [-timeout 30s] [-q]   push-optimal solve (all levels, or level N)
  shove gen    [-w 9 -h 8 -boxes 3 -seed 1 -attempts 200 -walls 0.12 -min-pushes 0 -o out.txt]
  shove pack   [-count 8 -seed 1 ... gen flags] -o pack.txt        generate a pack sorted easy -> hard
  shove check  <pack.txt> <moves|-f movesfile> [-n N]              verify an LURD move string
  shove replay <pack.txt> [-n N] [-moves STR] [-delay 150ms]       ASCII animation of a solution
  shove html   <pack.txt>... -o game.html [-title T]               export a playable game with verified solutions
  shove bench  <pack.txt> [-md] [-nodes N]                         solver statistics table

Pack format: XSB ('#' wall, '@' player, '$' box, '.' goal, '*' box on goal, '+' player on goal);
levels separated by blank lines; ';name' lines name the level that follows.`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	args := os.Args[2:]
	switch os.Args[1] {
	case "solve":
		err = cmdSolve(args)
	case "gen":
		err = cmdGen(args, false)
	case "pack":
		err = cmdGen(args, true)
	case "check":
		err = cmdCheck(args)
	case "replay":
		err = cmdReplay(args)
	case "html":
		err = cmdHTML(args)
	case "bench":
		err = cmdBench(args)
	case "-h", "--help", "help":
		fmt.Println(usage)
		return
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s\n", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

// splitArgs lets flags appear before or after positionals.
func splitArgs(fs *flag.FlagSet, args []string) ([]string, error) {
	var pos []string
	for len(args) > 0 {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		args = fs.Args()
		if len(args) > 0 {
			pos = append(pos, args[0])
			args = args[1:]
		}
	}
	return pos, nil
}

func loadPack(path string) ([]*sok.Level, error) {
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, err
	}
	lvs, err := sok.ParsePack(string(b))
	if err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return lvs, nil
}

func pick(lvs []*sok.Level, n int) ([]*sok.Level, []int, error) {
	if n == 0 {
		idx := make([]int, len(lvs))
		for i := range idx {
			idx[i] = i + 1
		}
		return lvs, idx, nil
	}
	if n < 1 || n > len(lvs) {
		return nil, nil, fmt.Errorf("level %d out of range (pack has %d levels)", n, len(lvs))
	}
	return []*sok.Level{lvs[n-1]}, []int{n}, nil
}

func fsNew(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

func cmdSolve(args []string) error {
	fs := fsNew("solve")
	n := fs.Int("n", 0, "level number (default: all)")
	nodes := fs.Int("nodes", 0, "max expanded nodes (0 = unlimited)")
	to := fs.Duration("timeout", 30*time.Second, "per-level time limit")
	q := fs.Bool("q", false, "quiet: only print the move strings")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("solve needs exactly one pack file")
	}
	lvs, err := loadPack(pos[0])
	if err != nil {
		return err
	}
	sel, idx, err := pick(lvs, *n)
	if err != nil {
		return err
	}
	failed := 0
	for i, lv := range sel {
		sol, err := sok.Solve(lv, sok.Options{MaxNodes: *nodes, Timeout: *to})
		if err != nil {
			failed++
			fmt.Printf("#%d %s: %v\n", idx[i], lv.Name, err)
			continue
		}
		if _, verr := lv.Verify(sol.Moves); verr != nil {
			return fmt.Errorf("internal error: solver output for #%d failed verification: %v", idx[i], verr)
		}
		if *q {
			fmt.Println(sol.Moves)
			continue
		}
		fmt.Printf("#%d %s\n  pushes %d (optimal)  moves %d  expanded %d  generated %d  %s  [%s]\n  %s\n",
			idx[i], lv.Name, sol.Pushes, sol.WalkMoves, sol.Expanded, sol.Generated,
			sol.Elapsed.Round(time.Microsecond), sok.Rate(sol), sol.Moves)
	}
	if failed > 0 {
		return fmt.Errorf("%d level(s) not solved", failed)
	}
	return nil
}

func cmdGen(args []string, pack bool) error {
	fs := fsNew("gen")
	o := sok.GenOptions{}
	fs.IntVar(&o.W, "w", 9, "grid width")
	fs.IntVar(&o.H, "h", 8, "grid height")
	fs.IntVar(&o.Boxes, "boxes", 3, "number of boxes")
	fs.Int64Var(&o.Seed, "seed", 1, "RNG seed")
	fs.IntVar(&o.Attempts, "attempts", 200, "candidates to rate per level")
	fs.IntVar(&o.Pulls, "pulls", 0, "random pulls per candidate (default 40*boxes)")
	fs.Float64Var(&o.WallDens, "walls", 0.12, "interior wall density")
	fs.IntVar(&o.MinPushes, "min-pushes", 0, "minimum optimal pushes")
	fs.IntVar(&o.MaxNodes, "nodes", 0, "solver node budget per candidate")
	out := fs.String("o", "", "output file (default stdout)")
	count := fs.Int("count", 8, "pack: number of levels")
	if _, err := splitArgs(fs, args); err != nil {
		return err
	}
	var sb strings.Builder
	if !pack {
		count = new(int)
		*count = 1
	}
	var gens []*sok.Generated
	for i := 0; i < *count; i++ {
		oo := o
		oo.Seed = o.Seed + int64(i)
		g, err := sok.Generate(oo)
		if err != nil {
			if pack {
				fmt.Fprintf(os.Stderr, "seed %d: %v (skipped)\n", oo.Seed, err)
				continue
			}
			return err
		}
		gens = append(gens, g)
	}
	if len(gens) == 0 {
		return sok.ErrNoCandidate
	}
	if pack {
		for i := 1; i < len(gens); i++ { // insertion sort by difficulty
			for j := i; j > 0 && gens[j].Solution.Expanded < gens[j-1].Solution.Expanded; j-- {
				gens[j], gens[j-1] = gens[j-1], gens[j]
			}
		}
	}
	for i, g := range gens {
		if pack {
			g.Level.Name = fmt.Sprintf("%d. %s", i+1, g.Level.Name)
		}
		fmt.Fprintf(&sb, ";%s\n%s\n", g.Level.Name, g.Level)
		fmt.Fprintf(os.Stderr, "generated %-48s expanded=%-6d (best of %d rated)\n", g.Level.Name, g.Solution.Expanded, g.Rated)
	}
	if *out == "" {
		fmt.Print(sb.String())
		return nil
	}
	return os.WriteFile(*out, []byte(sb.String()), 0o644)
}

func cmdCheck(args []string) error {
	fs := fsNew("check")
	n := fs.Int("n", 1, "level number")
	f := fs.String("f", "", "read moves from file")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	moves := ""
	switch {
	case *f != "":
		b, err := os.ReadFile(*f)
		if err != nil {
			return err
		}
		moves = string(b)
		if len(pos) != 1 {
			return errors.New("check -f needs one pack file")
		}
	case len(pos) == 2:
		moves = pos[1]
	default:
		return errors.New("usage: check <pack> <moves> | check <pack> -f file")
	}
	lvs, err := loadPack(pos[0])
	if err != nil {
		return err
	}
	sel, _, err := pick(lvs, *n)
	if err != nil {
		return err
	}
	r, err := sel[0].Verify(strings.TrimSpace(moves))
	if err != nil {
		return err
	}
	fmt.Printf("OK: solved %q in %d moves, %d pushes\n", sel[0].Name, r.Moves, r.Pushes)
	return nil
}

func cmdReplay(args []string) error {
	fs := fsNew("replay")
	n := fs.Int("n", 1, "level number")
	mv := fs.String("moves", "", "moves to replay (default: solve first)")
	delay := fs.Duration("delay", 150*time.Millisecond, "frame delay (0 = print all frames)")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("replay needs one pack file")
	}
	lvs, err := loadPack(pos[0])
	if err != nil {
		return err
	}
	sel, _, err := pick(lvs, *n)
	if err != nil {
		return err
	}
	lv := sel[0]
	moves := *mv
	if moves == "" {
		sol, err := sok.Solve(lv, sok.Options{Timeout: 30 * time.Second})
		if err != nil {
			return err
		}
		moves = sol.Moves
	}
	if _, err := lv.Replay(moves); err != nil {
		return err
	}
	for i := 0; i <= len(moves); i++ {
		r, _ := lv.Replay(moves[:i])
		if *delay > 0 && i > 0 {
			fmt.Print("\x1b[", lv.H+2, "A")
		}
		fmt.Printf("%s%d/%d  moves %d  pushes %d\n\n", lv.Format(r.Boxes, r.Player), i, len(moves), r.Moves, r.Pushes)
		if *delay > 0 {
			time.Sleep(*delay)
		}
	}
	return nil
}

func cmdHTML(args []string) error {
	fs := fsNew("html")
	out := fs.String("o", "shove.html", "output file")
	title := fs.String("title", "Shove", "page title")
	to := fs.Duration("timeout", 60*time.Second, "per-level solve limit")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) == 0 {
		return errors.New("html needs at least one pack file")
	}
	var all []*sok.Level
	for _, p := range pos {
		lvs, err := loadPack(p)
		if err != nil {
			return err
		}
		all = append(all, lvs...)
	}
	page, lv, err := sok.BuildHTML(*title, all, nil, sok.Options{Timeout: *to})
	if err != nil {
		return err
	}
	if err := os.WriteFile(*out, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d levels, %d KB), every solution verified\n", *out, len(lv), len(page)/1024)
	return nil
}

func cmdBench(args []string) error {
	fs := fsNew("bench")
	md := fs.Bool("md", false, "markdown table")
	nodes := fs.Int("nodes", 2_000_000, "node budget per level")
	ablate := fs.Bool("ablate", false, "also run with the weaker no-matching heuristic and no freeze pruning")
	pos, err := splitArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 1 {
		return errors.New("bench needs one pack file")
	}
	lvs, err := loadPack(pos[0])
	if err != nil {
		return err
	}
	sep := " | "
	if !*md {
		sep = "  "
	}
	row := func(cells ...string) {
		if *md {
			fmt.Println("| " + strings.Join(cells, sep) + " |")
		} else {
			fmt.Println(strings.Join(cells, sep))
		}
	}
	hdr := []string{"level", "boxes", "pushes", "moves", "expanded", "time", "rating"}
	if *ablate {
		hdr = append(hdr, "exp(no-match)", "exp(no-freeze)")
	}
	row(hdr...)
	if *md {
		row(strings.Split(strings.Repeat("---,", len(hdr)), ",")[:len(hdr)]...)
	}
	for _, lv := range lvs {
		sol, err := sok.Solve(lv, sok.Options{MaxNodes: *nodes})
		cells := []string{lv.Name, fmt.Sprint(len(lv.Boxes))}
		if err != nil {
			cells = append(cells, "-", "-", "-", "-", err.Error())
		} else {
			cells = append(cells, fmt.Sprint(sol.Pushes), fmt.Sprint(sol.WalkMoves), fmt.Sprint(sol.Expanded),
				sol.Elapsed.Round(time.Microsecond).String(), sok.Rate(sol))
		}
		if *ablate {
			for _, o := range []sok.Options{{MaxNodes: *nodes, NoMatching: true}, {MaxNodes: *nodes, NoFreeze: true}} {
				s2, e2 := sok.Solve(lv, o)
				if e2 != nil {
					cells = append(cells, "budget")
				} else {
					cells = append(cells, fmt.Sprint(s2.Expanded))
				}
			}
		}
		row(cells...)
	}
	return nil
}
