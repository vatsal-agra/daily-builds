package learn

import (
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/infer"
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

func TestSimulateMatchesDistribution(t *testing.T) {
	n := load(t, "student.bn")
	ds := Simulate(n, 60000, rand.New(rand.NewSource(1)), 0, nil)
	jt, _ := infer.NewJT(n)
	ms, _, _ := jt.Marginals(nil)
	for v := range n.Vars {
		cnt := make([]float64, n.Card(v))
		for _, row := range ds.Rows {
			cnt[row[v]]++
		}
		for s, p := range ms[v].Probs() {
			if got := cnt[s] / float64(len(ds.Rows)); math.Abs(got-p) > 0.01 {
				t.Errorf("%s=%s: sampled %.4f, exact %.4f", n.Vars[v].Name, n.Vars[v].States[s], got, p)
			}
		}
	}
}

func TestFitRecoversParametersAndMatchesCounting(t *testing.T) {
	truth := load(t, "student.bn")
	ds := Simulate(truth, 80000, rand.New(rand.NewSource(2)), 0, nil)
	start := truth.Clone()
	for v := range start.Vars {
		start.ResetUniform(v)
	}
	fit, err := Fit(start, ds, 0)
	if err != nil {
		t.Fatal(err)
	}
	kl, err := KLJoint(truth, fit)
	if err != nil {
		t.Fatal(err)
	}
	if kl > 0.002 {
		t.Fatalf("KL(truth||fit) = %g", kl)
	}
	// hand-count one CPT entry: P(Letter=strong | Grade=A)
	letter, grade := truth.MustID("Letter"), truth.MustID("Grade")
	var nA, nAS float64
	for _, row := range ds.Rows {
		if row[grade] == 0 {
			nA++
			if row[letter] == 1 {
				nAS++
			}
		}
	}
	if got := fit.Vars[letter].CPT[0*2+1]; math.Abs(got-nAS/nA) > 1e-12 {
		t.Fatalf("CPT entry %g, hand count %g", got, nAS/nA)
	}
	// MLE maximises likelihood among all candidates: truth must not beat it
	llFit, _ := LogLikelihood(fit, ds)
	llTruth, _ := LogLikelihood(truth, ds)
	if llFit < llTruth {
		t.Fatalf("MLE likelihood %g below truth's %g", llFit, llTruth)
	}
}

func TestFitSmoothingAndErrors(t *testing.T) {
	n := load(t, "sprinkler.bn")
	ds := &parse.Dataset{Cols: []int{0, 1, 2, 3}, Rows: [][]int{{0, 0, 0, 0}, {0, 0, 0, 0}}}
	if _, err := Fit(n, ds, 0); err == nil {
		t.Fatal("alpha=0 with unseen parent configurations must fail")
	}
	fit, err := Fit(n, ds, 1)
	if err != nil {
		t.Fatal(err)
	}
	if errs := fit.Validate(); len(errs) > 0 {
		t.Fatal(errs)
	}
	// Laplace: P(Cloudy=true) = (2+1)/(2+2)
	if got := fit.Vars[0].CPT[0]; math.Abs(got-0.75) > 1e-12 {
		t.Fatalf("laplace estimate %g", got)
	}
	if _, err := Fit(n, ds, -1); err == nil {
		t.Fatal("negative alpha accepted")
	}
	if _, err := Fit(n, &parse.Dataset{Cols: []int{0}, Rows: [][]int{{0}}}, 1); err == nil {
		t.Fatal("latent columns must be rejected by plain MLE")
	}
	// all-missing data for a family
	if _, err := Fit(n, &parse.Dataset{Cols: []int{0, 1, 2, 3}, Rows: [][]int{{-1, 0, 0, 0}}}, 1); err == nil {
		t.Fatal("expected error: Cloudy never observed")
	}
}

func TestEMMonotoneAndFindsGoodModel(t *testing.T) {
	truth := load(t, "weather-hmm.bn")
	hidden := []int{0, 1, 2, 3, 4}
	ds := Simulate(truth, 3000, rand.New(rand.NewSource(4)), 0, hidden)
	res, err := EM(truth, ds, EMOptions{MaxIter: 120, Alpha: 0.01, Random: true, Seed: 5, Restarts: 2})
	if err != nil {
		t.Fatal(err)
	}
	for i := 1; i < len(res.LogLik); i++ {
		if res.LogLik[i] < res.LogLik[i-1]-1e-6 {
			t.Fatalf("log-likelihood decreased at iteration %d: %g → %g", i, res.LogLik[i-1], res.LogLik[i])
		}
	}
	llTruth, _ := LogLikelihood(truth, ds)
	llEM := res.LogLik[len(res.LogLik)-1]
	if llEM < llTruth-5 {
		t.Fatalf("EM likelihood %g much worse than truth's %g", llEM, llTruth)
	}
	if errs := res.Net.Validate(); len(errs) > 0 {
		t.Fatal(errs)
	}
}

func TestEMWithMissingCellsRecoversTruth(t *testing.T) {
	truth := load(t, "burglar.bn")
	ds := Simulate(truth, 100000, rand.New(rand.NewSource(6)), 0.25, nil)
	start := truth.Clone()
	for v := range start.Vars {
		start.ResetUniform(v)
	}
	res, err := EM(start, ds, EMOptions{MaxIter: 300, Tol: 1e-9, Alpha: 0})
	if err != nil {
		t.Fatal(err)
	}
	// Alarm-related CPTs are well determined; rare-event entries are noisy so check KL, not entries.
	kl, err := KLJoint(truth, res.Net)
	if err != nil {
		t.Fatal(err)
	}
	if kl > 0.003 {
		t.Fatalf("KL(truth‖EM) = %g after %d iterations", kl, len(res.LogLik))
	}
}

func TestEMOnCompleteDataEqualsMLEInOneStep(t *testing.T) {
	truth := load(t, "student.bn")
	ds := Simulate(truth, 5000, rand.New(rand.NewSource(7)), 0, nil)
	start := truth.Clone()
	for v := range start.Vars {
		start.ResetUniform(v)
	}
	res, err := EM(start, ds, EMOptions{MaxIter: 3, Alpha: 0})
	if err != nil {
		t.Fatal(err)
	}
	fit, _ := Fit(start, ds, 0)
	if d := MaxCPTDiff(res.Net, fit); d > 1e-9 {
		t.Fatalf("EM on complete data differs from MLE by %g", d)
	}
}

func TestEMErrors(t *testing.T) {
	n := load(t, "sprinkler.bn")
	if _, err := EM(n, &parse.Dataset{Cols: []int{0}}, EMOptions{}); err == nil {
		t.Fatal("empty dataset accepted")
	}
	if _, err := EM(n, &parse.Dataset{Cols: []int{0}, Rows: [][]int{{0}}}, EMOptions{Alpha: -1}); err == nil {
		t.Fatal("negative alpha accepted")
	}
	// a row that is impossible under the model must be reported, not produce NaN
	imp := load(t, "asia.bn")
	either, tb, lc := imp.MustID("Either"), imp.MustID("Tuberculosis"), imp.MustID("LungCancer")
	ds := &parse.Dataset{Cols: []int{either, tb, lc}, Rows: [][]int{{1, 0, 1}}} // Either=no yet TB=yes
	if _, err := EM(imp, ds, EMOptions{}); err == nil {
		t.Fatal("impossible data row accepted")
	}
}

func TestKLJoint(t *testing.T) {
	a := load(t, "student.bn")
	if kl, err := KLJoint(a, a); err != nil || math.Abs(kl) > 1e-12 {
		t.Fatalf("KL(a,a) = %g, %v", kl, err)
	}
	// brute-force KL over the joint for a perturbed copy
	b := a.Clone()
	rng := rand.New(rand.NewSource(8))
	randomizeCPTs(b, rng)
	got, err := KLJoint(a, b)
	if err != nil {
		t.Fatal(err)
	}
	want := 0.0
	asg := make([]int, len(a.Vars))
	for {
		pa, pb := math.Exp(a.LogJoint(asg)), math.Exp(b.LogJoint(asg))
		if pa > 0 {
			want += pa * math.Log(pa/pb)
		}
		k := len(asg) - 1
		for ; k >= 0; k-- {
			if asg[k]++; asg[k] < a.Card(k) {
				break
			}
			asg[k] = 0
		}
		if k < 0 {
			break
		}
	}
	if math.Abs(got-want) > 1e-10 {
		t.Fatalf("chain-rule KL %g, brute force %g", got, want)
	}
	c := load(t, "sprinkler.bn")
	if _, err := KLJoint(a, c); err == nil {
		t.Fatal("different structures accepted")
	}
}

func TestEMStopsWhenConverged(t *testing.T) {
	truth := load(t, "student.bn")
	ds := Simulate(truth, 2000, rand.New(rand.NewSource(10)), 0.1, nil)
	start := truth.Clone()
	for v := range start.Vars {
		start.ResetUniform(v)
	}
	res, err := EM(start, ds, EMOptions{MaxIter: 500, Tol: 1e-6, Alpha: 0.1})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Converged || len(res.LogLik) >= 500 {
		t.Fatalf("EM did not detect convergence (%d iterations, converged=%v)", len(res.LogLik), res.Converged)
	}
	last := len(res.LogLik) - 1
	if res.LogLik[last]-res.LogLik[last-1] >= 1e-6 {
		t.Fatalf("stopped while still improving by %g", res.LogLik[last]-res.LogLik[last-1])
	}
}
