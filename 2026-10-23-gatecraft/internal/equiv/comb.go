package equiv

import (
	"fmt"
	"math/big"
	"sort"
	"strings"
	"time"

	"gatecraft/internal/aig"
	"gatecraft/internal/sat"
)

// Verdict of an equivalence query.
type Verdict int

const (
	Equivalent Verdict = iota
	Different
	Inconclusive
)

func (v Verdict) String() string {
	return [...]string{"EQUIVALENT", "NOT EQUIVALENT", "INCONCLUSIVE"}[v]
}

// Obligation is one pair of functions that must agree.
type Obligation struct {
	Name string
	A, B aig.Lit // in the graphs of the first / second design
}

// Cex is a counterexample to a state-matched combinational check.
type Cex struct {
	Obligation string
	Inputs     map[string]*big.Int
	StateA     map[string]bool
	StateB     map[string]bool
	Confirmed  bool // replayed in the simulator and the obligation really differs
}

// Trace is an input sequence from the reset state.
type Trace struct {
	Inputs    []map[string]*big.Int // one map per cycle
	Fail      string                // what differs / which property failed
	Cycle     int                   // cycle at which Fail is observed
	Confirmed bool
}

// Result of a check.
type Result struct {
	Verdict     Verdict
	Method      string
	Cex         *Cex
	Trace       *Trace
	Obligations int
	Notes       []string
	Conflicts   int64
	Elapsed     time.Duration
}

func portMismatch(kind string, a, b []aig.Port) error {
	am, bm := map[string]int{}, map[string]int{}
	for _, p := range a {
		am[p.Name] = len(p.Bits)
	}
	for _, p := range b {
		bm[p.Name] = len(p.Bits)
	}
	var msgs []string
	for n, w := range am {
		if w2, ok := bm[n]; !ok {
			msgs = append(msgs, fmt.Sprintf("%s '%s' only in first design", kind, n))
		} else if w != w2 {
			msgs = append(msgs, fmt.Sprintf("%s '%s' is %d bits vs %d bits", kind, n, w, w2))
		}
	}
	for n := range bm {
		if _, ok := am[n]; !ok {
			msgs = append(msgs, fmt.Sprintf("%s '%s' only in second design", kind, n))
		}
	}
	if len(msgs) == 0 {
		return nil
	}
	sort.Strings(msgs)
	return fmt.Errorf("interfaces differ: %s", strings.Join(msgs, "; "))
}

// CheckInterfaces verifies identical port names and widths.
func CheckInterfaces(a, b *aig.AIG) error {
	if err := portMismatch("input", a.Inputs, b.Inputs); err != nil {
		return err
	}
	return portMismatch("output", a.Outputs, b.Outputs)
}

type tie struct {
	obls   []Obligation
	bindA  map[uint32]aig.Lit // A latch node -> literal in A it is assumed equal to (const or other latch)
	bindB  map[uint32]aig.Lit // B latch node -> literal in A's graph (A-side lit) it is tied to
	constA map[uint32]bool
	notes  []string
	initOK bool
}

func latchIndex(g *aig.AIG) map[string]int {
	m := map[string]int{}
	for i, l := range g.Latches {
		m[l.Name] = i
	}
	return m
}

// matchState pairs registers between two designs by name, resolving the
// optimiser's Removed records (constant / alias / dead).
func matchState(a, b *aig.AIG) (*tie, error) {
	t := &tie{bindA: map[uint32]aig.Lit{}, bindB: map[uint32]aig.Lit{}, constA: map[uint32]bool{}, initOK: true}
	ia, ib := latchIndex(a), latchIndex(b)
	liveA, liveB := a.LiveLatches(), b.LiveLatches()
	// pairs by name
	for i, la := range a.Latches {
		if !liveA[i] {
			continue
		}
		if j, ok := ib[la.Name]; ok {
			lb := b.Latches[j]
			if la.Init != lb.Init {
				t.initOK = false
				t.notes = append(t.notes, fmt.Sprintf("register %s has a different reset value (%v vs %v)", la.Name, la.Init, lb.Init))
			}
			t.bindB[lb.Q] = aig.Lit(la.Q << 1)
			t.obls = append(t.obls, Obligation{"next(" + la.Name + ")", la.D, lb.D})
		}
	}
	// registers only on one side
	oneSide := func(x, y *aig.AIG, live []bool, iy map[string]int, flip bool) error {
		for i, lx := range x.Latches {
			if !live[i] {
				continue
			}
			if _, ok := iy[lx.Name]; ok {
				continue
			}
			target, ok := y.Removed[lx.Name]
			if !ok {
				return fmt.Errorf("register %s exists only in the %s design and is not recorded as optimised away; use the bounded sequential check (-bmc N)", lx.Name, map[bool]string{false: "first", true: "second"}[flip])
			}
			switch target {
			case "dead":
				continue
			case "0", "1":
				val := target == "1"
				if lx.Init != val {
					t.initOK = false
					t.notes = append(t.notes, fmt.Sprintf("register %s is constant %s in the optimised design but resets to %v", lx.Name, target, lx.Init))
				}
				c := aig.False
				if val {
					c = aig.True
				}
				if !flip {
					t.bindA[lx.Q] = c
					t.obls = append(t.obls, Obligation{"next(" + lx.Name + ")", lx.D, c})
				} else {
					t.bindB[lx.Q] = c // resolved on the B side below
					t.obls = append(t.obls, Obligation{"next(" + lx.Name + ")", c, lx.D})
				}
			default:
				j, ok := iy[target]
				if !ok {
					return fmt.Errorf("register %s is recorded as an alias of %s, which does not exist", lx.Name, target)
				}
				ly := y.Latches[j]
				if !flip {
					// x (in A) aliased to y (in B, also in A by name)
					ja, ok := ia[target]
					if !ok {
						return fmt.Errorf("alias target %s missing from first design", target)
					}
					t.bindA[lx.Q] = aig.Lit(a.Latches[ja].Q << 1)
					t.obls = append(t.obls, Obligation{"next(" + lx.Name + ")", lx.D, ly.D})
				} else {
					if _, ok := ib[target]; !ok {
						return fmt.Errorf("alias target %s missing from second design", target)
					}
					// x in B aliased to y in A: tie B.x.Q := A.y.Q
					t.bindB[lx.Q] = aig.Lit(ly.Q << 1)
					t.obls = append(t.obls, Obligation{"next(" + lx.Name + ")", ly.D, lx.D})
				}
				if la := lx.Init; la != ly.Init {
					t.initOK = false
					t.notes = append(t.notes, fmt.Sprintf("alias %s/%s have different reset values", lx.Name, target))
				}
			}
		}
		return nil
	}
	if err := oneSide(a, b, liveA, ib, false); err != nil {
		return nil, err
	}
	if err := oneSide(b, a, liveB, ia, true); err != nil {
		return nil, err
	}
	return t, nil
}

func propObligations(a, b *aig.AIG) ([]Obligation, error) {
	var out []Obligation
	for _, pair := range []struct {
		kind   string
		pa, pb []aig.Prop
	}{{"assert", a.Asserts, b.Asserts}, {"assume", a.Assumes, b.Assumes}} {
		bm := map[string]aig.Lit{}
		for _, p := range pair.pb {
			bm[p.Name] = p.Lit
		}
		if len(pair.pa) != len(pair.pb) {
			return nil, fmt.Errorf("designs have a different number of %s properties (%d vs %d)", pair.kind, len(pair.pa), len(pair.pb))
		}
		for _, p := range pair.pa {
			l, ok := bm[p.Name]
			if !ok {
				return nil, fmt.Errorf("%s property %s missing from the second design", pair.kind, p.Name)
			}
			out = append(out, Obligation{pair.kind + " " + p.Name, p.Lit, l})
		}
	}
	return out, nil
}

// CheckComb proves that two designs agree on every output, property and
// next-state function for all inputs and all (state-matched) states. When it
// answers Equivalent it implies sequential equivalence from reset, by induction
// on the matched state (reset values are checked to agree).
func CheckComb(a, b *aig.AIG) (*Result, error) {
	t0 := time.Now()
	if err := CheckInterfaces(a, b); err != nil {
		return nil, err
	}
	tie, err := matchState(a, b)
	if err != nil {
		return nil, err
	}
	res := &Result{Method: "SAT miter with state matching", Notes: tie.notes}
	var obls []Obligation
	for _, p := range a.Outputs {
		q := b.FindOutput(p.Name)
		for i := range p.Bits {
			obls = append(obls, Obligation{fmt.Sprintf("output %s[%d]", p.Name, i), p.Bits[i], q.Bits[i]})
		}
	}
	po, err := propObligations(a, b)
	if err != nil {
		return nil, err
	}
	obls = append(obls, po...)
	obls = append(obls, tie.obls...)
	res.Obligations = len(obls)
	if !tie.initOK {
		res.Verdict = Inconclusive
		res.Notes = append(res.Notes, "state matching impossible because reset values differ; use the bounded sequential check")
		res.Elapsed = time.Since(t0)
		return res, nil
	}

	s := sat.New()
	encA, encB := aig.NewEncoder(a, s), aig.NewEncoder(b, s)
	encB.FreeVar = func(id uint32) sat.Lit {
		n := b.Nodes[id]
		if n.Kind == aig.KInput {
			pi := b.PIs[n.Idx]
			return encA.Lit(a.FindInput(pi.Port).Bits[pi.Bit])
		}
		return sat.MkLit(s.NewVar(), false)
	}
	resolveA := func(l aig.Lit) sat.Lit { return encA.Lit(l) }
	constLit := func(l aig.Lit) sat.Lit { // constants only
		v := sat.MkLit(s.NewVar(), false)
		s.AddClause(v)
		return v.NotIf(l == aig.False)
	}
	for q, l := range tie.bindA {
		if l.ID() == 0 {
			encA.Bind(q, constLit(l))
		} else {
			encA.Bind(q, resolveA(l))
		}
	}
	for q, l := range tie.bindB {
		if l.ID() == 0 {
			encB.Bind(q, constLit(l))
		} else {
			encB.Bind(q, resolveA(l))
		}
	}
	for _, o := range obls {
		x, y := encA.Lit(o.A), encB.Lit(o.B)
		if x == y {
			continue
		}
		d := sat.MkLit(s.NewVar(), false)
		s.AddClause(d.Not(), x, y)
		s.AddClause(d.Not(), x.Not(), y.Not())
		switch s.Solve(d) {
		case sat.Unsat:
			s.AddClause(d.Not())
			s.AddClause(x.Not(), y)
			s.AddClause(x, y.Not())
		case sat.Sat:
			cex := &Cex{Obligation: o.Name, Inputs: map[string]*big.Int{}, StateA: map[string]bool{}, StateB: map[string]bool{}}
			for _, p := range a.Inputs {
				v := new(big.Int)
				for i, bit := range p.Bits {
					if s.LitValue(encA.Lit(bit)) {
						v.SetBit(v, i, 1)
					}
				}
				cex.Inputs[p.Name] = v
			}
			for _, l := range a.Latches {
				cex.StateA[l.Name] = s.LitValue(encA.Lit(aig.Lit(l.Q << 1)))
			}
			for _, l := range b.Latches {
				cex.StateB[l.Name] = s.LitValue(encB.Lit(aig.Lit(l.Q << 1)))
			}
			cex.Confirmed = replayCex(a, b, o, cex)
			res.Verdict, res.Cex = Different, cex
			res.Conflicts, res.Elapsed = s.Conflicts, time.Since(t0)
			return res, nil
		default:
			res.Verdict = Inconclusive
			res.Notes = append(res.Notes, "SAT solver gave up on "+o.Name)
			res.Elapsed = time.Since(t0)
			return res, nil
		}
	}
	res.Verdict = Equivalent
	res.Conflicts, res.Elapsed = s.Conflicts, time.Since(t0)
	return res, nil
}

// replayCex re-evaluates both designs in the bit-parallel simulator with the
// counterexample's inputs and states and checks that the obligation differs.
func replayCex(a, b *aig.AIG, o Obligation, c *Cex) bool {
	sa, sb := aig.NewSimulator(a), aig.NewSimulator(b)
	load := func(g *aig.AIG, s *aig.Simulator, state map[string]bool) {
		for i, pi := range g.PIs {
			var w uint64
			if v := c.Inputs[pi.Port]; v != nil && v.Bit(pi.Bit) == 1 {
				w = ^uint64(0)
			}
			s.SetPI(i, w)
		}
		for i, l := range g.Latches {
			if state[l.Name] {
				s.State[i] = ^uint64(0)
			} else {
				s.State[i] = 0
			}
		}
		s.Eval()
	}
	load(a, sa, c.StateA)
	load(b, sb, c.StateB)
	return sa.Lit(o.A)&1 != sb.Lit(o.B)&1
}
