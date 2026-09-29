package main

import (
	"fmt"
	"math/rand"
	"strings"
	"testing"
)

// genProgram builds a random *safe* stratified program over a small domain.
// Predicates p0..p3 (arity 2) and base e0,e1. Negation only targets e* or
// lower-numbered p*, so programs are always stratifiable.
func genProgram(r *rand.Rand) string {
	var b strings.Builder
	dom := 4
	for i := 0; i < 2; i++ {
		for k := 0; k < 4+r.Intn(6); k++ {
			fmt.Fprintf(&b, "e%d(%d,%d).\n", i, r.Intn(dom), r.Intn(dom))
		}
	}
	vars := []string{"A", "B", "C", "D"}
	for pi := 0; pi < 4; pi++ {
		for k := 0; k < 1+r.Intn(3); k++ {
			nb := 1 + r.Intn(3)
			var lits []string
			used := map[string]bool{}
			for j := 0; j < nb; j++ {
				var pred string
				if r.Intn(2) == 0 {
					pred = fmt.Sprintf("e%d", r.Intn(2))
				} else {
					pred = fmt.Sprintf("p%d", r.Intn(pi+1)) // self/lower recursion; occasionally mutual below
					if r.Intn(6) == 0 {
						pred = fmt.Sprintf("p%d", r.Intn(4)) // may create mutual recursion (positive only)
					}
				}
				v1, v2 := vars[r.Intn(4)], vars[r.Intn(4)]
				if r.Intn(8) == 0 {
					v2 = fmt.Sprint(r.Intn(dom))
				}
				used[v1], used[v2] = true, true
				lits = append(lits, fmt.Sprintf("%s(%s,%s)", pred, v1, v2))
			}
			var uv []string
			for _, v := range vars {
				if used[v] {
					uv = append(uv, v)
				}
			}
			if r.Intn(3) == 0 && pi > 0 {
				// negation on lower predicate or base
				np := fmt.Sprintf("e%d", r.Intn(2))
				if r.Intn(2) == 0 {
					np = fmt.Sprintf("p%d", r.Intn(pi))
				}
				lits = append(lits, fmt.Sprintf("not %s(%s,%s)", np, uv[r.Intn(len(uv))], uv[r.Intn(len(uv))]))
			}
			if r.Intn(4) == 0 && len(uv) >= 2 {
				ops := []string{"<", "!=", "<=", "="}
				lits = append(lits, fmt.Sprintf("%s %s %s", uv[0], ops[r.Intn(4)], uv[len(uv)-1]))
			}
			h1, h2 := uv[r.Intn(len(uv))], uv[r.Intn(len(uv))]
			fmt.Fprintf(&b, "p%d(%s,%s) :- %s.\n", pi, h1, h2, strings.Join(lits, ", "))
		}
	}
	return b.String()
}

// oracle: brute-force stratum-by-stratum fixpoint by enumerating every
// variable assignment over the domain. Shares no join code with the engine.
func oracle(p *Program, level map[string]int, count int, dom int) map[string]map[string]bool {
	db := map[string]map[string]bool{}
	get := func(p string) map[string]bool {
		if db[p] == nil {
			db[p] = map[string]bool{}
		}
		return db[p]
	}
	for _, r := range p.Rules {
		if len(r.Body) == 0 {
			t := []Val{}
			for _, a := range r.Head.Args {
				t = append(t, a.C)
			}
			get(r.Head.Pred)[tupleKey(t)] = true
		}
	}
	for lvl := 0; lvl < count; lvl++ {
		for changed := true; changed; {
			changed = false
			for _, r := range p.Rules {
				if len(r.Body) == 0 || level[r.Head.Pred] != lvl {
					continue
				}
				var names []string
				seen := map[string]bool{}
				for _, l := range r.Body {
					for _, v := range litVars(l) {
						if !seen[v] {
							seen[v] = true
							names = append(names, v)
						}
					}
				}
				total := 1
				for range names {
					total *= dom
				}
				for code := 0; code < total; code++ {
					env := map[string]Val{}
					c := code
					for _, n := range names {
						env[n] = Int(int64(c % dom))
						c /= dom
					}
					val := func(t Term) Val {
						if t.Var {
							return env[t.Name]
						}
						return t.C
					}
					ok := true
					for _, l := range r.Body {
						switch l.Kind {
						case LPos, LNeg:
							var t []Val
							for _, a := range l.Atom.Args {
								t = append(t, val(a))
							}
							in := get(l.Atom.Pred)[tupleKey(t)]
							if in != (l.Kind == LPos) {
								ok = false
							}
						case LCmp:
							a, b := val(l.L.T), val(l.R.T)
							cmp := a.Compare(b)
							res := map[string]bool{"=": cmp == 0, "!=": cmp != 0, "<": cmp < 0, "<=": cmp <= 0}[l.Op]
							ok = ok && res
						}
						if !ok {
							break
						}
					}
					if !ok {
						continue
					}
					var t []Val
					for _, a := range r.Head.Args {
						t = append(t, val(a))
					}
					k := tupleKey(t)
					if !get(r.Head.Pred)[k] {
						get(r.Head.Pred)[k] = true
						changed = true
					}
				}
			}
		}
	}
	return db
}

func TestFuzzAgainstOracle(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	nProg := 400
	if testing.Short() {
		nProg = 60
	}
	skipped, tested := 0, 0
	for it := 0; it < nProg; it++ {
		src := genProgram(r)
		prog, err := Parse(src)
		if err != nil {
			t.Fatalf("generated program does not parse: %v\n%s", err, src)
		}
		var engines [2]*Engine
		for m := 0; m < 2; m++ {
			e, err := NewEngine(prog)
			if err != nil && strings.Contains(err.Error(), "not stratifiable") {
				skipped++
				engines[0] = nil
				break
			}
			if err != nil {
				t.Fatalf("plan: %v\n%s", err, src)
			}
			e.Naive = m == 0
			if err := e.Run(); err != nil {
				t.Fatal(err)
			}
			engines[m] = e
		}
		if engines[0] == nil {
			continue
		}
		tested++
		want := oracle(prog, engines[1].Strata.Level, engines[1].Strata.Count, 4)
		for m, e := range engines {
			for pred, rel := range e.Rels {
				if len(rel.Tuples) != len(want[pred]) {
					t.Fatalf("mode naive=%v pred %s: got %d facts want %d\n%s", m == 0, pred, len(rel.Tuples), len(want[pred]), src)
				}
				for _, tu := range rel.Tuples {
					if !want[pred][tupleKey(tu)] {
						t.Fatalf("mode naive=%v: spurious %s\n%s", m == 0, tupleString(pred, tu), src)
					}
				}
			}
		}
	}
	t.Logf("tested %d programs, skipped %d unstratifiable", tested, skipped)
	if tested < nProg/2 {
		t.Fatalf("too few stratifiable programs generated")
	}
}
