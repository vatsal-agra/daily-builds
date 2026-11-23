// Command tabula: generate, check, solve, verify and render school timetables.
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"tabula/tabula"
)

const usage = `tabula - school timetabling solver

  tabula gen     [-seed N -groups N -teachers N -rooms N -days N -periods N -load F] -o problem.json
  tabula check   problem.json                       validate + explain impossibilities
  tabula solve   problem.json -o sol.json [-html f.html] [-ics dir] [-seed N -time 10s -iters N]
  tabula verify  problem.json sol.json              independent hard/soft re-check
  tabula resolve problem.json prev.json -o new.json [-html f.html]   minimal-disruption re-solve
  tabula show    problem.json sol.json              print the timetable as text
`

func die(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "tabula: "+f+"\n", a...)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Print(usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "gen":
		cmdGen(args)
	case "check":
		cmdCheck(args)
	case "solve":
		cmdSolve(args, false)
	case "resolve":
		cmdSolve(args, true)
	case "verify":
		cmdVerify(args)
	case "show":
		cmdShow(args)
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "tabula: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
}

// parse allows flags after positional arguments (tabula solve p.json -o x).
func parse(fs *flag.FlagSet, args []string, wantPos int) []string {
	var pos []string
	for len(args) > 0 {
		if err := fs.Parse(args); err != nil {
			os.Exit(2)
		}
		args = fs.Args()
		if len(args) > 0 {
			pos = append(pos, args[0])
			args = args[1:]
		}
	}
	if len(pos) != wantPos {
		die("expected %d positional argument(s), got %d", wantPos, len(pos))
	}
	return pos
}

func cmdGen(args []string) {
	fs := flag.NewFlagSet("gen", flag.ExitOnError)
	c := tabula.GenConfig{}
	fs.Int64Var(&c.Seed, "seed", 1, "seed")
	fs.IntVar(&c.Groups, "groups", 8, "student groups")
	fs.IntVar(&c.Teachers, "teachers", 10, "teachers")
	fs.IntVar(&c.Rooms, "rooms", 7, "rooms")
	fs.IntVar(&c.Days, "days", 5, "days")
	fs.IntVar(&c.Periods, "periods", 8, "periods per day")
	fs.Float64Var(&c.Load, "load", 0.6, "fraction of each group's week to fill")
	out := fs.String("o", "", "output file (required)")
	parse(fs, args, 0)
	if *out == "" {
		die("gen: -o is required")
	}
	if c.Groups < 1 || c.Teachers < 1 || c.Rooms < 1 || c.Load <= 0 || c.Load > 0.95 {
		die("gen: need groups,teachers,rooms >= 1 and 0 < load <= 0.95")
	}
	p := tabula.Generate(c)
	if err := tabula.SaveJSON(*out, p); err != nil {
		die("%v", err)
	}
	fmt.Printf("wrote %s: %d groups, %d teachers, %d rooms, %d lessons (feasible by construction)\n", *out, len(p.Groups), len(p.Teachers), len(p.Rooms), len(p.Lessons))
}

func load(path string) (*tabula.Problem, *tabula.Instance) {
	p, err := tabula.LoadProblem(path)
	if err != nil {
		die("%v", err)
	}
	in, err := tabula.Compile(p)
	if err != nil {
		die("%v", err)
	}
	return p, in
}

func cmdCheck(args []string) {
	fs := flag.NewFlagSet("check", flag.ExitOnError)
	pos := parse(fs, args, 1)
	p, in := load(pos[0])
	ds := in.Diagnose()
	fmt.Printf("%s: %d days x %d periods, %d teachers, %d rooms, %d groups, %d lessons -> %d sessions\n",
		p.Name, p.Days, p.Periods, len(p.Teachers), len(p.Rooms), len(p.Groups), len(p.Lessons), len(in.Events))
	for _, d := range ds {
		fmt.Println("  " + d.String())
	}
	if tabula.HasFatal(ds) {
		os.Exit(1)
	}
	fmt.Println("no impossibility proof found (the solver will settle the rest)")
}

func cmdSolve(args []string, resolve bool) {
	fs := flag.NewFlagSet("solve", flag.ExitOnError)
	out := fs.String("o", "", "solution JSON output")
	html := fs.String("html", "", "write the HTML viewer here")
	ics := fs.String("ics", "", "write .ics calendars into this directory")
	start := fs.String("start", "", "first Monday for .ics (YYYY-MM-DD), default next Monday")
	seed := fs.Int64("seed", 1, "random seed")
	dur := fs.Duration("time", 5*time.Second, "optimisation time budget")
	iters := fs.Int("iters", 0, "fixed annealing iterations (deterministic; overrides -time)")
	quiet := fs.Bool("q", false, "quiet")
	want := 1
	if resolve {
		want = 2
	}
	pos := parse(fs, args, want)
	p, in := load(pos[0])
	opt := tabula.Options{Seed: *seed, AnnealFor: *dur, AnnealIters: *iters}
	var prevSol *tabula.Solution
	if resolve {
		var err error
		prevSol, err = tabula.LoadSolution(pos[1])
		if err != nil {
			die("%v", err)
		}
		opt.Previous, err = in.PartialFromSolution(prevSol)
		if err != nil {
			die("previous solution: %v", err)
		}
	}
	a, rep, err := in.Solve(opt)
	for _, d := range rep.Diagnostics {
		if !*quiet {
			fmt.Println("  " + d.String())
		}
	}
	if err != nil {
		die("%v", err)
	}
	sol := in.ToSolution(a)
	if !*quiet {
		fmt.Printf("feasible after %d search nodes (%d restarts); cost %d -> %d in %d annealing steps (%d moves, %d swaps accepted); %s\n",
			rep.Construct.Nodes, rep.Construct.Restarts, rep.Initial, sol.Cost, rep.Anneal.Iters, rep.Anneal.Moves, rep.Anneal.Swaps, rep.Elapsed.Round(time.Millisecond))
		for _, k := range tabula.CatNames {
			if v := sol.Breakdown[k]; v != 0 {
				fmt.Printf("    %-14s %d\n", k, v)
			}
		}
		if resolve {
			fmt.Printf("sessions moved vs previous timetable: %d of %d\n", in.CountMoved(opt.Previous, a), len(in.Events))
		}
	}
	viol, c2, _ := tabula.Verify(p, sol, prevSol)
	if len(viol) > 0 || (c2 != sol.Cost) {
		die("internal error: verifier disagrees (%d violations, cost %d vs %d): %s", len(viol), c2, sol.Cost, strings.Join(viol, "; "))
	}
	if *out != "" {
		if err := tabula.SaveJSON(*out, sol); err != nil {
			die("%v", err)
		}
	}
	if *html != "" {
		if err := tabula.WriteHTML(*html, p, sol); err != nil {
			die("%v", err)
		}
		fmt.Println("wrote", *html)
	}
	if *ics != "" {
		n, err := tabula.WriteICS(*ics, p, sol, *start)
		if err != nil {
			die("%v", err)
		}
		fmt.Printf("wrote %d calendar files to %s\n", n, *ics)
	}
}

func cmdVerify(args []string) {
	fs := flag.NewFlagSet("verify", flag.ExitOnError)
	pos := parse(fs, args, 2)
	p, _ := load(pos[0])
	s, err := tabula.LoadSolution(pos[1])
	if err != nil {
		die("%v", err)
	}
	viol, cost, bd := tabula.Verify(p, s, nil)
	if len(viol) > 0 {
		fmt.Printf("INVALID: %d hard-constraint violations\n", len(viol))
		for _, v := range viol {
			fmt.Println("  - " + v)
		}
		os.Exit(1)
	}
	fmt.Printf("VALID: %d sessions, 0 hard violations, soft cost %d\n", len(s.Placements), cost)
	for _, k := range tabula.CatNames {
		if bd[k] != 0 {
			fmt.Printf("    %-14s %d\n", k, bd[k])
		}
	}
}

func cmdShow(args []string) {
	fs := flag.NewFlagSet("show", flag.ExitOnError)
	pos := parse(fs, args, 2)
	p, _ := load(pos[0])
	s, err := tabula.LoadSolution(pos[1])
	if err != nil {
		die("%v", err)
	}
	fmt.Print(tabula.TextGrid(p, s))
}
