package infer

import (
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/factor"
	"bayou/internal/parse"
)

func load(t testing.TB, name string) *bn.Network {
	t.Helper()
	src, err := os.ReadFile(filepath.Join("..", "..", "examples", name))
	if err != nil {
		t.Fatal(err)
	}
	n, err := parse.ParseBN(name, string(src))
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func near(a, b, tol float64) bool { return math.Abs(a-b) <= tol }

func probs(f *factor.Factor) []float64 { return f.Probs() }

func TestAsiaKnownMarginals(t *testing.T) {
	n := load(t, "asia.bn")
	// Published prior marginals of the Asia network.
	want := map[string]float64{"Tuberculosis": 0.0104, "LungCancer": 0.055, "Bronchitis": 0.45, "XRay": 0.11029, "Dyspnea": 0.4359}
	for name, p := range want {
		r, err := VE(n, []int{n.MustID(name)}, nil)
		if err != nil {
			t.Fatal(err)
		}
		if !near(probs(r.Posterior)[0], p, 2e-4) {
			t.Errorf("P(%s=first) = %.5f, want %.5f", name, probs(r.Posterior)[0], p)
		}
	}
}

func TestEnumVsVEvsJT(t *testing.T) {
	for _, name := range []string{"asia.bn", "student.bn", "sprinkler.bn", "burglar.bn", "car.bn", "weather-hmm.bn"} {
		n := load(t, name)
		jt, err := NewJT(n)
		if err != nil {
			t.Fatal(err)
		}
		rng := rand.New(rand.NewSource(7))
		for trial := 0; trial < 20; trial++ {
			ev := bn.Evidence{}
			for v := range n.Vars {
				if rng.Float64() < 0.25 {
					ev[v] = rng.Intn(n.Card(v))
				}
			}
			q := rng.Intn(len(n.Vars))
			if _, o := ev[q]; o {
				continue
			}
			a, errA := Enumerate(n, []int{q}, ev)
			b, errB := VE(n, []int{q}, ev)
			cal, errC := jt.Calibrate(ev)
			if (errA == nil) != (errB == nil) || (errA == nil) != (errC == nil) {
				t.Fatalf("%s %s: disagreement on feasibility: %v %v %v", name, n.EvidenceString(ev), errA, errB, errC)
			}
			if errA != nil {
				continue
			}
			c := cal.Marginal(q)
			for i := range probs(a.Posterior) {
				if !near(probs(a.Posterior)[i], probs(b.Posterior)[i], 1e-9) || !near(probs(a.Posterior)[i], probs(c)[i], 1e-9) {
					t.Fatalf("%s q=%s ev=%s: enum %v ve %v jt %v", name, n.Vars[q].Name, n.EvidenceString(ev), probs(a.Posterior), probs(b.Posterior), probs(c))
				}
			}
			if !near(a.LogEvidence, b.LogEvidence, 1e-9) || !near(a.LogEvidence, cal.LogEvidence, 1e-9) {
				t.Fatalf("%s: logPe enum %g ve %g jt %g", name, a.LogEvidence, b.LogEvidence, cal.LogEvidence)
			}
		}
	}
}
