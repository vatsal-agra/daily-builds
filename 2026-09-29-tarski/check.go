package main

import (
	"fmt"
	"sort"
	"strings"
)

// Check validates arities and ground facts. Range-restriction (safety) is
// checked while planning each rule, since it depends on evaluation order.
func Check(p *Program) (map[string]int, error) {
	arity := map[string]int{}
	use := func(a Atom, line int) error {
		if n, ok := arity[a.Pred]; ok && n != len(a.Args) {
			return fmt.Errorf("line %d: predicate %s used with %d arguments but earlier with %d", line, a.Pred, len(a.Args), n)
		}
		if len(a.Args) > 60 {
			return fmt.Errorf("line %d: predicate %s has too many arguments (max 60)", line, a.Pred)
		}
		arity[a.Pred] = len(a.Args)
		return nil
	}
	for _, r := range p.Rules {
		if err := use(r.Head, r.Line); err != nil {
			return nil, err
		}
		if len(r.Body) == 0 {
			for _, t := range r.Head.Args {
				if t.Var || t.Agg != "" {
					return nil, fmt.Errorf("line %d: fact %s must be ground (no variables or aggregates)", r.Line, r.Head)
				}
			}
		}
		for _, l := range r.Body {
			if l.Kind != LCmp {
				if err := use(l.Atom, r.Line); err != nil {
					return nil, err
				}
			}
		}
	}
	for _, q := range p.Queries {
		for _, l := range q.Body {
			if l.Kind != LCmp {
				if err := use(l.Atom, q.Line); err != nil {
					return nil, err
				}
			}
		}
	}
	return arity, nil
}

type edge struct {
	to     string
	strict bool // negation or aggregation
	neg    bool
}

// Stratification is the result of dependency analysis.
type Stratification struct {
	Level map[string]int // predicate -> stratum
	Count int
}

// Stratify builds the predicate dependency graph, finds SCCs (Tarjan) and
// rejects programs where a negation/aggregation edge lies on a cycle.
func Stratify(p *Program, arity map[string]int) (*Stratification, error) {
	deps := map[string][]edge{} // head -> body preds it depends on
	for pred := range arity {
		deps[pred] = nil
	}
	for _, r := range p.Rules {
		for _, l := range r.Body {
			if l.Kind == LCmp {
				continue
			}
			deps[r.Head.Pred] = append(deps[r.Head.Pred], edge{l.Atom.Pred, l.Kind == LNeg || r.HasAgg(), l.Kind == LNeg})
		}
	}
	names := make([]string, 0, len(deps))
	for n := range deps {
		names = append(names, n)
	}
	sort.Strings(names)

	index, low := map[string]int{}, map[string]int{}
	on := map[string]bool{}
	comp := map[string]int{}
	var stack []string
	counter, ncomp := 0, 0
	var strong func(v string)
	strong = func(v string) {
		index[v], low[v] = counter, counter
		counter++
		stack = append(stack, v)
		on[v] = true
		for _, e := range deps[v] {
			if _, seen := index[e.to]; !seen {
				strong(e.to)
				if low[e.to] < low[v] {
					low[v] = low[e.to]
				}
			} else if on[e.to] && index[e.to] < low[v] {
				low[v] = index[e.to]
			}
		}
		if low[v] == index[v] {
			for {
				w := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				on[w] = false
				comp[w] = ncomp
				if w == v {
					break
				}
			}
			ncomp++
		}
	}
	for _, n := range names {
		if _, ok := index[n]; !ok {
			strong(n)
		}
	}
	for _, n := range names {
		for _, e := range deps[n] {
			if e.strict && comp[e.to] == comp[n] {
				what := "negation"
				if !e.neg {
					what = "aggregation"
				}
				return nil, fmt.Errorf("program is not stratifiable: %s of %s inside a recursive cycle: %s",
					what, e.to, cyclePath(deps, n, e.to, comp[n], comp, e.neg))
			}
		}
	}
	// Tarjan numbers components in reverse topological order: dependencies get lower ids.
	level := make([]int, ncomp)
	for c := 0; c < ncomp; c++ {
		for _, n := range names {
			if comp[n] != c {
				continue
			}
			for _, e := range deps[n] {
				if comp[e.to] == c {
					continue
				}
				d := level[comp[e.to]]
				if e.strict {
					d++
				}
				if d > level[c] {
					level[c] = d
				}
			}
		}
	}
	s := &Stratification{Level: map[string]int{}}
	for _, n := range names {
		s.Level[n] = level[comp[n]]
		if level[comp[n]]+1 > s.Count {
			s.Count = level[comp[n]] + 1
		}
	}
	return s, nil
}

// cyclePath renders head -> not target -> ... -> head inside one SCC.
func cyclePath(deps map[string][]edge, head, target string, c int, comp map[string]int, neg bool) string {
	first := head + " -> "
	if neg {
		first += "not "
	} else {
		first += "agg "
	}
	first += target
	// BFS from target back to head within the component
	prev := map[string]string{target: ""}
	q := []string{target}
	for len(q) > 0 && prev[head] == "" && target != head {
		v := q[0]
		q = q[1:]
		for _, e := range deps[v] {
			if comp[e.to] == c {
				if _, ok := prev[e.to]; !ok {
					prev[e.to] = v
					q = append(q, e.to)
				}
			}
		}
	}
	if target == head {
		return first
	}
	var path []string
	for v := head; v != target && v != ""; v = prev[v] {
		path = append(path, v)
	}
	for i, j := 0, len(path)-1; i < j; i, j = i+1, j-1 {
		path[i], path[j] = path[j], path[i]
	}
	if len(path) > 0 && path[len(path)-1] == head {
		path = path[:len(path)-1]
	}
	out := first
	for _, v := range path {
		out += " -> " + v
	}
	return out + " -> " + head
}

// Describe lists predicates per stratum.
func (s *Stratification) Describe(arity map[string]int) string {
	by := make([][]string, s.Count)
	for p, l := range s.Level {
		by[l] = append(by[l], fmt.Sprintf("%s/%d", p, arity[p]))
	}
	var b strings.Builder
	for i, ps := range by {
		sort.Strings(ps)
		fmt.Fprintf(&b, "stratum %d: %s\n", i, strings.Join(ps, ", "))
	}
	return b.String()
}
