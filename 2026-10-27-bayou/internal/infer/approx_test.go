package infer

import (
	"math"
	"math/rand"
	"testing"

	"bayou/internal/bn"
)

func maxAbsDiff(a, b []float64) float64 {
	d := 0.0
	for i := range a {
		d = math.Max(d, math.Abs(a[i]-b[i]))
	}
	return d
}

func TestSamplersConvergeToExact(t *testing.T) {
	for _, tc := range []struct {
		file, q, ev string
	}{
		{"student.bn", "Intelligence,Difficulty", "Letter=strong"},
		{"sprinkler.bn", "Rain", "WetGrass=true"},
		{"car.bn", "BatteryDead", "Lights=dim,Starts=no"},
	} {
		n := load(t, tc.file)
		q, _ := n.ParseVarList(tc.q)
		ev, _ := n.ParseEvidence(splitCSV(tc.ev))
		exact, err := VE(n, q, ev)
		if err != nil {
			t.Fatal(err)
		}
		lw, err := LikelihoodWeighting(n, q, ev, 400000, 1)
		if err != nil {
			t.Fatal(err)
		}
		if d := maxAbsDiff(exact.Posterior.Probs(), lw.Posterior.Probs()); d > 0.01 {
			t.Errorf("%s LW error %.4f (ESS %.0f)", tc.file, d, lw.ESS)
		}
		if math.Abs(lw.LogPe-exact.LogEvidence) > 0.05 {
			t.Errorf("%s LW log P(e) %.4f vs exact %.4f", tc.file, lw.LogPe, exact.LogEvidence)
		}
		g, err := Gibbs(n, q, ev, GibbsOptions{Samples: 150000, Seed: 3})
		if err != nil {
			t.Fatal(err)
		}
		if d := maxAbsDiff(exact.Posterior.Probs(), g.Posterior.Probs()); d > 0.015 {
			t.Errorf("%s Gibbs error %.4f", tc.file, d)
		}
		if g.ESS < 1000 || g.ESS > float64(g.Samples) {
			t.Errorf("%s Gibbs ESS %.0f out of range (samples %d)", tc.file, g.ESS, g.Samples)
		}
		if g.Rhat > 1.05 {
			t.Errorf("%s Gibbs R-hat %.3f on an easy problem", tc.file, g.Rhat)
		}
	}
}

func splitCSV(s string) []string {
	var out []string
	cur := ""
	for _, r := range s {
		if r == ',' {
			out = append(out, cur)
			cur = ""
		} else {
			cur += string(r)
		}
	}
	return append(out, cur)
}

func TestLWDetectsImpossibleAndDegenerateEvidence(t *testing.T) {
	n := load(t, "asia.bn")
	ev, _ := n.ParseEvidence([]string{"Either=no", "Tuberculosis=yes"})
	if _, err := LikelihoodWeighting(n, []int{n.MustID("Smoking")}, ev, 5000, 1); err == nil {
		t.Fatal("impossible evidence not detected")
	}
	if _, err := Gibbs(n, []int{n.MustID("Smoking")}, ev, GibbsOptions{Samples: 100}); err == nil {
		t.Fatal("Gibbs accepted impossible evidence")
	}
	if _, err := LikelihoodWeighting(n, nil, nil, 10, 1); err == nil {
		t.Fatal("empty query accepted")
	}
	if _, err := LikelihoodWeighting(n, []int{0}, nil, 0, 1); err == nil {
		t.Fatal("zero samples accepted")
	}
}

func TestESSDropsWithRareEvidence(t *testing.T) {
	n := load(t, "burglar.bn")
	q := []int{n.MustID("Burglary")}
	common, _ := n.ParseEvidence([]string{"Alarm=no"})
	rare, _ := n.ParseEvidence([]string{"JohnCalls=yes", "MaryCalls=yes"})
	a, _ := LikelihoodWeighting(n, q, common, 50000, 1)
	b, _ := LikelihoodWeighting(n, q, rare, 50000, 1)
	if !(b.ESS < a.ESS/20) {
		t.Fatalf("ESS should collapse for rare evidence: common %.0f rare %.0f", a.ESS, b.ESS)
	}
}

func TestGibbsRhatFlagsStuckChains(t *testing.T) {
	// X = Y deterministically (two perfectly coupled coins): single-site Gibbs cannot move.
	n := bn.New("coupled")
	n.AddVar("X", []string{"0", "1"})
	copy(n.Vars[0].CPT, []float64{0.5, 0.5})
	n.AddVar("Y", []string{"0", "1"})
	n.SetParents(1, []int{0})
	copy(n.Vars[1].CPT, []float64{1, 0, 0, 1})
	n.AddVar("Z", []string{"0", "1"})
	n.SetParents(2, []int{1})
	copy(n.Vars[2].CPT, []float64{1, 0, 0, 1})
	g, err := Gibbs(n, []int{0}, bn.Evidence{}, GibbsOptions{Samples: 2000, Chains: 6, Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	if !(g.Rhat > 1.5) {
		t.Fatalf("stuck chains should give a large R-hat, got %.3f (posterior %v)", g.Rhat, g.Posterior.Probs())
	}
}

func TestSamplersAreDeterministicPerSeed(t *testing.T) {
	n := load(t, "student.bn")
	q := []int{n.MustID("Grade")}
	a, _ := LikelihoodWeighting(n, q, nil, 1000, 7)
	b, _ := LikelihoodWeighting(n, q, nil, 1000, 7)
	c, _ := LikelihoodWeighting(n, q, nil, 1000, 8)
	if maxAbsDiff(a.Posterior.Probs(), b.Posterior.Probs()) != 0 || maxAbsDiff(a.Posterior.Probs(), c.Posterior.Probs()) == 0 {
		t.Fatal("seed handling wrong")
	}
}

// Random networks: LW stays within a few standard errors of the exact answer.
func TestLWOnRandomNetworks(t *testing.T) {
	rng := rand.New(rand.NewSource(77))
	bad := 0
	for trial := 0; trial < 40; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 6 + rng.Intn(4), MaxParents: 2, MaxCard: 3, Sharp: 2})
		ev := randomEvidence(rng, n, 0.15)
		var q int = -1
		for v := range n.Vars {
			if _, o := ev[v]; !o {
				q = v
				break
			}
		}
		if q < 0 {
			continue
		}
		ex, err := VE(n, []int{q}, ev)
		if err != nil {
			continue
		}
		lw, err := LikelihoodWeighting(n, []int{q}, ev, 60000, int64(trial))
		if err != nil {
			continue
		}
		tol := 6/math.Sqrt(lw.ESS) + 0.003
		if maxAbsDiff(ex.Posterior.Probs(), lw.Posterior.Probs()) > tol {
			bad++
		}
	}
	if bad > 1 {
		t.Fatalf("%d of 40 random problems outside 6 standard errors", bad)
	}
}
