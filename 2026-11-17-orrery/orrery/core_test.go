package orrery

import (
	"math"
	"testing"
)

func TestKeplerPropagateVsOracle(t *testing.T) {
	for _, e := range []float64{0, 0.1, 0.6, 0.95} {
		r, v, err := StateFromElements(Elements{A: 1.3, E: e, I: 0.4, Raan: 1, Argp: 2, M: 0.7}, 1)
		if err != nil {
			t.Fatal(err)
		}
		for _, dt := range []float64{0.01, 1.7, 5.3, 40, -3.1} {
			r1, v1, err := KeplerPropagate(r, v, 1, dt)
			if err != nil {
				t.Fatal(err)
			}
			r2, v2, err := KeplerOracle(r, v, 1, dt)
			if err != nil {
				t.Fatal(err)
			}
			if d := r1.Sub(r2).Norm(); d > 1e-9 {
				t.Errorf("e=%v dt=%v pos mismatch %g", e, dt, d)
			}
			if d := v1.Sub(v2).Norm(); d > 1e-9 {
				t.Errorf("e=%v dt=%v vel mismatch %g", e, dt, d)
			}
		}
	}
}

func TestKeplerHyperbolicEnergy(t *testing.T) {
	r, v := Vec3{1, 0, 0}, Vec3{0, 1.6, 0} // v > escape speed sqrt(2)
	e0 := v.Norm2()/2 - 1/r.Norm()
	r1, v1, err := KeplerPropagate(r, v, 1, 7)
	if err != nil {
		t.Fatal(err)
	}
	e1 := v1.Norm2()/2 - 1/r1.Norm()
	if math.Abs(e1-e0) > 1e-12 {
		t.Errorf("energy changed %g", e1-e0)
	}
	rb, vb, _ := KeplerPropagate(r1, v1, 1, -7)
	if rb.Sub(r).Norm() > 1e-10 || vb.Sub(v).Norm() > 1e-10 {
		t.Errorf("back-propagation failed")
	}
}

func TestElementsRoundTrip(t *testing.T) {
	in := Elements{A: 2.5, E: 0.3, I: 0.5, Raan: 2.0, Argp: 4.0, M: 1.0}
	r, v, _ := StateFromElements(in, 1.7)
	out, err := ElementsFromState(r, v, 1.7)
	if err != nil {
		t.Fatal(err)
	}
	for name, p := range map[string][2]float64{"a": {in.A, out.A}, "e": {in.E, out.E}, "i": {in.I, out.I},
		"raan": {in.Raan, out.Raan}, "argp": {in.Argp, out.Argp}, "M": {in.M, out.M}} {
		if math.Abs(p[0]-p[1]) > 1e-10 {
			t.Errorf("%s: %v != %v", name, p[0], p[1])
		}
	}
}

func TestBHMatchesDirectAsThetaShrinks(t *testing.T) {
	s, _ := Builtin("plummer", 300, 3)
	prev := math.Inf(1)
	for _, th := range []float64{1.0, 0.5, 0.25, 0.1} {
		rep, err := BHError(s, th)
		if err != nil {
			t.Fatal(err)
		}
		if rep.RMSRel > prev {
			t.Errorf("error did not shrink at theta=%v: %g > %g", th, rep.RMSRel, prev)
		}
		prev = rep.RMSRel
	}
	if prev > 2e-3 {
		t.Errorf("theta=0.1 rms error too large: %g", prev)
	}
	// tiny theta must be essentially exact
	a, b := s.ForceBH(1e-9), s.ForceDirect()
	for i := range a {
		if a[i].Sub(b[i]).Norm() > 1e-9*b[i].Norm() {
			t.Fatalf("theta→0 not exact at %d", i)
		}
	}
}

func TestBHCoincidentBodies(t *testing.T) {
	s := &System{G: 1, Theta: 0.5}
	for i := 0; i < 20; i++ {
		s.Bodies = append(s.Bodies, Body{Name: string(rune('a' + i)), M: 1, Pos: Vec3{1, 1, 1}})
	}
	s.Eps = 0.1
	acc := s.ForceBH(0.5)
	for _, a := range acc {
		if a.Norm() != 0 {
			t.Fatalf("coincident bodies should feel zero force with softening, got %v", a)
		}
	}
}
