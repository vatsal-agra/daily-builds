package aig

import (
	"math/rand"

	"gatecraft/internal/sat"
)

// FraigStats reports what SAT sweeping did.
type FraigStats struct {
	Candidates int // simulation-equal pairs examined
	Proved     int // merged after an UNSAT proof
	Refuted    int // killed by a SAT counterexample
	GaveUp     int // conflict budget exhausted
	Rounds     int
}

// Fraig merges functionally equivalent (or complementary) nodes: random
// simulation proposes candidate classes, an incremental SAT solver proves or
// refutes each, counterexamples refine the simulation, and the graph is rebuilt
// with proven merges. Latch outputs are treated as free variables, so every
// merge holds for all states (not just reachable ones).
func Fraig(g *AIG, seed int64) (*AIG, FraigStats) {
	var st FraigStats
	rng := rand.New(rand.NewSource(seed))
	live := g.Live()
	n := len(g.Nodes)
	repr := make([]Lit, n)
	for i := range repr {
		repr[i] = Lit(i << 1)
	}
	solver := sat.New()
	enc := NewEncoder(g, solver)
	var cex [][]uint64 // each entry: one word per PI/latch holding 64 packed counterexamples
	type free struct{ id uint32 }
	var frees []uint32
	for id, nd := range g.Nodes {
		if (nd.Kind == KInput || nd.Kind == KLatch) && live[id] {
			frees = append(frees, uint32(id))
		}
	}

	const baseWords = 4
	for round := 0; round < 8; round++ {
		st.Rounds++
		words := baseWords + len(cex)
		sig := make([]uint64, n*words)
		for _, id := range frees {
			row := sig[int(id)*words : int(id)*words+words]
			for w := 0; w < baseWords; w++ {
				row[w] = rng.Uint64()
			}
			for w, c := range cex {
				row[baseWords+w] = c[id]
			}
		}
		for id := 1; id < n; id++ {
			nd := g.Nodes[id]
			if nd.Kind != KAnd || !live[id] {
				continue
			}
			a, b := sig[int(nd.A.ID())*words:int(nd.A.ID())*words+words], sig[int(nd.B.ID())*words:int(nd.B.ID())*words+words]
			row := sig[id*words : id*words+words]
			var ma, mb uint64
			if nd.A.Neg() {
				ma = ^uint64(0)
			}
			if nd.B.Neg() {
				mb = ^uint64(0)
			}
			for w := 0; w < words; w++ {
				row[w] = (a[w] ^ ma) & (b[w] ^ mb)
			}
		}
		keyOf := func(id int) (string, bool) {
			row := sig[id*words : id*words+words]
			neg := row[0]&1 == 1
			buf := make([]byte, 0, words*8)
			for _, w := range row {
				if neg {
					w = ^w
				}
				for k := 0; k < 8; k++ {
					buf = append(buf, byte(w>>(8*uint(k))))
				}
			}
			return string(buf), neg
		}
		buckets := map[string][]uint32{}
		add := func(id int) {
			k, _ := keyOf(id)
			buckets[k] = append(buckets[k], uint32(id))
		}
		add(0)
		newCex := 0
		var pending [64][]bool // packed later
		_ = pending
		var cur []uint64 // current cex word set being filled
		bitPos := 0
		flush := func() {
			if cur != nil && bitPos > 0 {
				cex = append(cex, cur)
			}
			cur = nil
			bitPos = 0
		}
		for id := 1; id < n; id++ {
			nd := g.Nodes[id]
			if !live[id] {
				continue
			}
			if nd.Kind != KAnd {
				add(id)
				continue
			}
			if repr[id] != Lit(id<<1) {
				continue
			}
			k, negN := keyOf(id)
			merged := false
			tries := 0
			for _, r := range buckets[k] {
				if tries >= 12 {
					break
				}
				tries++
				_, negR := keyOf(int(r))
				rel := negN != negR // n == r ^ rel
				st.Candidates++
				a := enc.Lit(Lit(uint32(id) << 1))
				b := enc.Lit(Lit(r << 1)).NotIf(rel)
				d := sat.MkLit(solver.NewVar(), false)
				solver.AddClause(d.Not(), a, b)
				solver.AddClause(d.Not(), a.Not(), b.Not())
				solver.SetConflictBudget(solver.Conflicts + 3000)
				switch solver.Solve(d) {
				case sat.Unsat:
					solver.AddClause(d.Not())
					solver.AddClause(a.Not(), b)
					solver.AddClause(a, b.Not())
					repr[id] = Lit(r << 1).NotIf(rel)
					st.Proved++
					merged = true
				case sat.Sat:
					st.Refuted++
					if cur == nil {
						cur = make([]uint64, n)
					}
					for _, f := range frees {
						if enc.Bound(f) && solver.LitValue(enc.Lit(Lit(f<<1))) {
							cur[f] |= 1 << uint(bitPos)
						} else if !enc.Bound(f) && rng.Intn(2) == 1 {
							cur[f] |= 1 << uint(bitPos)
						}
					}
					bitPos++
					newCex++
					if bitPos == 64 {
						flush()
					}
				default:
					st.GaveUp++
				}
				if merged {
					break
				}
			}
			if !merged {
				add(id)
			}
		}
		flush()
		if newCex == 0 {
			break
		}
	}

	subs := make([]latchSub, len(g.Latches))
	for i, l := range g.LiveLatches() {
		if !l {
			subs[i].kind = 3
		}
	}
	rb := newRebuilder(g, true, subs)
	rb.andFn = func(rb *rebuilder, id uint32) Lit {
		if r := repr[id]; r != Lit(id<<1) {
			return rb.lit(r)
		}
		nd := g.Nodes[id]
		return rb.dst.And(rb.lit(nd.A), rb.lit(nd.B))
	}
	return rb.finish(), st
}
