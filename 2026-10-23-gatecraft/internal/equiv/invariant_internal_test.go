package equiv

import (
	"fmt"
	"math/rand"
	"testing"

	"gatecraft/internal/aig"
)

// small random sequential netlist (kept tiny so reachable states can be enumerated)
func tinyAIG(rng *rand.Rand) *aig.AIG {
	g := aig.New()
	nin := 1 + rng.Intn(3)
	var pool []aig.Lit
	in := aig.Port{Name: "x"}
	for i := 0; i < nin; i++ {
		l := g.AddInput("x", i)
		in.Bits = append(in.Bits, l)
		pool = append(pool, l)
	}
	g.Inputs = append(g.Inputs, in)
	nl := 2 + rng.Intn(4)
	for i := 0; i < nl; i++ {
		q := g.AddLatch(fmt.Sprintf("s%d", i), rng.Intn(2) == 0)
		g.Latches[i].Clock = "clk"
		pool = append(pool, q)
	}
	pick := func() aig.Lit { return pool[rng.Intn(len(pool))].NotIf(rng.Intn(2) == 0) }
	for i := 0; i < 6+rng.Intn(14); i++ {
		a, b := pick(), pick()
		var r aig.Lit
		switch rng.Intn(3) {
		case 0:
			r = g.And(a, b)
		case 1:
			r = g.Or(a, b)
		default:
			r = g.Xor(a, b)
		}
		pool = append(pool, r)
	}
	for i := range g.Latches {
		g.Latches[i].D = pick()
	}
	out := aig.Port{Name: "y"}
	for i := 0; i < 1+rng.Intn(2); i++ {
		out.Bits = append(out.Bits, pick())
	}
	g.Outputs = append(g.Outputs, out)
	return g
}

// reachable enumerates every state reachable from reset under all input sequences.
func reachable(g *aig.AIG) map[uint64]bool {
	nl, nin := len(g.Latches), len(g.PIs)
	s := aig.NewSimulator(g)
	enc := func() uint64 {
		var v uint64
		for i := 0; i < nl; i++ {
			if s.State[i]&1 == 1 {
				v |= 1 << uint(i)
			}
		}
		return v
	}
	load := func(st uint64) {
		for i := 0; i < nl; i++ {
			if st>>uint(i)&1 == 1 {
				s.State[i] = ^uint64(0)
			} else {
				s.State[i] = 0
			}
		}
	}
	s.Reset()
	start := enc()
	seen := map[uint64]bool{start: true}
	queue := []uint64{start}
	for len(queue) > 0 {
		st := queue[0]
		queue = queue[1:]
		for in := 0; in < 1<<uint(nin); in++ {
			load(st)
			for i := 0; i < nin; i++ {
				if in>>uint(i)&1 == 1 {
					s.SetPI(i, ^uint64(0))
				} else {
					s.SetPI(i, 0)
				}
			}
			s.Eval()
			s.Clock(nil)
			if n := enc(); !seen[n] {
				seen[n] = true
				queue = append(queue, n)
			}
		}
	}
	return seen
}

// Every mined invariant must hold in every reachable state (soundness of the Houdini step).
func TestMinedInvariantsHoldOnAllReachableStates(t *testing.T) {
	total := 0
	for seed := int64(0); seed < 300; seed++ {
		rng := rand.New(rand.NewSource(seed))
		g := tinyAIG(rng)
		a := aig.Rebuild(g)
		b := aig.Rebuild(g)
		for i := range b.Latches {
			b.Latches[i].Name = fmt.Sprintf("other%d", i)
		}
		p := buildProduct(a, b)
		invs := mineInvariants(p, seed)
		total += len(invs)
		if len(p.Latches) > 12 {
			continue
		}
		states := reachable(p)
		sim := aig.NewSimulator(p)
		for st := range states {
			for i := range p.Latches {
				if st>>uint(i)&1 == 1 {
					sim.State[i] = ^uint64(0)
				} else {
					sim.State[i] = 0
				}
			}
			for i := range p.PIs {
				sim.SetPI(i, 0)
			}
			sim.Eval()
			for k, inv := range invs {
				if sim.Lit(inv)&1 == 0 {
					t.Fatalf("seed %d: mined invariant #%d is violated in reachable state %b", seed, k, st)
				}
			}
		}
	}
	if total < 100 {
		t.Fatalf("miner produced only %d invariants overall; test is vacuous", total)
	}
}

// Soundness + completeness probe of CheckInduction against explicit-state product search.
func TestInductionNeverProvesWrongEquivalences(t *testing.T) {
	proved, trulyEq, inconcl := 0, 0, 0
	for seed := int64(0); seed < 400; seed++ {
		rng := rand.New(rand.NewSource(7000 + seed))
		a := tinyAIG(rng)
		b := aig.Rebuild(a)
		for i := range b.Latches {
			b.Latches[i].Name = fmt.Sprintf("renamed%d", i) // defeats state matching
		}
		switch rng.Intn(3) {
		case 0: // flip one next-state function
			if len(b.Latches) > 0 {
				i := rng.Intn(len(b.Latches))
				b.Latches[i].D = b.Latches[i].D.Not()
			}
		case 1: // flip an output
			b.Outputs[0].Bits[0] = b.Outputs[0].Bits[0].Not()
		default: // behaviour-preserving restructuring
			b, _, _ = aig.Optimize(b, aig.OptOptions{Seed: seed, NoSeq: true})
		}
		// ground truth: outputs agree on every reachable state/input of the product machine
		p := buildProduct(a, b)
		if len(p.Latches) > 14 {
			continue
		}
		truth := true
		sim := aig.NewSimulator(p)
		for st := range reachable(p) {
			for i := range p.Latches {
				if st>>uint(i)&1 == 1 {
					sim.State[i] = ^uint64(0)
				} else {
					sim.State[i] = 0
				}
			}
			for in := 0; in < 1<<uint(len(p.PIs)); in++ {
				for i := range p.PIs {
					if in>>uint(i)&1 == 1 {
						sim.SetPI(i, ^uint64(0))
					} else {
						sim.SetPI(i, 0)
					}
				}
				sim.Eval()
				if sim.Lit(p.Asserts[0].Lit)&1 == 0 {
					truth = false
				}
			}
		}
		res, err := CheckInduction(a, b, 6)
		if err != nil {
			t.Fatal(err)
		}
		if truth {
			trulyEq++
		}
		switch res.Verdict {
		case Equivalent:
			proved++
			if !truth {
				t.Fatalf("seed %d: UNSOUND — induction proved equivalence of designs that differ on a reachable state", seed)
			}
		case Different:
			if truth {
				t.Fatalf("seed %d: induction reported a difference for equivalent designs", seed)
			}
			if !res.Trace.Confirmed {
				t.Fatalf("seed %d: unconfirmed counterexample", seed)
			}
		default:
			inconcl++
		}
	}
	t.Logf("truly equivalent pairs: %d, proved by induction: %d, inconclusive: %d", trulyEq, proved, inconcl)
	if trulyEq < 40 || proved < trulyEq/2 {
		t.Fatalf("induction proved only %d of %d truly equivalent pairs", proved, trulyEq)
	}
}
