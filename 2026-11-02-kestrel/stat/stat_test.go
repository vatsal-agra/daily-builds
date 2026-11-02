package stat

import (
	"math"
	"testing"

	"kestrel/mat"
)

func TestChi2KnownValues(t *testing.T) {
	// textbook table values
	cases := []struct {
		p    float64
		k    int
		want float64
	}{{0.95, 1, 3.8415}, {0.95, 2, 5.9915}, {0.999, 2, 13.8155}, {0.99, 4, 13.2767}, {0.5, 10, 9.3418}}
	for _, c := range cases {
		got, err := Chi2Quantile(c.p, c.k)
		if err != nil || math.Abs(got-c.want) > 2e-3 {
			t.Errorf("Chi2Quantile(%v,%d)=%v want %v (%v)", c.p, c.k, got, c.want, err)
		}
	}
	if v := Chi2CDF(2.0, 2); math.Abs(v-(1-math.Exp(-1))) > 1e-12 { // k=2 closed form
		t.Errorf("Chi2CDF closed form: %v", v)
	}
	if _, err := Chi2Quantile(1.5, 2); err == nil {
		t.Error("p>1 must error")
	}
}

func TestWrapAngle(t *testing.T) {
	for _, c := range [][2]float64{{0, 0}, {math.Pi, math.Pi}, {-math.Pi, math.Pi}, {3 * math.Pi, math.Pi}, {2*math.Pi + 0.1, 0.1}, {-2*math.Pi - 0.1, -0.1}} {
		if got := WrapAngle(c[0]); math.Abs(got-c[1]) > 1e-12 {
			t.Errorf("WrapAngle(%v)=%v want %v", c[0], got, c[1])
		}
	}
}

func TestMVNMoments(t *testing.T) {
	g := NewRNG(5)
	cov := mat.From(2, 2, 4, 1.5, 1.5, 2)
	n := 40000
	var sx, sxx, sxy float64
	for i := 0; i < n; i++ {
		v, err := g.MVN(mat.Vec(10, -3), cov)
		if err != nil {
			t.Fatal(err)
		}
		sx += v.D[0]
		sxx += (v.D[0] - 10) * (v.D[0] - 10)
		sxy += (v.D[0] - 10) * (v.D[1] + 3)
	}
	if math.Abs(sx/float64(n)-10) > 0.05 || math.Abs(sxx/float64(n)-4) > 0.1 || math.Abs(sxy/float64(n)-1.5) > 0.1 {
		t.Errorf("sample moments off: mean %v var %v cov %v", sx/float64(n), sxx/float64(n), sxy/float64(n))
	}
	if _, err := g.MVN(mat.Vec(0, 0), mat.From(2, 2, 1, 2, 2, 1)); err == nil {
		t.Error("non-PSD covariance must error")
	}
}

func TestPoissonMean(t *testing.T) {
	g := NewRNG(2)
	s := 0
	for i := 0; i < 20000; i++ {
		s += g.Poisson(4)
	}
	if m := float64(s) / 20000; math.Abs(m-4) > 0.08 {
		t.Errorf("Poisson mean %v", m)
	}
}
