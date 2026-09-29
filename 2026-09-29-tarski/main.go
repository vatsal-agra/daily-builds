package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
)

const usage = `tarski — a Datalog engine (semi-naive, stratified negation, aggregates, provenance)

usage:
  tarski run   [-naive] [-stats] [-dump] FILE|-     evaluate; print answers to '?-' queries
  tarski check FILE|-                                 validate + show the strata
  tarski why   FILE|- 'pred(a, d)'                    proof tree for a derived fact
  tarski bench [-n N]                                 naive vs semi-naive on generated graphs
  tarski repl  [FILE]                                 interactive session
`

func readSrc(path string) (string, error) {
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	return string(b), err
}

func load(path string) (*Engine, error) {
	src, err := readSrc(path)
	if err != nil {
		return nil, err
	}
	return build(src)
}

func build(src string) (*Engine, error) {
	prog, err := Parse(src)
	if err != nil {
		return nil, err
	}
	return NewEngine(prog)
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, out, errw io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(errw, usage)
		return 2
	}
	fail := func(err error) int { fmt.Fprintln(errw, "error:", err); return 1 }
	switch args[0] {
	case "run":
		fs := flag.NewFlagSet("run", flag.ContinueOnError)
		fs.SetOutput(errw)
		naive := fs.Bool("naive", false, "use naive evaluation")
		stats := fs.Bool("stats", false, "print evaluation statistics")
		dump := fs.Bool("dump", false, "print every derived relation")
		if err := fs.Parse(args[1:]); err != nil {
			return 2
		}
		if fs.NArg() != 1 {
			fmt.Fprint(errw, usage)
			return 2
		}
		e, err := load(fs.Arg(0))
		if err != nil {
			return fail(err)
		}
		e.Naive = *naive
		if err := e.Run(); err != nil {
			return fail(err)
		}
		for _, q := range e.Prog.Queries {
			fmt.Fprintf(out, "?- %s.\n", litsString(q.Body))
			res, err := e.Ask(q)
			if err != nil {
				return fail(err)
			}
			fmt.Fprint(out, res.Format())
		}
		if *dump {
			dumpAll(out, e)
		}
		if *stats {
			printStats(out, e)
		}
	case "check":
		if len(args) != 2 {
			fmt.Fprint(errw, usage)
			return 2
		}
		e, err := load(args[1])
		if err != nil {
			return fail(err)
		}
		fmt.Fprint(out, e.Strata.Describe(e.Arity))
		fmt.Fprintf(out, "ok: %d rules, %d queries\n", len(e.Prog.Rules), len(e.Prog.Queries))
	case "why":
		if len(args) != 3 {
			fmt.Fprint(errw, usage)
			return 2
		}
		e, err := load(args[1])
		if err != nil {
			return fail(err)
		}
		if err := e.Run(); err != nil {
			return fail(err)
		}
		pred, t, err := ParseFact(args[2])
		if err != nil {
			return fail(err)
		}
		s, err := e.Why(pred, t)
		if err != nil {
			return fail(err)
		}
		fmt.Fprint(out, s)
	case "bench":
		fs := flag.NewFlagSet("bench", flag.ContinueOnError)
		fs.SetOutput(errw)
		n := fs.Int("n", 120, "graph size")
		if err := fs.Parse(args[1:]); err != nil {
			return 2
		}
		if *n < 2 || *n > 5000 {
			return fail(fmt.Errorf("-n must be between 2 and 5000"))
		}
		if err := bench(out, *n); err != nil {
			return fail(err)
		}
	case "repl":
		var e0 string
		if len(args) > 1 {
			s, err := readSrc(args[1])
			if err != nil {
				return fail(err)
			}
			e0 = s
		}
		repl(os.Stdin, out, e0)
	default:
		fmt.Fprint(errw, usage)
		return 2
	}
	return 0
}

func litsString(ls []Literal) string {
	parts := make([]string, len(ls))
	for i, l := range ls {
		parts[i] = l.String()
	}
	return strings.Join(parts, ", ")
}

func sortedPreds(e *Engine) []string {
	var ps []string
	for p := range e.Rels {
		ps = append(ps, p)
	}
	sort.Strings(ps)
	return ps
}

func dumpAll(out io.Writer, e *Engine) {
	for _, p := range sortedPreds(e) {
		fs := e.Facts(p)
		fmt.Fprintf(out, "%% %s/%d (%d facts)\n", p, e.Arity[p], len(fs))
		for _, t := range fs {
			fmt.Fprintf(out, "%s.\n", tupleString(p, t))
		}
	}
}

func printStats(out io.Writer, e *Engine) {
	mode := "semi-naive"
	if e.Naive {
		mode = "naive"
	}
	total := 0
	for _, r := range e.Rels {
		total += len(r.Tuples)
	}
	fmt.Fprintf(out, "%% %s: %d strata, %d iterations, %d join probes, %d derived, %d facts total, %v\n",
		mode, e.Strata.Count, e.Stats.Iterations, e.Stats.Probes, e.Stats.Derived, total, e.Stats.Elapsed)
}

// ---- REPL ----

func repl(in io.Reader, out io.Writer, initial string) {
	var src strings.Builder
	src.WriteString(initial)
	var eng *Engine
	rebuild := func() bool {
		e, err := build(src.String())
		if err != nil {
			fmt.Fprintln(out, "error:", err)
			return false
		}
		if err := e.Run(); err != nil {
			fmt.Fprintln(out, "error:", err)
			return false
		}
		eng = e
		return true
	}
	if initial != "" {
		if rebuild() {
			fmt.Fprintf(out, "loaded %d rules\n", len(eng.Prog.Rules))
		}
	} else {
		rebuild()
	}
	fmt.Fprintln(out, "tarski repl — enter facts/rules ending in '.', queries as '?- p(X).', or :help")
	sc := bufio.NewScanner(in)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for {
		fmt.Fprint(out, "> ")
		if !sc.Scan() {
			fmt.Fprintln(out)
			return
		}
		line := strings.TrimSpace(sc.Text())
		switch {
		case line == "":
		case line == ":quit" || line == ":q":
			return
		case line == ":help":
			fmt.Fprintln(out, ":why FACT   :facts PRED   :strata   :program   :reset   :quit\nAnything else is parsed as facts, rules, or '?-' queries.")
		case line == ":reset":
			src.Reset()
			rebuild()
			fmt.Fprintln(out, "cleared")
		case line == ":program":
			fmt.Fprint(out, src.String())
		case line == ":strata":
			if eng != nil {
				fmt.Fprint(out, eng.Strata.Describe(eng.Arity))
			}
		case strings.HasPrefix(line, ":facts"):
			p := strings.TrimSpace(strings.TrimPrefix(line, ":facts"))
			if eng == nil || eng.Rels[p] == nil {
				fmt.Fprintln(out, "unknown predicate", p)
				break
			}
			for _, t := range eng.Facts(p) {
				fmt.Fprintf(out, "%s.\n", tupleString(p, t))
			}
		case strings.HasPrefix(line, ":why"):
			pred, t, err := ParseFact(strings.TrimPrefix(line, ":why"))
			if err != nil {
				fmt.Fprintln(out, "error:", err)
				break
			}
			s, err := eng.Why(pred, t)
			if err != nil {
				fmt.Fprintln(out, "error:", err)
				break
			}
			fmt.Fprint(out, s)
		case strings.HasPrefix(line, "?-"):
			p, err := Parse(line)
			if err != nil {
				fmt.Fprintln(out, "error:", err)
				break
			}
			if eng == nil {
				fmt.Fprintln(out, "error: program does not currently evaluate; fix it first")
				break
			}
			for _, q := range p.Queries {
				// queries may mention predicates the program never defined
				if res, err := eng.Ask(q); err != nil {
					fmt.Fprintln(out, "error:", err)
				} else {
					fmt.Fprint(out, res.Format())
				}
			}
		default:
			old := src.String()
			src.WriteString(line + "\n")
			if rebuild() {
				fmt.Fprintln(out, "ok")
			} else {
				src.Reset()
				src.WriteString(old)
				rebuild()
			}
		}
	}
}

// ---- bench ----

func bench(out io.Writer, n int) error {
	type gen struct {
		name string
		src  string
	}
	tc := "path(X,Y) :- edge(X,Y).\npath(X,Z) :- path(X,Y), edge(Y,Z).\n"
	tcNonLinear := "path(X,Y) :- edge(X,Y).\npath(X,Z) :- path(X,Y), path(Y,Z).\n"
	var chain, ring, tree, rnd strings.Builder
	for i := 0; i < n-1; i++ {
		fmt.Fprintf(&chain, "edge(%d,%d).\n", i, i+1)
	}
	for i := 0; i < n; i++ {
		fmt.Fprintf(&ring, "edge(%d,%d).\n", i, (i+1)%n)
	}
	for i := 1; i < n; i++ {
		fmt.Fprintf(&tree, "edge(%d,%d).\n", (i-1)/2, i)
	}
	seed := uint64(12345)
	nextRand := func() int {
		seed = seed*6364136223846793005 + 1442695040888963407
		return int(seed >> 33)
	}
	for i := 0; i < n*2; i++ {
		fmt.Fprintf(&rnd, "edge(%d,%d).\n", nextRand()%n, nextRand()%n)
	}
	gens := []gen{
		{"chain, linear TC", chain.String() + tc},
		{"ring, linear TC", ring.String() + tc},
		{"binary tree, linear TC", tree.String() + tc},
		{"random graph, linear TC", rnd.String() + tc},
		{"chain, non-linear TC", chain.String() + tcNonLinear},
	}
	fmt.Fprintf(out, "%-26s %8s | %6s %10s %9s | %6s %10s %9s | %s\n", "workload (n="+fmt.Sprint(n)+")", "facts", "iters", "probes", "time", "iters", "probes", "time", "speedup(probes)")
	fmt.Fprintf(out, "%-26s %8s | %-27s | %-27s |\n", "", "", "naive", "semi-naive")
	for _, g := range gens {
		var res [2]*Engine
		for m := 0; m < 2; m++ {
			e, err := build(g.src)
			if err != nil {
				return err
			}
			e.Naive = m == 0
			if err := e.Run(); err != nil {
				return err
			}
			res[m] = e
		}
		if !sameModel(res[0], res[1]) {
			return fmt.Errorf("MODEL MISMATCH between naive and semi-naive on %q", g.name)
		}
		nv, sn := res[0].Stats, res[1].Stats
		fmt.Fprintf(out, "%-26s %8d | %6d %10d %9v | %6d %10d %9v | %.1fx\n", g.name, len(res[1].Rels["path"].Tuples),
			nv.Iterations, nv.Probes, nv.Elapsed.Round(1000), sn.Iterations, sn.Probes, sn.Elapsed.Round(1000), float64(nv.Probes)/float64(max(sn.Probes, 1)))
	}
	fmt.Fprintln(out, "all workloads: naive and semi-naive computed identical models")
	return nil
}

func sameModel(a, b *Engine) bool {
	if len(a.Rels) != len(b.Rels) {
		return false
	}
	for p, ra := range a.Rels {
		rb := b.Rels[p]
		if rb == nil || len(ra.Tuples) != len(rb.Tuples) {
			return false
		}
		for k := range ra.set {
			if _, ok := rb.set[k]; !ok {
				return false
			}
		}
	}
	return true
}
