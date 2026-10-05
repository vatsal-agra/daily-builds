package gp

import (
	"math"
	"strings"
	"testing"
	"time"

	"kepler/data"
	"kepler/expr"
)

func parse(t *testing.T, s string, names []string) *expr.Node {
	t.Helper()
	n, err := expr.Parse(s, names)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

// The headline test: every benchmark law is rediscovered and the winner
// generalises to fresh, noiseless points.
func TestRediscoversAllBenchmarks(t *testing.T) {
	if testing.Short() {
		t.Skip("slow")
	}
	for i := range data.Benchmarks {
		b := data.Benchmarks[i]
		t.Run(b.Name, func(t *testing.T) {
			res, err := Run(b.Generate(120, 1), DefaultConfig())
			if err != nil {
				t.Fatal(err)
			}
			if res.Selected < 0 {
				t.Fatal("no model")
			}
			sel := res.Front[res.Selected]
			clean := b
			clean.Noise = 0
			e := NewProblem(clean.Generate(300, 77)).NMSE(sel.Tree)
			if e > 1e-3 {
				t.Fatalf("found %s: noiseless NMSE %.2e", sel.Tree.Format(b.Names), e)
			}
			t.Logf("%s = %s  (nmse %.1e, complexity %d)", b.Target, sel.Tree.Format(b.Names), e, sel.Complexity)
			// front invariants: complexity strictly ascending, error strictly descending
			for k := 1; k < len(res.Front); k++ {
				if res.Front[k].Complexity <= res.Front[k-1].Complexity || res.Front[k].TrainNMSE >= res.Front[k-1].TrainNMSE {
					t.Fatalf("front not Pareto at %d", k)
				}
			}
		})
	}
}

func TestRecoversReadableForms(t *testing.T) {
	if testing.Short() {
		t.Skip("slow")
	}
	want := map[string][]string{
		"kepler":   {"a^1.5"},
		"kinetic":  {"0.5 * m * v^2", "0.5 * v^2 * m"},
		"gravity":  {"6.674 * m1 * m2 / r^2", "6.674 * m2 * m1 / r^2"},
		"idealgas": {"8.314 * n * T / V", "8.314 * T * n / V"},
	}
	for name, forms := range want {
		b, _ := data.Find(name)
		res, _ := Run(b.Generate(120, 1), DefaultConfig())
		got := res.Front[res.Selected].Tree.Format(b.Names)
		ok := false
		for _, f := range forms {
			ok = ok || got == f
		}
		if !ok {
			t.Errorf("%s: got %q, want one of %v", name, got, forms)
		}
	}
}

func TestDeterministicAcrossRuns(t *testing.T) {
	b, _ := data.Find("pendulum")
	d := b.Generate(60, 2)
	cfg := DefaultConfig()
	cfg.Gens, cfg.Pop = 15, 80
	a, _ := Run(d, cfg)
	c, _ := Run(d, cfg)
	if len(a.Front) != len(c.Front) {
		t.Fatalf("front sizes differ %d %d", len(a.Front), len(c.Front))
	}
	for i := range a.Front {
		if !a.Front[i].Tree.Equal(c.Front[i].Tree) {
			t.Fatalf("model %d differs: %v vs %v", i, a.Front[i].Tree, c.Front[i].Tree)
		}
	}
	cfg.Seed = 99
	other, _ := Run(d, cfg)
	if other.Evals == a.Evals && other.Front[0].Tree.Equal(a.Front[0].Tree) && len(other.Front) == len(a.Front) {
		t.Log("different seed gave the same result (possible but unlikely)")
	}
}

func TestIslandsAreIndependentOfThreadScheduling(t *testing.T) {
	b, _ := data.Find("kepler")
	d := b.Generate(50, 1)
	cfg := DefaultConfig()
	cfg.Islands, cfg.Gens, cfg.Pop, cfg.StopErr = 6, 12, 60, 0
	var first string
	for i := 0; i < 3; i++ {
		r, _ := Run(d, cfg)
		s := r.Front[r.Selected].Tree.String()
		if i == 0 {
			first = s
		} else if s != first {
			t.Fatalf("run %d: %s != %s", i, s, first)
		}
	}
}

func TestConfigValidation(t *testing.T) {
	d := (&data.Benchmarks[0]).Generate(30, 1)
	bad := []func(*Config){
		func(c *Config) { c.Pop = 2 }, func(c *Config) { c.Gens = 0 }, func(c *Config) { c.Islands = 0 },
		func(c *Config) { c.MaxSize = 1 }, func(c *Config) { c.Binary = nil }, func(c *Config) { c.Holdout = 0.95 },
		func(c *Config) { c.Unary = []string{"tan"} }, func(c *Config) { c.Binary = []string{"%"} },
	}
	for i, mut := range bad {
		c := DefaultConfig()
		mut(&c)
		if _, err := Run(d, c); err == nil {
			t.Errorf("case %d: expected validation error", i)
		}
	}
	tiny := &data.Dataset{Names: []string{"x"}, Target: "y", X: [][]float64{{1}, {2}}, Y: []float64{1, 2}}
	if _, err := Run(tiny, DefaultConfig()); err == nil {
		t.Error("expected error for 2 rows")
	}
}

func TestTimeLimitAndStop(t *testing.T) {
	b, _ := data.Find("wave")
	d := b.Generate(80, 1)
	cfg := DefaultConfig()
	cfg.Gens, cfg.StopErr, cfg.TimeLimit = 100000, 0, 500*time.Millisecond
	t0 := time.Now()
	res, err := Run(d, cfg)
	if err != nil || len(res.Front) == 0 {
		t.Fatal(err)
	}
	if el := time.Since(t0); el > 15*time.Second {
		t.Fatalf("time limit ignored: %v", el)
	}
	cfg.TimeLimit = 0
	n := 0
	cfg.Stop = func() bool { n++; return n >= 3 }
	res, _ = Run(d, cfg)
	if res.Generations != 3 {
		t.Fatalf("Stop honoured after %d gens", res.Generations)
	}
}

func TestFitConstantsRecoversParameters(t *testing.T) {
	d := &data.Dataset{Names: []string{"x"}, Target: "y"}
	for i := 1; i <= 40; i++ {
		x := float64(i) / 4
		d.X = append(d.X, []float64{x})
		d.Y = append(d.Y, 3.7*math.Exp(-0.45*x)+1.25)
	}
	p := NewProblem(d)
	n := parse(t, "2*exp(-1*x)+0.5", d.Names) // a*exp(-b*x)+c from a poor start
	e := p.FitConstants(n, 800, 3)
	if e > 1e-10 {
		t.Fatalf("nmse %v after fit: %s", e, n)
	}
}

func TestSnapMakesNiceNumbers(t *testing.T) {
	d := (&data.Benchmarks[2]).Generate(60, 1) // kinetic 0.5*m*v^2
	p := NewProblem(d)
	n := parse(t, "0.50000731*m*v^2.0000043", d.Names)
	p.Snap(n, 0.02)
	if got := expr.Simplify(n).Format(d.Names); got != "0.5 * m * v^2" {
		t.Fatalf("snap gave %s", got)
	}
	// but must not snap when it would hurt: 1.5 exponent stays 1.5, 1.4 stays
	k, _ := data.Find("kepler")
	pk := NewProblem(k.Generate(60, 1))
	n2 := parse(t, "a^1.5", []string{"a"})
	pk.Snap(n2, 0.02)
	if n2.R.Val != 1.5 {
		t.Fatalf("snap damaged exponent: %v", n2.R.Val)
	}
}

func TestPruneRemovesVestigialTerms(t *testing.T) {
	k, _ := data.Find("kepler")
	d := k.Generate(60, 1)
	p := NewProblem(d)
	n := parse(t, "a^1.5 + 0.0000003*a + 1e-9", d.Names)
	got := p.Prune(n, 0.02)
	if got.Complexity() > 5 {
		t.Fatalf("not pruned: %s", got)
	}
	if p.NMSE(got) > 1e-9 {
		t.Fatalf("pruning hurt: %v", p.NMSE(got))
	}
	// and must NOT prune a load-bearing term
	n2 := parse(t, "a^1.5 + 0.5*a", d.Names)
	pn := NewProblem(&data.Dataset{Names: d.Names, X: d.X, Y: evalAll(n2, d.X)})
	if r := pn.Prune(n2.Clone(), 0.02); r.Complexity() < n2.Complexity() {
		t.Fatalf("pruned a needed term: %s", r)
	}
}

func evalAll(n *expr.Node, X [][]float64) []float64 {
	out := make([]float64, len(X))
	for i, x := range X {
		out[i] = n.Eval(x)
	}
	return out
}

func TestNMSESemantics(t *testing.T) {
	d := &data.Dataset{Names: []string{"x"}, X: [][]float64{{1}, {2}, {3}, {4}, {5}}, Y: []float64{1, 2, 3, 4, 5}}
	p := NewProblem(d)
	if e := p.NMSE(parse(t, "x", d.Names)); e != 0 {
		t.Errorf("exact fit nmse %v", e)
	}
	if e := p.NMSE(parse(t, "3", d.Names)); math.Abs(e-1) > 1e-12 {
		t.Errorf("mean predictor nmse %v, want 1", e)
	}
	if e := p.NMSE(parse(t, "1/(x-3)", d.Names)); !math.IsInf(e, 1) {
		t.Errorf("undefined at x=3 should be +Inf, got %v", e)
	}
	if p.R2(parse(t, "x", d.Names)) != 1 {
		t.Error("R2")
	}
}

func TestSelectModelPrefersSimplerWhenEqual(t *testing.T) {
	m := func(c int, tr, ho float64) Model { return Model{Complexity: c, TrainNMSE: tr, HoldoutNMSE: ho} }
	front := []Model{m(1, 1, 1), m(5, 1e-3, 1.1e-3), m(9, 9.9e-4, 1.0e-3), m(30, 1e-4, 9e-4)}
	if got := SelectModel(front); got != 1 {
		t.Errorf("picked %d, want 1", got)
	}
	exact := []Model{m(3, 0.2, math.NaN()), m(6, 1e-15, math.NaN()), m(12, 1e-17, math.NaN())}
	if got := SelectModel(exact); got != 1 {
		t.Errorf("exact fits: picked %d, want 1", got)
	}
	if SelectModel(nil) != -1 {
		t.Error("empty front")
	}
	// holdout overrides train: a model that overfits train loses
	over := []Model{m(5, 1e-2, 1.2e-2), m(10, 1e-5, 5e-1)}
	if got := SelectModel(over); got != 0 {
		t.Errorf("overfit model chosen: %d", got)
	}
}

func TestHoldoutUsedAndReported(t *testing.T) {
	b, _ := data.Find("kepler")
	cfg := DefaultConfig()
	cfg.Gens, cfg.Pop = 20, 100
	res, _ := Run(b.Generate(100, 1), cfg)
	for _, m := range res.Front {
		if math.IsNaN(m.HoldoutNMSE) {
			t.Fatal("holdout missing")
		}
	}
	cfg.Holdout = 0
	res, _ = Run(b.Generate(100, 1), cfg)
	if !math.IsNaN(res.Front[0].HoldoutNMSE) {
		t.Fatal("holdout should be NaN when disabled")
	}
}

func TestToleratesHostileData(t *testing.T) {
	cfg := DefaultConfig()
	cfg.Gens, cfg.Pop = 8, 40
	mk := func(f func(i int) (float64, float64)) *data.Dataset {
		d := &data.Dataset{Names: []string{"x"}, Target: "y"}
		for i := 0; i < 30; i++ {
			x, y := f(i)
			d.X = append(d.X, []float64{x})
			d.Y = append(d.Y, y)
		}
		return d
	}
	cases := map[string]*data.Dataset{
		"constant y": mk(func(i int) (float64, float64) { return float64(i), 4 }),
		"constant x": mk(func(i int) (float64, float64) { return 2, float64(i) }),
		"zeros":      mk(func(i int) (float64, float64) { return 0, 0 }),
		"huge":       mk(func(i int) (float64, float64) { return float64(i), 1e150 * float64(i+1) }),
		"negative x": mk(func(i int) (float64, float64) { return float64(i) - 15, float64(i*i) - 30*float64(i) }),
		"outlier": mk(func(i int) (float64, float64) {
			y := 2 * float64(i)
			if i == 7 {
				y = 1e6
			}
			return float64(i), y
		}),
	}
	for name, d := range cases {
		res, err := Run(d, cfg)
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		for _, m := range res.Front {
			if math.IsNaN(m.TrainNMSE) {
				t.Errorf("%s: NaN error on front", name)
			}
		}
	}
}

func TestPrintedFrontNamesVariables(t *testing.T) {
	b, _ := data.Find("pendulum")
	res, _ := Run(b.Generate(60, 1), DefaultConfig())
	s := res.Front[res.Selected].Tree.Format(res.Names)
	if !strings.Contains(s, "L") || !strings.Contains(s, "g") {
		t.Fatalf("expected variable names in %q", s)
	}
}
