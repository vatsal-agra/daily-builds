package model

import (
	"math"
	"testing"

	"kestrel/mat"
)

func numJac(f func(*mat.M) *mat.M, x *mat.M) *mat.M {
	y0 := f(x)
	j := mat.New(y0.R, x.R)
	for c := 0; c < x.R; c++ {
		h := 1e-5 * math.Max(1, math.Abs(x.D[c]))
		xp, xm := x.Clone(), x.Clone()
		xp.D[c] += h
		xm.D[c] -= h
		d := f(xp).Sub(f(xm)).Scale(1 / (2 * h))
		for r := 0; r < y0.R; r++ {
			j.Set(r, c, d.D[r])
		}
	}
	return j
}

func close(a, b *mat.M, tol float64) bool {
	for i := range a.D {
		if math.Abs(a.D[i]-b.D[i]) > tol*math.Max(1, math.Abs(b.D[i])) {
			return false
		}
	}
	return true
}

func TestCTJacobianMatchesNumeric(t *testing.T) {
	m := NewCT(1, 1e-4)
	for _, w := range []float64{0, 1e-9, 0.01, -0.05, 0.3} {
		x := mat.Vec(1000, 150, -2000, 80, w)
		got := m.Jac(x, 2)
		want := numJac(func(v *mat.M) *mat.M { return m.Step(v, 2) }, x)
		if !close(got, want, 1e-3) {
			t.Errorf("ω=%v\n%v\nvs\n%v", w, got, want)
		}
	}
}

func TestCTReducesToCVAtZeroTurn(t *testing.T) {
	x := mat.Vec(10, 5, 20, -3, 0)
	a := NewCT(1, 1).Step(x, 3)
	b := NewCV(1, 5).Step(x, 3)
	for i := 0; i < 4; i++ {
		if math.Abs(a.D[i]-b.D[i]) > 1e-9 {
			t.Fatalf("component %d: CT %v CV %v", i, a.D[i], b.D[i])
		}
	}
}

func TestCTPreservesSpeedAndTurns(t *testing.T) {
	x := mat.Vec(0, 100, 0, 0, 0.1)
	y := NewCT(1, 1).Step(x, 10)
	if s := math.Hypot(y.D[1], y.D[3]); math.Abs(s-100) > 1e-9 {
		t.Fatalf("speed changed: %v", s)
	}
	if h := math.Atan2(y.D[3], y.D[1]); math.Abs(h-1.0) > 1e-9 { // ω·T = 1 rad
		t.Fatalf("heading %v want 1", h)
	}
}

func TestQSymmetricPSD(t *testing.T) {
	for _, m := range []Motion{NewCV(1, 4), NewCA(0.1), NewCT(1, 1e-3)} {
		q := m.Q(mat.New(m.Dim(), 1), 2)
		for i := 0; i < q.R; i++ {
			for j := 0; j < q.C; j++ {
				if q.At(i, j) != q.At(j, i) {
					t.Errorf("%s Q not symmetric", m.Name())
				}
			}
		}
		// position/velocity block must be PSD: Cholesky of a jittered copy succeeds
		if _, err := q.Add(mat.Eye(q.R).Scale(1e-9)).Chol(); err != nil {
			t.Errorf("%s Q not PSD: %v", m.Name(), err)
		}
	}
}

func TestRadarJacobianAndWrap(t *testing.T) {
	r := NewRadar(0, 2, 100, -50, 25, 0.01)
	x := mat.Vec(4000, 1, 3000, 1)
	if !close(r.Jac(x), numJac(r.H, x), 1e-6) {
		t.Fatal("radar Jacobian disagrees with finite differences")
	}
	res := r.Resid(mat.Vec(10, math.Pi-0.01), mat.Vec(8, -math.Pi+0.01))
	if math.Abs(res.D[1]+0.02) > 1e-12 {
		t.Fatalf("bearing residual across ±π: %v want -0.02", res.D[1])
	}
	px, py := r.ToCartesian(r.H(x))
	if math.Abs(px-4000) > 1e-6 || math.Abs(py-3000) > 1e-6 {
		t.Fatalf("round trip %v %v", px, py)
	}
	if c := r.CartCov(r.H(x)); c.At(0, 0) <= 0 || c.At(1, 1) <= 0 {
		t.Fatal("Cartesian covariance must be positive")
	}
}
