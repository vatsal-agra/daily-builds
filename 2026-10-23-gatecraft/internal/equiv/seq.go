package equiv

import (
	"fmt"
	"math/big"
	"strings"
	"time"

	"gatecraft/internal/aig"
	"gatecraft/internal/sat"
)

// CheckBounded unrolls both designs from reset with shared inputs and searches
// for a cycle (< depth) at which some output differs. A found trace is a real
// counterexample; "no difference" is a guarantee only up to the bound.
func CheckBounded(a, b *aig.AIG, depth int) (*Result, error) {
	t0 := time.Now()
	if err := CheckInterfaces(a, b); err != nil {
		return nil, err
	}
	if err := singleClock(a, b); err != nil {
		return nil, err
	}
	m, diffs := buildBoundedMiter(a, b, depth)
	res := &Result{Method: fmt.Sprintf("bounded sequential miter, %d cycles from reset", depth)}
	for t, d := range diffs {
		if d == aig.False {
			continue
		}
		res.Obligations++
		idx, model, conf := solveMiter(m, []aig.Lit{d})
		res.Conflicts += conf
		switch idx {
		case -2:
			res.Verdict = Inconclusive
			res.Notes = append(res.Notes, fmt.Sprintf("SAT budget exhausted at cycle %d", t))
			res.Elapsed = time.Since(t0)
			return res, nil
		case 0:
			tr := &Trace{Cycle: t}
			for k := 0; k <= t; k++ {
				in := map[string]*big.Int{}
				for _, p := range a.Inputs {
					in[p.Name] = model[fmt.Sprintf("%s@%d", p.Name, k)]
					if in[p.Name] == nil {
						in[p.Name] = new(big.Int)
					}
				}
				tr.Inputs = append(tr.Inputs, in)
			}
			tr.Confirmed = replayDiff(a, b, tr)
			tr.Fail = firstDifferingOutput(a, b, tr)
			res.Verdict, res.Trace = Different, tr
			res.Elapsed = time.Since(t0)
			return res, nil
		}
	}
	res.Verdict = Equivalent
	res.Notes = append(res.Notes, fmt.Sprintf("outputs agree for the first %d cycles after reset (bounded guarantee only)", depth))
	res.Elapsed = time.Since(t0)
	return res, nil
}

// firstDifferingOutput replays the trace and names an output bit that differs in the last cycle.
func firstDifferingOutput(a, b *aig.AIG, tr *Trace) string {
	sa, sb := aig.NewSimulator(a), aig.NewSimulator(b)
	for t, in := range tr.Inputs {
		for _, side := range []struct {
			g *aig.AIG
			s *aig.Simulator
		}{{a, sa}, {b, sb}} {
			for i, pi := range side.g.PIs {
				var w uint64
				if v := in[pi.Port]; v != nil && v.Bit(pi.Bit) == 1 {
					w = ^uint64(0)
				}
				side.s.SetPI(i, w)
			}
			side.s.Eval()
		}
		if t == len(tr.Inputs)-1 {
			for _, p := range a.Outputs {
				q := b.FindOutput(p.Name)
				for i := range p.Bits {
					if sa.Lit(p.Bits[i])&1 != sb.Lit(q.Bits[i])&1 {
						if len(p.Bits) == 1 {
							return "output " + p.Name
						}
						return fmt.Sprintf("output %s[%d]", p.Name, i)
					}
				}
			}
		}
		sa.Clock(nil)
		sb.Clock(nil)
	}
	return ""
}

// replayDiff drives both designs through the trace in the simulator and confirms
// that the failing output differs at the final cycle.
func replayDiff(a, b *aig.AIG, tr *Trace) bool {
	sa, sb := aig.NewSimulator(a), aig.NewSimulator(b)
	for t, in := range tr.Inputs {
		apply := func(g *aig.AIG, s *aig.Simulator) {
			for i, pi := range g.PIs {
				var w uint64
				if v := in[pi.Port]; v != nil && v.Bit(pi.Bit) == 1 {
					w = ^uint64(0)
				}
				s.SetPI(i, w)
			}
			s.Eval()
		}
		apply(a, sa)
		apply(b, sb)
		if t == len(tr.Inputs)-1 {
			for _, p := range a.Outputs {
				q := b.FindOutput(p.Name)
				for i := range p.Bits {
					if sa.Lit(p.Bits[i])&1 != sb.Lit(q.Bits[i])&1 {
						return true
					}
				}
			}
			return false
		}
		sa.Clock(nil)
		sb.Clock(nil)
	}
	return false
}

// ---------------------------------------------------------------- properties

// PropStatus of one assert.
type PropStatus int

const (
	PropProved PropStatus = iota
	PropFailed
	PropBounded // no counterexample up to the depth, but no inductive proof
)

func (p PropStatus) String() string {
	return [...]string{"PROVED", "FAILED", "HOLDS (bounded)"}[p]
}

// PropResult is the verdict for one assertion.
type PropResult struct {
	Name   string
	Status PropStatus
	Depth  int    // proved by k-induction with this k, or bound explored, or failing cycle
	Trace  *Trace // for failures
}

// PropOptions control CheckProps.
type PropOptions struct {
	MaxDepth int
	Unique   bool // add simple-path (pairwise distinct state) constraints to the induction step
}

// CheckProps runs bounded model checking and k-induction over all assert
// properties (with every assume property holding in every cycle).
func CheckProps(g *aig.AIG, opt PropOptions) ([]PropResult, error) {
	if len(g.Asserts) == 0 {
		return nil, fmt.Errorf("design has no 'assert property' statements")
	}
	if err := singleClock(g); err != nil {
		return nil, err
	}
	if opt.MaxDepth <= 0 {
		opt.MaxDepth = 20
	}
	n := len(g.Asserts)
	results := make([]PropResult, n)
	for i, a := range g.Asserts {
		results[i] = PropResult{Name: a.Name, Status: PropBounded, Depth: opt.MaxDepth}
	}
	failed := make([]bool, n)

	// base case: BMC from reset
	bs := sat.New()
	bu := NewUnroller(g, bs, true)
	// step case: free initial state
	ss := sat.New()
	su := NewUnroller(g, ss, false)
	latchLits := func(u *Unroller, t int) []sat.Lit {
		var r []sat.Lit
		live := g.LiveLatches()
		for i, l := range g.Latches {
			if live[i] {
				r = append(r, u.Frame(t).Lit(aig.Lit(l.Q<<1)))
			}
		}
		return r
	}
	proved := false
	for k := 0; k <= opt.MaxDepth && !proved; k++ {
		// ---- base: frame k
		eb := bu.Frame(k)
		for _, as := range g.Assumes {
			bs.AddClause(eb.Lit(as.Lit))
		}
		baseUnknown := false
		for i, a := range g.Asserts {
			if failed[i] {
				continue
			}
			bs.SetConflictBudget(bs.Conflicts + 500000)
			switch bs.Solve(eb.Lit(a.Lit).Not()) {
			case sat.Sat:
				failed[i] = true
				tr := &Trace{Cycle: k, Fail: a.Name}
				for t := 0; t <= k; t++ {
					tr.Inputs = append(tr.Inputs, bu.Inputs(t))
				}
				tr.Confirmed = replayProp(g, tr, i)
				results[i] = PropResult{Name: a.Name, Status: PropFailed, Depth: k, Trace: tr}
			case sat.Unknown:
				baseUnknown = true
			}
		}
		// ---- step: frame k from a free state; assume all live asserts held in frames < k
		es := su.Frame(k)
		for _, as := range g.Assumes {
			ss.AddClause(es.Lit(as.Lit))
		}
		if opt.Unique {
			cur := latchLits(su, k)
			for j := 0; j < k; j++ {
				prev := latchLits(su, j)
				var xs []sat.Lit
				for q := range cur {
					x := sat.MkLit(ss.NewVar(), false)
					ss.AddClause(x.Not(), cur[q], prev[q])
					ss.AddClause(x.Not(), cur[q].Not(), prev[q].Not())
					xs = append(xs, x)
				}
				ss.AddClause(xs...)
			}
		}
		var viol []sat.Lit
		active := 0
		for i, a := range g.Asserts {
			if failed[i] {
				continue
			}
			active++
			viol = append(viol, es.Lit(a.Lit).Not())
		}
		if active == 0 {
			break
		}
		d := sat.MkLit(ss.NewVar(), false)
		ss.AddClause(append([]sat.Lit{d.Not()}, viol...)...)
		ss.SetConflictBudget(ss.Conflicts + 500000)
		if ss.Solve(d) == sat.Unsat && !baseUnknown {
			// every non-failed property is inductive at depth k and the base case held up to k
			for i := range results {
				if !failed[i] {
					results[i] = PropResult{Name: results[i].Name, Status: PropProved, Depth: k}
				}
			}
			proved = true
		}
		for i, a := range g.Asserts {
			if !failed[i] {
				ss.AddClause(es.Lit(a.Lit))
			}
		}
	}
	return results, nil
}

// replayProp drives the simulator with the trace and confirms that assertion idx is false at the last cycle.
func replayProp(g *aig.AIG, tr *Trace, idx int) bool {
	s := aig.NewSimulator(g)
	for t, in := range tr.Inputs {
		for i, pi := range g.PIs {
			var w uint64
			if v := in[pi.Port]; v != nil && v.Bit(pi.Bit) == 1 {
				w = ^uint64(0)
			}
			s.SetPI(i, w)
		}
		s.Eval()
		for _, as := range g.Assumes {
			if s.Lit(as.Lit)&1 == 0 {
				return false // trace violates an assumption: not a legal counterexample
			}
		}
		if t == len(tr.Inputs)-1 {
			return s.Lit(g.Asserts[idx].Lit)&1 == 0
		}
		s.Clock(nil)
	}
	return false
}

// FormatInputs renders an input assignment compactly.
func FormatInputs(g *aig.AIG, m map[string]*big.Int) string {
	out := ""
	clocks := map[string]bool{}
	for _, c := range g.Clocks() {
		clocks[strings.SplitN(c, "[", 2)[0]] = true
	}
	for _, p := range g.Inputs {
		if clocks[p.Name] {
			continue // clocks are implicit in cycle-based traces
		}
		if v, ok := m[p.Name]; ok {
			if out != "" {
				out += " "
			}
			out += fmt.Sprintf("%s=%s", p.Name, v.Text(10))
		}
	}
	return out
}
