package equiv_test

import (
	"fmt"
	"math/rand"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/equiv"
)

// randomAIG builds a random sequential netlist laced with redundancy (equivalent
// re-expressions, duplicated and stuck registers) for the optimiser to chew on.
func randomAIG(rng *rand.Rand) *aig.AIG {
	g := aig.New()
	nin := 3 + rng.Intn(4)
	var pool []aig.Lit
	in := aig.Port{Name: "x"}
	for i := 0; i < nin; i++ {
		l := g.AddInput("x", i)
		in.Bits = append(in.Bits, l)
		pool = append(pool, l)
	}
	g.Inputs = append(g.Inputs, in)
	nl := rng.Intn(7)
	var qs []aig.Lit
	for i := 0; i < nl; i++ {
		q := g.AddLatch(fmt.Sprintf("s%d", i), rng.Intn(2) == 0)
		g.Latches[i].Clock = "clk"
		qs = append(qs, q)
		pool = append(pool, q)
	}
	pick := func() aig.Lit { return pool[rng.Intn(len(pool))].NotIf(rng.Intn(2) == 0) }
	for i, n := 0, 15+rng.Intn(60); i < n; i++ {
		a, b := pick(), pick()
		var r aig.Lit
		switch rng.Intn(7) {
		case 0, 1:
			r = g.And(a, b)
		case 2:
			r = g.Or(a, b)
		case 3:
			r = g.Xor(a, b)
		case 4: // redundant re-association: (a&b)&c vs a&(b&c), kept both
			c := pick()
			x, y := g.And(g.And(a, b), c), g.And(a, g.And(b, c))
			pool = append(pool, x)
			r = y
		case 5: // absorption: a | (a & b) == a
			r = g.Or(a, g.And(a, b))
		default:
			r = g.Mux(pick(), a, b)
		}
		pool = append(pool, r)
	}
	for i := range qs {
		d := pick()
		switch rng.Intn(5) {
		case 0: // stuck register: stays at init
			d = qs[i]
		case 1: // twin of a previous register
			if i > 0 {
				g.Latches[i].D = g.Latches[i-1].D
				g.Latches[i].Init = g.Latches[i-1].Init
				continue
			}
		case 2: // sticky-zero if init 0
			if !g.Latches[i].Init {
				d = g.And(qs[i], pick())
			}
		}
		g.Latches[i].D = d
	}
	out := aig.Port{Name: "y"}
	for i := 0; i < 1+rng.Intn(4); i++ {
		out.Bits = append(out.Bits, pick())
	}
	g.Outputs = append(g.Outputs, out)
	return g
}

// run both nets for `cycles` cycles under identical random 64-lane stimulus; return the first mismatch.
func firstMismatch(a, b *aig.AIG, cycles int, rng *rand.Rand) string {
	sa, sb := aig.NewSimulator(a), aig.NewSimulator(b)
	for c := 0; c < cycles; c++ {
		for i, pi := range a.PIs {
			w := rng.Uint64()
			sa.SetPI(i, w)
			for j, pj := range b.PIs {
				if pj.Port == pi.Port && pj.Bit == pi.Bit {
					sb.SetPI(j, w)
				}
			}
		}
		sa.Eval()
		sb.Eval()
		for _, p := range a.Outputs {
			q := b.FindOutput(p.Name)
			for i := range p.Bits {
				if sa.Lit(p.Bits[i]) != sb.Lit(q.Bits[i]) {
					return fmt.Sprintf("cycle %d output %s[%d]", c, p.Name, i)
				}
			}
		}
		sa.Clock(nil)
		sb.Clock(nil)
	}
	return ""
}

func TestOptimizerFuzz(t *testing.T) {
	shrunk := 0
	for seed := int64(0); seed < 400; seed++ {
		rng := rand.New(rand.NewSource(seed))
		g := randomAIG(rng)
		opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: seed})
		if err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if m := firstMismatch(g, opt, 40, rng); m != "" {
			t.Fatalf("seed %d: simulation mismatch after optimisation at %s", seed, m)
		}
		res, err := equiv.CheckComb(g, opt)
		if err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if res.Verdict != equiv.Equivalent {
			t.Fatalf("seed %d: CheckComb says %s (%+v) although simulation agrees", seed, res.Verdict, res.Cex)
		}
		if a, b := g.Stats(), opt.Stats(); b.Ands < a.Ands || b.Latches < a.Latches {
			shrunk++
		}
	}
	if shrunk < 200 {
		t.Fatalf("optimiser shrank only %d/400 random redundant designs", shrunk)
	}
}

// Mutate a netlist; the checker must never call a simulation-visible difference equivalent,
// and every counterexample it produces must replay.
func TestCheckerFuzzWithMutants(t *testing.T) {
	diff, same := 0, 0
	for seed := int64(0); seed < 400; seed++ {
		rng := rand.New(rand.NewSource(1000 + seed))
		g := randomAIG(rng)
		opt, _, _ := aig.Optimize(g, aig.OptOptions{Seed: seed})
		mut := cloneForMutation(opt, rng)
		res, err := equiv.CheckComb(opt, mut)
		if err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		switch res.Verdict {
		case equiv.Different:
			diff++
			if !res.Cex.Confirmed {
				t.Fatalf("seed %d: counterexample on %s does not replay", seed, res.Cex.Obligation)
			}
		case equiv.Equivalent:
			same++
			// state-matched equivalence implies identical behaviour from reset
			if m := firstMismatch(opt, mut, 40, rng); m != "" {
				t.Fatalf("seed %d: checker said EQUIVALENT but simulation differs at %s", seed, m)
			}
		}
	}
	if diff < 50 || same < 5 {
		t.Fatalf("mutation mix too skewed: diff=%d same=%d", diff, same)
	}
}

// cloneForMutation rebuilds g and perturbs one output bit or next-state function.
func cloneForMutation(g *aig.AIG, rng *rand.Rand) *aig.AIG {
	m := aig.Rebuild(g)
	switch rng.Intn(3) {
	case 0:
		if len(m.Outputs) > 0 {
			p := &m.Outputs[0]
			i := rng.Intn(len(p.Bits))
			p.Bits[i] = m.And(p.Bits[i], m.Inputs[0].Bits[rng.Intn(len(m.Inputs[0].Bits))].NotIf(rng.Intn(2) == 0))
		}
	case 1:
		if len(m.Latches) > 0 {
			i := rng.Intn(len(m.Latches))
			m.Latches[i].D = m.Latches[i].D.Not()
		}
	}
	return m
}
