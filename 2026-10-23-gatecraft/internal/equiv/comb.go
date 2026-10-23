package equiv

import (
	"fmt"
	"math/big"
	"sort"
	"strings"
	"time"

	"gatecraft/internal/aig"
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
	A, B aig.Lit // in the graphs of the first / second design (or both in one graph, see Side)
	Side int     // 0: A is in the first design, B in the second; 1: both in the first; 2: both in the second
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

// binding says what a latch output is tied to: a literal of the first design (inA)
// or of its own design.
type binding struct {
	lit aig.Lit
	inA bool
}

type tie struct {
	obls   []Obligation
	bindA  map[uint32]aig.Lit // first-design latch node -> literal in the first design
	bindB  map[uint32]binding // second-design latch node -> literal
	notes  []string
	initOK bool
}

// relevantState returns, per design, the latches that matter to the comparison: those
// observable in either design plus everything their next-state functions need,
// matched by name across the designs (to a fixpoint).
func relevantState(a, b *aig.AIG) [2][]bool {
	gs := [2]*aig.AIG{a, b}
	idx := [2]map[string]int{latchIndex(a), latchIndex(b)}
	rel := [2][]bool{make([]bool, len(a.Latches)), make([]bool, len(b.Latches))}
	for k := 0; k < 2; k++ {
		for i, l := range gs[k].LiveLatches() {
			rel[k][i] = l
		}
	}
	for changed := true; changed; {
		changed = false
		for k := 0; k < 2; k++ {
			// a latch relevant on one side is relevant on the other if it exists there
			for i, l := range gs[k].Latches {
				if rel[k][i] {
					if j, ok := idx[1-k][l.Name]; ok && !rel[1-k][j] {
						rel[1-k][j] = true
						changed = true
					}
				}
			}
			for i, l := range gs[k].LatchClosure(rel[k]) {
				if l && !rel[k][i] {
					rel[k][i] = true
					changed = true
				}
			}
		}
	}
	return rel
}

func latchIndex(g *aig.AIG) map[string]int {
	m := map[string]int{}
	for i, l := range g.Latches {
		m[l.Name] = i
	}
	return m
}

// matchState pairs registers between two designs by name and resolves the
// optimiser's Removed records (constant / alias / unobservable) into ties that
// the SAT check assumes and, at the same time, proves inductive.
func matchState(a, b *aig.AIG) (*tie, error) {
	t := &tie{bindA: map[uint32]aig.Lit{}, bindB: map[uint32]binding{}, initOK: true}
	idx := [2]map[string]int{latchIndex(a), latchIndex(b)}
	gs := [2]*aig.AIG{a, b}
	live := relevantState(a, b)
	sideName := [2]string{"first", "second"}
	badInit := func(format string, args ...any) {
		t.initOK = false
		t.notes = append(t.notes, fmt.Sprintf(format, args...))
	}
	// registers present in both designs
	for i, la := range a.Latches {
		if !live[0][i] {
			continue
		}
		if j, ok := idx[1][la.Name]; ok {
			lb := b.Latches[j]
			if la.Init != lb.Init {
				badInit("register %s has a different reset value (%v vs %v)", la.Name, la.Init, lb.Init)
			}
			t.bindB[lb.Q] = binding{aig.Lit(la.Q << 1), true}
			t.obls = append(t.obls, Obligation{"next(" + la.Name + ")", la.D, lb.D, 0})
		}
	}
	// registers present on one side only: the other side must record what happened to them
	for x := 0; x < 2; x++ {
		y := 1 - x
		gx, gy := gs[x], gs[y]
		for i, lx := range gx.Latches {
			if !live[x][i] {
				continue
			}
			if _, ok := idx[y][lx.Name]; ok {
				continue
			}
			target, ok := gy.Removed[lx.Name]
			if !ok {
				return nil, fmt.Errorf("register %s exists only in the %s design and is not recorded as optimised away; use the bounded sequential check (-bmc N)", lx.Name, sideName[x])
			}
			q := aig.Lit(lx.Q << 1)
			var tied aig.Lit // what lx.Q equals, in gx's graph
			var obl Obligation
			side := 1 + x // intra-design obligation side
			switch target {
			case "dead":
				continue
			case "0", "1":
				tied = aig.False
				if target == "1" {
					tied = aig.True
				}
				if lx.Init != (target == "1") {
					badInit("register %s is constant %s in the other design but resets to %v", lx.Name, target, lx.Init)
				}
				obl = Obligation{"next(" + lx.Name + ")", lx.D, tied, side}
			default:
				jx, okx := idx[x][target]
				if !okx {
					return nil, fmt.Errorf("register %s is recorded as an alias of %s, which does not exist in the %s design", lx.Name, target, sideName[x])
				}
				lt := gx.Latches[jx]
				tied = aig.Lit(lt.Q << 1)
				if lx.Init != lt.Init {
					badInit("registers %s and %s are merged but have different reset values", lx.Name, target)
				}
				if jy, ok := idx[y][target]; ok { // survivor exists on both sides
					ly := gy.Latches[jy]
					if x == 0 {
						obl = Obligation{"next(" + lx.Name + ")", lx.D, ly.D, 0}
					} else {
						obl = Obligation{"next(" + lx.Name + ")", ly.D, lx.D, 0}
					}
				} else { // alias of an unobservable register: prove the two next-states equal in place
					if gy.Removed[target] != "dead" {
						return nil, fmt.Errorf("register %s aliases %s, which the other design neither contains nor records as removed", lx.Name, target)
					}
					obl = Obligation{"next(" + lx.Name + ")", lx.D, lt.D, side}
				}
			}
			if x == 0 {
				t.bindA[lx.Q] = tied
			} else {
				t.bindB[lx.Q] = binding{tied, false}
			}
			_ = q
			t.obls = append(t.obls, obl)
		}
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
			out = append(out, Obligation{pair.kind + " " + p.Name, p.Lit, l, 0})
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
			name := "output " + p.Name
			if len(p.Bits) > 1 {
				name = fmt.Sprintf("output %s[%d]", p.Name, i)
			}
			obls = append(obls, Obligation{name, p.Bits[i], q.Bits[i], 0})
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

	cm := buildCombMiter(a, b, obls, tie)
	idx, model, conflicts := solveMiter(cm.m, cm.bits)
	res.Conflicts = conflicts
	res.Elapsed = time.Since(t0)
	switch {
	case idx == -1:
		res.Verdict = Equivalent
	case idx == -2:
		res.Verdict = Inconclusive
		res.Notes = append(res.Notes, "SAT solver gave up (conflict budget exhausted)")
	default:
		o := obls[idx]
		cex := &Cex{Obligation: o.Name, Inputs: map[string]*big.Int{}}
		for _, p := range a.Inputs {
			cex.Inputs[p.Name] = model[p.Name]
		}
		cex.StateA, cex.StateB = stateValues(a, b, tie, model)
		cex.Confirmed = replayCex(a, b, o, cex)
		res.Verdict, res.Cex = Different, cex
	}
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
	switch o.Side {
	case 0:
		return sa.Lit(o.A)&1 != sb.Lit(o.B)&1
	case 1:
		return sa.Lit(o.A)&1 != sa.Lit(o.B)&1
	}
	return sb.Lit(o.A)&1 != sb.Lit(o.B)&1
}
