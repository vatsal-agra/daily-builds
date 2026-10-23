package equiv_test

import (
	"math/rand"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/equiv"
)

// explicit-state oracle: BFS over reachable states honouring assumptions.
// returns the shortest cycle at which `assert` can be violated, or -1.
func bruteForceViolation(g *aig.AIG, ai int) int {
	nl := len(g.Latches)
	nin := len(g.PIs)
	s := aig.NewSimulator(g)
	encode := func() uint32 {
		var v uint32
		for i := 0; i < nl; i++ {
			if s.State[i]&1 == 1 {
				v |= 1 << uint(i)
			}
		}
		return v
	}
	load := func(st uint32) {
		for i := 0; i < nl; i++ {
			if st>>uint(i)&1 == 1 {
				s.State[i] = ^uint64(0)
			} else {
				s.State[i] = 0
			}
		}
	}
	s.Reset()
	start := encode()
	depth := map[uint32]int{start: 0}
	frontier := []uint32{start}
	best := -1
	for d := 0; len(frontier) > 0; d++ {
		var next []uint32
		for _, st := range frontier {
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
				legal := true
				for _, as := range g.Assumes {
					if s.Lit(as.Lit)&1 == 0 {
						legal = false
					}
				}
				if !legal {
					continue
				}
				if s.Lit(g.Asserts[ai].Lit)&1 == 0 && (best < 0 || d < best) {
					best = d
				}
				s.Clock(nil)
				ns := encode()
				if _, seen := depth[ns]; !seen {
					depth[ns] = d + 1
					next = append(next, ns)
				}
			}
		}
		frontier = next
	}
	return best
}

func TestPropertyCheckerAgainstExplicitState(t *testing.T) {
	proved, failed, bounded := 0, 0, 0
	for seed := int64(0); seed < 300; seed++ {
		rng := rand.New(rand.NewSource(5000 + seed))
		g := randomAIG(rng)
		if len(g.Latches) == 0 || len(g.PIs) > 5 {
			continue
		}
		// properties over random existing logic; assume constrains the inputs a bit
		pool := []aig.Lit{}
		for _, p := range g.Inputs {
			pool = append(pool, p.Bits...)
		}
		for _, l := range g.Latches {
			pool = append(pool, aig.Lit(l.Q<<1))
		}
		pick := func() aig.Lit { return pool[rng.Intn(len(pool))].NotIf(rng.Intn(2) == 0) }
		prop := func() aig.Lit {
			x := g.Or(g.And(pick(), pick()), g.And(pick(), pick()))
			if rng.Intn(2) == 0 {
				x = g.Or(x, pick())
			}
			return x
		}
		g.Asserts = append(g.Asserts, aig.Prop{Name: "p0", Lit: prop()}, aig.Prop{Name: "p1", Lit: prop()})
		if rng.Intn(2) == 0 {
			g.Assumes = append(g.Assumes, aig.Prop{Name: "a0", Lit: g.Or(pick(), pick())})
		}
		rs, err := equiv.CheckProps(g, equiv.PropOptions{MaxDepth: 40, Unique: seed%2 == 0})
		if err != nil {
			t.Fatal(err)
		}
		for i, r := range rs {
			want := bruteForceViolation(g, i)
			switch r.Status {
			case equiv.PropProved:
				proved++
				if want >= 0 {
					t.Fatalf("seed %d prop %d: PROVED but explicit-state search finds a violation at cycle %d", seed, i, want)
				}
			case equiv.PropFailed:
				failed++
				if want != r.Depth {
					t.Fatalf("seed %d prop %d: failure reported at cycle %d, true shortest violation %d", seed, i, r.Depth, want)
				}
				if !r.Trace.Confirmed {
					t.Fatalf("seed %d prop %d: trace does not replay", seed, i)
				}
			case equiv.PropBounded:
				bounded++
				if want >= 0 && want <= 40 {
					t.Fatalf("seed %d prop %d: reported no violation within 40 cycles, but one exists at %d", seed, i, want)
				}
			}
		}
	}
	t.Logf("proved=%d failed=%d bounded=%d", proved, failed, bounded)
	if proved < 20 || failed < 20 {
		t.Fatalf("test did not exercise both outcomes: proved=%d failed=%d", proved, failed)
	}
}
