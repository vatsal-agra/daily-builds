package infer

import (
	"math"
	"math/rand"
	"testing"

	"bayou/internal/bn"
)

func randomEvidence(rng *rand.Rand, n *bn.Network, p float64) bn.Evidence {
	ev := bn.Evidence{}
	for v := range n.Vars {
		if rng.Float64() < p {
			ev[v] = rng.Intn(n.Card(v))
		}
	}
	return ev
}

// Differential test: enumeration, VE and the junction tree must agree on
// posteriors, joint posteriors, log P(e) and feasibility for random networks,
// including ones with deterministic (zero-probability) CPT entries.
func TestRandomNetworksAgree(t *testing.T) {
	rng := rand.New(rand.NewSource(20261027))
	checked, impossible := 0, 0
	for trial := 0; trial < 400; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 2 + rng.Intn(9), MaxParents: 1 + rng.Intn(3), MaxCard: 2 + rng.Intn(3),
			EdgeProb: 0.3 + 0.6*rng.Float64(), ZeroProb: []float64{0, 0.2, 0.5}[rng.Intn(3)], Sharp: []float64{0.3, 1, 3}[rng.Intn(3)]})
		if errs := n.Validate(); len(errs) > 0 {
			t.Fatal(errs)
		}
		jt, err := NewJT(n)
		if err != nil {
			t.Fatal(err)
		}
		ev := randomEvidence(rng, n, 0.3)
		var hidden []int
		for v := range n.Vars {
			if _, o := ev[v]; !o {
				hidden = append(hidden, v)
			}
		}
		q := []int{}
		for _, v := range hidden {
			if len(q) < 3 && rng.Float64() < 0.5 {
				q = append(q, v)
			}
		}
		rng.Shuffle(len(q), func(i, j int) { q[i], q[j] = q[j], q[i] })
		a, errA := Enumerate(n, q, ev)
		b, errB := VE(n, q, ev)
		cal, errC := jt.Calibrate(ev)
		if (errA == nil) != (errB == nil) || (errA == nil) != (errC == nil) {
			t.Fatalf("trial %d: feasibility disagrees enum=%v ve=%v jt=%v ev=%s", trial, errA, errB, errC, n.EvidenceString(ev))
		}
		if errA != nil {
			impossible++
			continue
		}
		checked++
		if math.Abs(a.LogEvidence-b.LogEvidence) > 1e-9 || math.Abs(a.LogEvidence-cal.LogEvidence) > 1e-9 {
			t.Fatalf("trial %d: log P(e) enum %.12g ve %.12g jt %.12g", trial, a.LogEvidence, b.LogEvidence, cal.LogEvidence)
		}
		pa, pb := a.Posterior.Probs(), b.Posterior.Probs()
		for i := range pa {
			if math.Abs(pa[i]-pb[i]) > 1e-9 {
				t.Fatalf("trial %d: VE posterior differs: %v vs %v", trial, pa, pb)
			}
		}
		for _, v := range hidden {
			e1, _ := Enumerate(n, []int{v}, ev)
			m := cal.Marginal(v).Probs()
			for i, p := range e1.Posterior.Probs() {
				if math.Abs(p-m[i]) > 1e-9 {
					t.Fatalf("trial %d: JT marginal of %s differs: %v vs %v", trial, n.Vars[v].Name, e1.Posterior.Probs(), m)
				}
			}
		}
		// family marginals must equal enumerated joint P(v, parents | e)
		for v := range n.Vars {
			if _, o := ev[v]; o {
				continue
			}
			var fam []int
			okFam := true
			for _, u := range append([]int{v}, n.Vars[v].Parents...) {
				if _, o := ev[u]; o {
					okFam = false
				}
				fam = append(fam, u)
			}
			if !okFam {
				continue
			}
			e2, _ := Enumerate(n, fam, ev)
			f := cal.Family(v)
			for i, p := range e2.Posterior.Probs() {
				if math.Abs(p-f.Probs()[i]) > 1e-9 {
					t.Fatalf("trial %d: family marginal of %s differs", trial, n.Vars[v].Name)
				}
			}
		}
	}
	if checked < 250 || impossible == 0 {
		t.Fatalf("test not exercising enough: %d feasible, %d impossible", checked, impossible)
	}
}

// bruteMAP maximises P(m, e) over m by enumerating the marginal joint.
func bruteMAP(n *bn.Network, mvars []int, ev bn.Evidence) (best float64, ok bool) {
	r, err := Enumerate(n, mvars, ev)
	if err != nil {
		return 0, false
	}
	for _, p := range r.Posterior.Probs() {
		if p > best {
			best = p
		}
	}
	return best, true
}

func TestMAPMatchesBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(99))
	for trial := 0; trial < 300; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 3 + rng.Intn(7), MaxParents: 3, MaxCard: 3, ZeroProb: 0.15, Sharp: 0.5})
		ev := randomEvidence(rng, n, 0.25)
		var m []int
		for v := range n.Vars {
			if _, o := ev[v]; !o && rng.Float64() < 0.6 {
				m = append(m, v)
			}
		}
		if len(m) == 0 {
			continue
		}
		best, feasible := bruteMAP(n, m, ev)
		r, err := MAP(n, m, ev)
		if !feasible {
			if err != ErrImpossible {
				t.Fatalf("trial %d: expected impossible, got %v", trial, err)
			}
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		// the returned assignment must achieve the optimum posterior probability
		got, _ := Enumerate(n, m, ev)
		idx, stride := 0, 1
		for k := len(got.Posterior.Vars) - 1; k >= 0; k-- {
			idx += r.Assign[got.Posterior.Vars[k]] * stride
			stride *= got.Posterior.Card[k]
		}
		if p := got.Posterior.Probs()[idx]; math.Abs(p-best) > 1e-9 {
			t.Fatalf("trial %d: MAP assignment has posterior %.9f but optimum is %.9f", trial, p, best)
		}
		if math.Abs(math.Exp(r.LogPost)-best) > 1e-9 {
			t.Fatalf("trial %d: reported posterior %.9f != optimum %.9f", trial, math.Exp(r.LogPost), best)
		}
	}
}
