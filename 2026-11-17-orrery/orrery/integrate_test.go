package orrery

import (
	"math"
	"testing"
)

func mustBuiltin(t *testing.T, name string) *System {
	t.Helper()
	s, err := Builtin(name, 0, 1)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// two-body orbit vs the analytic oracle for every method
func TestTwoBodyAgainstOracle(t *testing.T) {
	s := mustBuiltin(t, "twobody")
	rel := s.Bodies[1].Pos.Sub(s.Bodies[0].Pos)
	vel := s.Bodies[1].Vel.Sub(s.Bodies[0].Vel)
	mu := s.G * s.TotalMass()
	el, _ := ElementsFromState(rel, vel, mu)
	T := 2 * el.Period
	rO, _, err := KeplerOracle(rel, vel, mu, T)
	if err != nil {
		t.Fatal(err)
	}
	tols := map[Method]float64{Euler: 5, SymplecticEul: 1, Leapfrog: 1e-2, Yoshida4: 1e-4, RK4: 1e-3, DOPRI5: 1e-6, WisdomHolman: 1e-3}
	for m, tol := range tols {
		dt := el.Period / 2000
		res, err := Run(s, m, dt, T, 20, 1e-11)
		if err != nil || res.Err != nil {
			t.Fatalf("%s: %v %v", m, err, res.Err)
		}
		f := res.Final
		got := f.Bodies[1].Pos.Sub(f.Bodies[0].Pos)
		if d := got.Sub(rO).Norm(); d > tol {
			t.Errorf("%s: position error %g > %g", m, d, tol)
		}
	}
}

func TestFigureEightReturns(t *testing.T) {
	s := mustBuiltin(t, "figure8")
	const period = 6.32591398
	res, err := Run(s, Yoshida4, period/4000, period, 50, 0)
	if err != nil || res.Err != nil {
		t.Fatal(err, res.Err)
	}
	for i := range s.Bodies {
		if d := res.Final.Bodies[i].Pos.Sub(s.Bodies[i].Pos).Norm(); d > 2e-4 {
			t.Errorf("body %d not back at start: %g", i, d)
		}
	}
}

func TestSymplecticBeatsRK4LongRun(t *testing.T) {
	s := mustBuiltin(t, "twobody")
	T := 3000.0
	dt := 0.05
	lf, _ := Run(s, Leapfrog, dt, T, 200, 0)
	rk, _ := Run(s, RK4, dt, T, 200, 0)
	if lf.Err != nil || rk.Err != nil {
		t.Fatal(lf.Err, rk.Err)
	}
	// RK4 energy error must show monotone secular drift, leapfrog stays bounded.
	n := len(rk.EnergyErr)
	if math.Abs(rk.EnergyErr[n-1]) < math.Abs(rk.EnergyErr[n/2]) {
		t.Errorf("expected RK4 energy drift to grow: mid=%g end=%g", rk.EnergyErr[n/2], rk.EnergyErr[n-1])
	}
	if lf.MaxAbsEnergyErr() > 5e-2 {
		t.Errorf("leapfrog energy error unexpectedly large: %g", lf.MaxAbsEnergyErr())
	}
	if lf.MaxAbsEnergyErr() >= rk.MaxAbsEnergyErr() {
		t.Errorf("leapfrog (%g) should beat RK4 (%g) over %g time units at dt=%g", lf.MaxAbsEnergyErr(), rk.MaxAbsEnergyErr(), T, dt)
	}
}

func TestConservationLawsExact(t *testing.T) {
	s := mustBuiltin(t, "figure8")
	for _, m := range []Method{Leapfrog, Yoshida4, RK4, DOPRI5} {
		res, _ := Run(s, m, 0.01, 6, 30, 1e-11)
		if res.Err != nil {
			t.Fatal(res.Err)
		}
		if p := maxAbs(res.PDrift); p > 1e-11 {
			t.Errorf("%s momentum drift %g", m, p)
		}
	}
}

func TestInvalidInputs(t *testing.T) {
	s := mustBuiltin(t, "twobody")
	if _, err := Run(s, Leapfrog, 0, 1, 10, 0); err == nil {
		t.Error("dt=0 should fail")
	}
	if _, err := Run(s, Leapfrog, 0.1, -1, 10, 0); err == nil {
		t.Error("T<0 should fail")
	}
	if _, err := Run(s, "bogus", 0.1, 1, 10, 0); err == nil {
		t.Error("bad method should fail")
	}
	if _, err := Run(s, Leapfrog, math.NaN(), 1, 10, 0); err == nil {
		t.Error("NaN dt should fail")
	}
	bad := s.Clone()
	bad.Bodies[0].M = 0
	if _, err := Run(bad, Leapfrog, 0.1, 1, 10, 0); err == nil {
		t.Error("zero mass should fail")
	}
}

// Wisdom–Holman shines when planets are light: error ∝ planet mass.
func TestWisdomHolmanSolarSystem(t *testing.T) {
	s := mustBuiltin(t, "solar")
	wh, err := Run(s, WisdomHolman, 0.05, 200, 100, 0)
	if err != nil || wh.Err != nil {
		t.Fatal(err, wh.Err)
	}
	lf, _ := Run(s, Leapfrog, 0.05, 200, 100, 0)
	if wh.MaxAbsEnergyErr() > 1e-6 {
		t.Errorf("WH energy error %g too large", wh.MaxAbsEnergyErr())
	}
	if wh.MaxAbsEnergyErr() >= lf.MaxAbsEnergyErr() {
		t.Errorf("WH (%g) should beat leapfrog (%g) at dt=0.05 on the solar system", wh.MaxAbsEnergyErr(), lf.MaxAbsEnergyErr())
	}
	if maxAbs(wh.PDrift) > 1e-12 {
		t.Errorf("WH momentum drift %g", maxAbs(wh.PDrift))
	}
}

func TestWisdomHolmanRejectsBadSystems(t *testing.T) {
	s := mustBuiltin(t, "solar")
	soft := s.Clone()
	soft.Eps = 0.1
	if _, err := NewIntegrator(soft, WisdomHolman); err == nil {
		t.Error("softened system should be rejected")
	}
	heavy := s.Clone()
	heavy.Bodies[3].M = 5
	if _, err := NewIntegrator(heavy, WisdomHolman); err == nil {
		t.Error("planet heavier than body 0 should be rejected")
	}
}
