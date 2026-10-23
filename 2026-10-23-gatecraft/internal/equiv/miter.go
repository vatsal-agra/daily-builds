package equiv

import (
	"fmt"
	"math/big"

	"gatecraft/internal/aig"
	"gatecraft/internal/sat"
)

// ConflictBudget bounds the SAT effort per miter output after SAT sweeping; hitting it
// yields an INCONCLUSIVE verdict instead of an unbounded run.
var ConflictBudget int64 = 3_000_000

// xlate copies logic of one design into a shared, structurally hashed miter
// graph. Because both designs land in the same hash table, identical
// sub-structure collapses to the same node and most of a miter vanishes before
// the SAT solver is ever called.
type xlate struct {
	g, m *aig.AIG
	memo []aig.Lit
}

func newXlate(g, m *aig.AIG) *xlate {
	x := &xlate{g: g, m: m, memo: make([]aig.Lit, len(g.Nodes))}
	for i := range x.memo {
		x.memo[i] = aig.Undef
	}
	x.memo[0] = aig.False
	return x
}

func (x *xlate) set(node uint32, l aig.Lit) { x.memo[node] = l }

func (x *xlate) lit(l aig.Lit) aig.Lit {
	id := l.ID()
	if x.memo[id] == aig.Undef {
		n := x.g.Nodes[id]
		if n.Kind != aig.KAnd {
			panic(fmt.Sprintf("equiv: unbound source node %d (kind %d)", id, n.Kind))
		}
		x.memo[id] = x.m.And(x.lit(n.A), x.lit(n.B))
	}
	return x.memo[id].NotIf(l.Neg())
}

// freshInput adds a single-bit named input port to the miter.
func freshInput(m *aig.AIG, name string) aig.Lit {
	l := m.AddInput(name, 0)
	m.Inputs = append(m.Inputs, aig.Port{Name: name, Bits: []aig.Lit{l}})
	return l
}

// solveMiter decides each miter bit: it returns the index of the first
// satisfiable (differing) bit together with the model's input values, -1 if every
// bit is unsatisfiable (proved), or -2 if the solver gave up. Easy bits are
// tried directly; whatever is left is SAT-swept (FRAIG) to merge internal
// equivalences before a second, larger attempt.
func solveMiter(m *aig.AIG, bits []aig.Lit) (idx int, model map[string]*big.Int, conflicts int64) {
	attempt := func(g *aig.AIG, bs []aig.Lit, only []int, budget int64) (found int, mdl map[string]*big.Int, hard []int, conf int64) {
		s := sat.New()
		enc := aig.NewEncoder(g, s)
		if only == nil {
			for i := range bs {
				only = append(only, i)
			}
		}
		for _, i := range only {
			b := bs[i]
			if b == aig.False {
				continue
			}
			s.SetConflictBudget(s.Conflicts + budget)
			switch s.Solve(enc.Lit(b)) {
			case sat.Sat:
				mdl = map[string]*big.Int{}
				for _, p := range g.Inputs {
					v := new(big.Int)
					for k, bit := range p.Bits {
						if s.LitValue(enc.Lit(bit)) {
							v.SetBit(v, k, 1)
						}
					}
					mdl[p.Name] = v
				}
				return i, mdl, nil, s.Conflicts
			case sat.Unknown:
				hard = append(hard, i)
				continue
			}
			s.AddClause(enc.Lit(b).Not())
		}
		return -1, nil, hard, s.Conflicts
	}
	found, mdl, hard, conf := attempt(m, bits, nil, 20_000)
	conflicts = conf
	if found >= 0 {
		return found, mdl, conflicts
	}
	if len(hard) == 0 {
		return -1, nil, conflicts
	}
	m.Outputs = []aig.Port{{Name: "miter", Bits: bits}}
	m2, _ := aig.Fraig(m, 1)
	found, mdl, hard, conf = attempt(m2, m2.Outputs[0].Bits, hard, ConflictBudget)
	conflicts += conf
	switch {
	case found >= 0:
		return found, mdl, conflicts
	case len(hard) > 0:
		return -2, nil, conflicts
	}
	return -1, nil, conflicts
}

func bitOn(m map[string]*big.Int, name string) bool {
	v := m[name]
	return v != nil && v.Bit(0) == 1
}

// ----------------------------------------------------------------- combinational miter

type combMiter struct {
	m     *aig.AIG
	bits  []aig.Lit
	obls  []Obligation
	freeA map[string]bool // names of latches given free variables (for CEX state extraction)
}

func buildCombMiter(a, b *aig.AIG, obls []Obligation, tie *tie) *combMiter {
	m := aig.New()
	cm := &combMiter{m: m, obls: obls}
	xa, xb := newXlate(a, m), newXlate(b, m)
	// shared primary inputs
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
	// state: free variables unless tied
	side := [2]*xlate{xa, xb}
	graphs := [2]*aig.AIG{a, b}
	live := relevantState(a, b)
	bound := func(s int, node uint32) (aig.Lit, bool, bool) { // lit, inFirst, ok
		if s == 0 {
			l, ok := tie.bindA[node]
			return l, true, ok
		}
		bd, ok := tie.bindB[node]
		return bd.lit, bd.inA, ok
	}
	var resolve func(s int, node uint32)
	resolve = func(s int, node uint32) {
		x := side[s]
		if x.memo[node] != aig.Undef {
			return
		}
		if tgt, inA, ok := bound(s, node); ok {
			xs, gs := x, graphs[s]
			if inA {
				xs, gs = xa, a
			}
			if tgt.ID() == 0 {
				x.set(node, tgt)
				return
			}
			if gs.Nodes[tgt.ID()].Kind == aig.KLatch {
				ts := s
				if inA {
					ts = 0
				}
				resolve(ts, tgt.ID())
			}
			x.set(node, xs.lit(tgt))
			return
		}
		name := graphs[s].Latches[graphs[s].Nodes[node].Idx].Name
		x.set(node, freshInput(m, fmt.Sprintf("$%c:%s", 'A'+s, name)))
	}
	for s := 0; s < 2; s++ {
		for i, l := range graphs[s].Latches {
			if live[s][i] {
				resolve(s, l.Q)
			}
		}
	}
	for _, o := range obls {
		var la, lb aig.Lit
		switch o.Side {
		case 0:
			la, lb = xa.lit(o.A), xb.lit(o.B)
		case 1:
			la, lb = xa.lit(o.A), xa.lit(o.B)
		default:
			la, lb = xb.lit(o.A), xb.lit(o.B)
		}
		cm.bits = append(cm.bits, m.Xor(la, lb))
	}
	return cm
}

// stateValues evaluates every latch of both designs under a model of the
// miter's free variables, following the ties used to build the miter.
func stateValues(a, b *aig.AIG, tie *tie, model map[string]*big.Int) (sa, sb map[string]bool) {
	graphs := [2]*aig.AIG{a, b}
	cache := map[[2]uint32]bool{}
	var val func(side int, node uint32) bool
	val = func(side int, node uint32) bool {
		key := [2]uint32{uint32(side), node}
		if v, ok := cache[key]; ok {
			return v
		}
		var v bool
		var tgt aig.Lit
		bound, inA := false, true
		if side == 0 {
			tgt, bound = tie.bindA[node]
		} else {
			var bd binding
			bd, bound = tie.bindB[node]
			tgt, inA = bd.lit, bd.inA
		}
		switch {
		case !bound:
			g := graphs[side]
			v = bitOn(model, fmt.Sprintf("$%c:%s", 'A'+side, g.Latches[g.Nodes[node].Idx].Name))
		case tgt == aig.False:
			v = false
		case tgt == aig.True:
			v = true
		default:
			ts := side
			if inA {
				ts = 0
			}
			v = val(ts, tgt.ID()) != tgt.Neg()
		}
		cache[key] = v
		return v
	}
	sa, sb = map[string]bool{}, map[string]bool{}
	for _, l := range a.Latches {
		sa[l.Name] = val(0, l.Q)
	}
	for _, l := range b.Latches {
		sb[l.Name] = val(1, l.Q)
	}
	return sa, sb
}

// ----------------------------------------------------------------- bounded sequential miter

// buildBoundedMiter unrolls both designs from reset into one strashed graph
// with shared per-cycle inputs; diffs[t] is true iff some output differs at cycle t.
func buildBoundedMiter(a, b *aig.AIG, depth int) (m *aig.AIG, diffs []aig.Lit) {
	return buildProductMiter(a, b, depth, false)
}

// buildProductMiter is buildBoundedMiter with an optional free (arbitrary) initial
// state, which is what the induction step of a sequential equivalence proof needs.
func buildProductMiter(a, b *aig.AIG, depth int, freeInit bool) (m *aig.AIG, diffs []aig.Lit) {
	m = aig.New()
	stA := make([]aig.Lit, len(a.Latches))
	stB := make([]aig.Lit, len(b.Latches))
	liveA, liveB := a.LiveLatches(), b.LiveLatches()
	for i, l := range a.Latches {
		stA[i] = aig.False.NotIf(l.Init)
		if freeInit && liveA[i] {
			stA[i] = freshInput(m, "$A:"+l.Name)
		}
	}
	for i, l := range b.Latches {
		stB[i] = aig.False.NotIf(l.Init)
		if freeInit && liveB[i] {
			stB[i] = freshInput(m, "$B:"+l.Name)
		}
	}
	for t := 0; t < depth; t++ {
		xa, xb := newXlate(a, m), newXlate(b, m)
		for _, p := range a.Inputs {
			port := aig.Port{Name: fmt.Sprintf("%s@%d", p.Name, t)}
			for i := range p.Bits {
				port.Bits = append(port.Bits, m.AddInput(port.Name, i))
			}
			m.Inputs = append(m.Inputs, port)
			q := b.FindInput(p.Name)
			for i, bit := range p.Bits {
				xa.set(bit.ID(), port.Bits[i])
				xb.set(q.Bits[i].ID(), port.Bits[i])
			}
		}
		for i, l := range a.Latches {
			if liveA[i] {
				xa.set(l.Q, stA[i])
			}
		}
		for i, l := range b.Latches {
			if liveB[i] {
				xb.set(l.Q, stB[i])
			}
		}
		d := aig.False
		for _, p := range a.Outputs {
			q := b.FindOutput(p.Name)
			for i := range p.Bits {
				d = m.Or(d, m.Xor(xa.lit(p.Bits[i]), xb.lit(q.Bits[i])))
			}
		}
		diffs = append(diffs, d)
		nextA, nextB := make([]aig.Lit, len(stA)), make([]aig.Lit, len(stB))
		for i, l := range a.Latches {
			if liveA[i] {
				nextA[i] = xa.lit(l.D)
			}
		}
		for i, l := range b.Latches {
			if liveB[i] {
				nextB[i] = xb.lit(l.D)
			}
		}
		stA, stB = nextA, nextB
	}
	return m, diffs
}
