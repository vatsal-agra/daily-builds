package equiv

import (
	"fmt"
	"math/rand"
	"sort"
	"time"

	"gatecraft/internal/aig"
	"gatecraft/internal/sat"
)

// buildProduct fuses two single-clock designs into one sequential AIG with shared
// inputs, the registers of both ("A:name" / "B:name") and a single assertion
// "outputs agree".
func buildProduct(a, b *aig.AIG) *aig.AIG {
	m := aig.New()
	xa, xb := newXlate(a, m), newXlate(b, m)
	for _, p := range a.Inputs {
		port := aig.Port{Name: p.Name}
		for i := range p.Bits {
			port.Bits = append(port.Bits, m.AddInput(p.Name, i))
		}
		m.Inputs = append(m.Inputs, port)
		q := b.FindInput(p.Name)
		for i, bit := range p.Bits {
			xa.set(bit.ID(), port.Bits[i])
			xb.set(q.Bits[i].ID(), port.Bits[i])
		}
	}
	type pend struct {
		x    *xlate
		l    aig.Latch
		node int
	}
	var ps []pend
	for _, side := range []struct {
		g      *aig.AIG
		x      *xlate
		prefix string
	}{{a, xa, "A:"}, {b, xb, "B:"}} {
		live := side.g.LiveLatches()
		for i, l := range side.g.Latches {
			if !live[i] {
				continue
			}
			q := m.AddLatch(side.prefix+l.Name, l.Init)
			m.Latches[len(m.Latches)-1].Clock = "clk"
			side.x.set(l.Q, q)
			ps = append(ps, pend{side.x, l, len(m.Latches) - 1})
		}
	}
	for _, p := range ps {
		m.Latches[p.node].D = p.x.lit(p.l.D)
	}
	eq := aig.True
	for _, p := range a.Outputs {
		q := b.FindOutput(p.Name)
		for i := range p.Bits {
			eq = m.And(eq, m.Xnor(xa.lit(p.Bits[i]), xb.lit(q.Bits[i])))
		}
	}
	m.Asserts = []aig.Prop{{Name: "outputs_agree", Lit: eq}}
	return m
}

// clause is a disjunction of latch literals (latch index, negated).
type clause struct {
	lits [3]struct {
		latch int
		neg   bool
	}
	n int
}

// mineInvariants proposes candidate invariants (constants, 2- and 3-literal
// clauses over registers) that hold in every state visited by random simulation
// from reset, then keeps the largest subset that is *inductive* (Houdini): assuming
// all of them in an arbitrary state implies they hold after one transition. Every
// survivor also holds in the reset state, hence in all reachable states.
func mineInvariants(p *aig.AIG, seed int64) []aig.Lit {
	nl := len(p.Latches)
	if nl == 0 || nl > 400 { // mining is quadratic in the number of registers
		return nil
	}
	rng := rand.New(rand.NewSource(seed))
	// ---- 1. sample reachable states
	var samples [][]uint64 // per sample word: value of every latch (64 lanes)
	sim := aig.NewSimulator(p)
	for _, bias := range []int{50, 50, 10, 90, 25, 75} {
		sim.Reset()
		for cyc := 0; cyc < 48; cyc++ {
			for i := range p.PIs {
				var w uint64
				for b := 0; b < 64; b++ {
					if rng.Intn(100) < bias {
						w |= 1 << uint(b)
					}
				}
				sim.SetPI(i, w)
			}
			sim.Eval()
			row := make([]uint64, nl)
			copy(row, sim.State)
			samples = append(samples, row)
			sim.Clock(nil)
		}
	}
	val := func(l int, neg bool, w int) uint64 {
		v := samples[w][l]
		if neg {
			return ^v
		}
		return v
	}
	holds := func(c clause) bool {
		for w := range samples {
			var acc uint64
			for k := 0; k < c.n; k++ {
				acc |= val(c.lits[k].latch, c.lits[k].neg, w)
			}
			if acc != ^uint64(0) {
				return false
			}
		}
		return true
	}
	initState := make([]bool, nl)
	for i, l := range p.Latches {
		initState[i] = l.Init
	}
	holdsInit := func(c clause) bool {
		for k := 0; k < c.n; k++ {
			if initState[c.lits[k].latch] != c.lits[k].neg {
				return true
			}
		}
		return false
	}
	mk := func(ls ...[2]int) clause {
		var c clause
		c.n = len(ls)
		for i, l := range ls {
			c.lits[i].latch, c.lits[i].neg = l[0], l[1] == 1
		}
		return c
	}
	// ---- 2. candidate clauses
	var cands []clause
	add := func(c clause) {
		if holds(c) && holdsInit(c) {
			cands = append(cands, c)
		}
	}
	for i := 0; i < nl; i++ {
		for ni := 0; ni < 2; ni++ {
			add(mk([2]int{i, ni}))
		}
	}
	for i := 0; i < nl; i++ {
		for j := i + 1; j < nl; j++ {
			for ni := 0; ni < 2; ni++ {
				for nj := 0; nj < 2; nj++ {
					add(mk([2]int{i, ni}, [2]int{j, nj}))
				}
			}
		}
	}
	two := len(cands)
	if nl <= 40 {
		have := map[[4]int]bool{}
		for _, c := range cands[:two] {
			if c.n == 2 {
				a, b := c.lits[0], c.lits[1]
				have[[4]int{a.latch, b2i(a.neg), b.latch, b2i(b.neg)}] = true
			}
		}
		for i := 0; i < nl && len(cands) < 60000; i++ {
			for j := i + 1; j < nl; j++ {
				for k := j + 1; k < nl; k++ {
					for m := 0; m < 8; m++ {
						ni, nj, nk := m&1, m>>1&1, m>>2&1
						// skip clauses subsumed by an already-valid 2-clause
						if have[[4]int{i, ni, j, nj}] || have[[4]int{i, ni, k, nk}] || have[[4]int{j, nj, k, nk}] {
							continue
						}
						add(mk([2]int{i, ni}, [2]int{j, nj}, [2]int{k, nk}))
					}
				}
			}
		}
	}
	if len(cands) == 0 {
		return nil
	}
	// ---- 3. Houdini: two frames from a free state
	s := sat.New()
	u := NewUnroller(p, s, false)
	f0, f1 := u.Frame(0), u.Frame(1)
	litOf := func(e *aig.Encoder, c clause) []sat.Lit {
		out := make([]sat.Lit, c.n)
		for k := 0; k < c.n; k++ {
			q := aig.Lit(p.Latches[c.lits[k].latch].Q << 1)
			out[k] = e.Lit(q).NotIf(c.lits[k].neg)
		}
		return out
	}
	act0 := make([]sat.Lit, len(cands)) // activation: candidate holds at frame 0
	hold1 := make([]sat.Lit, len(cands))
	for i, c := range cands {
		a0 := sat.MkLit(s.NewVar(), false)
		s.AddClause(append([]sat.Lit{a0.Not()}, litOf(f0, c)...)...)
		act0[i] = a0
		h1 := sat.MkLit(s.NewVar(), false)
		ls := litOf(f1, c)
		s.AddClause(append([]sat.Lit{h1.Not()}, ls...)...)
		for _, l := range ls {
			s.AddClause(h1, l.Not())
		}
		hold1[i] = h1 // h1 <-> clause holds at frame 1
	}
	alive := make([]bool, len(cands))
	for i := range alive {
		alive[i] = true
	}
	for iter := 0; iter < len(cands)+1; iter++ {
		var assumps, viol []sat.Lit
		for i := range cands {
			if alive[i] {
				assumps = append(assumps, act0[i])
				viol = append(viol, hold1[i].Not())
			}
		}
		if len(viol) == 0 {
			break
		}
		bad := sat.MkLit(s.NewVar(), false)
		s.AddClause(append([]sat.Lit{bad.Not()}, viol...)...)
		s.SetConflictBudget(s.Conflicts + 200000)
		res := s.Solve(append(assumps, bad)...)
		s.AddClause(bad.Not())
		if res == sat.Unsat {
			break
		}
		if res == sat.Unknown {
			return nil // give up on invariants rather than return an unproven set
		}
		killed := 0
		for i := range cands {
			if alive[i] && !s.LitValue(hold1[i]) {
				alive[i] = false
				killed++
			}
		}
		if killed == 0 {
			return nil
		}
	}
	// ---- 4. materialise survivors as literals of p
	var out []aig.Lit
	for i, c := range cands {
		if !alive[i] {
			continue
		}
		l := aig.False
		for k := 0; k < c.n; k++ {
			q := aig.Lit(p.Latches[c.lits[k].latch].Q << 1)
			l = p.Or(l, q.NotIf(c.lits[k].neg))
		}
		out = append(out, l)
	}
	return out
}

func b2i(b bool) int {
	if b {
		return 1
	}
	return 0
}

// CheckInduction tries to prove, for all time, that two single-clock designs have
// identical outputs from reset *without* requiring matching state encodings. It
// fuses them into a product machine, infers inductive register invariants
// (Houdini over mined clauses), and runs k-induction with those as lemmas.
// Equivalent is a proof; Inconclusive means no proof was found (not "different").
func CheckInduction(a, b *aig.AIG, maxK int) (*Result, error) {
	t0 := time.Now()
	if err := CheckInterfaces(a, b); err != nil {
		return nil, err
	}
	if err := singleClock(a, b); err != nil {
		return nil, err
	}
	base, err := CheckBounded(a, b, maxK+1)
	if err != nil || base.Verdict != Equivalent {
		return base, err
	}
	p := buildProduct(a, b)
	invs := mineInvariants(p, 1)
	p.Assumes = append(p.Assumes, namedProps("inv", invs)...)
	rs, err := CheckProps(p, PropOptions{MaxDepth: maxK, Unique: true})
	if err != nil {
		return nil, err
	}
	res := &Result{Method: "k-induction on the product machine with mined inductive invariants", Obligations: 1}
	r := rs[0]
	switch r.Status {
	case PropProved:
		res.Verdict = Equivalent
		res.Notes = append(res.Notes, fmt.Sprintf("proved for all time: %d-induction using %d inductive register invariants (base case: outputs agree for %d cycles from reset)", r.Depth, len(invs), maxK+1))
	default:
		res.Verdict = Inconclusive
		res.Notes = append(res.Notes, fmt.Sprintf("not proved: the outputs agree for %d cycles but k-induction with %d mined invariants (k <= %d) is not strong enough", maxK+1, len(invs), maxK))
	}
	res.Elapsed = time.Since(t0)
	return res, nil
}

func namedProps(prefix string, ls []aig.Lit) []aig.Prop {
	out := make([]aig.Prop, len(ls))
	for i, l := range ls {
		out[i] = aig.Prop{Name: fmt.Sprintf("%s%d", prefix, i), Lit: l}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}
