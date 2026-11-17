package orrery

import (
	"encoding/json"
	"math"
	"regexp"
	"strings"
	"testing"
)

func TestOrderStudyMatchesNominal(t *testing.T) {
	s := &System{G: 1, Bodies: []Body{{Name: "star", M: 1}, {Name: "planet", M: 1e-3}}}
	r, v, _ := StateFromElements(Elements{A: 1, E: 0.3}, 1.001)
	s.Bodies[1].Pos, s.Bodies[1].Vel = r, v
	s.ToBarycentric()
	for _, m := range []Method{SymplecticEul, Leapfrog, Yoshida4, RK4, WisdomHolman} {
		st, err := MeasureOrder(s, m, []int{100, 200, 400, 800, 1600})
		if err != nil {
			t.Fatalf("%s: %v", m, err)
		}
		if math.Abs(st.Observed-float64(m.Order())) > 0.35 {
			t.Errorf("%s: observed order %.2f, nominal %d", m, st.Observed, m.Order())
		}
	}
	if _, err := MeasureOrder(s, DOPRI5, []int{100, 200, 400}); err == nil {
		t.Error("dopri5 order study must be rejected")
	}
	three := mustBuiltin(t, "figure8")
	if _, err := MeasureOrder(three, Leapfrog, []int{100, 200, 400}); err == nil {
		t.Error("three bodies must be rejected")
	}
}

func TestReversibility(t *testing.T) {
	s := mustBuiltin(t, "figure8")
	for _, m := range []Method{Leapfrog, Yoshida4, WisdomHolman} {
		if m == WisdomHolman {
			continue // body 0 is not dominant in figure8
		}
		r, err := ReverseTest(s, m, 0.01, 6)
		if err != nil {
			t.Fatal(err)
		}
		if r.RelPosErr > 1e-9 {
			t.Errorf("%s should be reversible to round-off, err=%g", m, r.RelPosErr)
		}
	}
	for _, m := range []Method{Euler, SymplecticEul} {
		r, _ := ReverseTest(s, m, 0.01, 6)
		if r.RelPosErr < 1e-4 {
			t.Errorf("%s is not time-reversible but returned err=%g", m, r.RelPosErr)
		}
	}
	sol := mustBuiltin(t, "solar")
	r, err := ReverseTest(sol, WisdomHolman, 0.05, 20)
	if err != nil || r.RelPosErr > 1e-9 {
		t.Errorf("WH reversibility: %v %v", err, r)
	}
	if _, err := ReverseTest(s, Leapfrog, 0, 1); err == nil {
		t.Error("dt=0 must fail")
	}
}

func TestLyapunovVerdicts(t *testing.T) {
	pl, _ := Builtin("plummer", 16, 1)
	r, err := Lyapunov(pl, Yoshida4, 0.005, 40, 1)
	if err != nil {
		t.Fatal(err)
	}
	if r.Verdict != "chaotic" || r.LambdaLate < 0.5 {
		t.Errorf("16-body Plummer should be chaotic: %+v", r.Verdict)
	}
	tb := mustBuiltin(t, "twobody")
	r, err = Lyapunov(tb, Yoshida4, 0.01, 800, 1)
	if err != nil {
		t.Fatal(err)
	}
	if r.Verdict != "regular" {
		t.Errorf("Kepler orbit must be regular, got %s (efolds %.2f)", r.Verdict, r.EFolds)
	}
	if _, err := Lyapunov(tb, Yoshida4, 1, 5, 1); err == nil {
		t.Error("too few steps must fail")
	}
}

func TestScenarioRoundTripAllBuiltins(t *testing.T) {
	for _, b := range Builtins() {
		s, err := Builtin(b.Name, 25, 7)
		if err != nil {
			t.Fatalf("%s: %v", b.Name, err)
		}
		back, err := ParseScenario(FormatScenario(s))
		if err != nil {
			t.Fatalf("%s round trip: %v", b.Name, err)
		}
		if len(back.Bodies) != len(s.Bodies) || back.G != s.G || back.Eps != s.Eps || back.Theta != s.Theta {
			t.Fatalf("%s header mismatch", b.Name)
		}
		for i := range s.Bodies {
			if back.Bodies[i] != s.Bodies[i] {
				t.Fatalf("%s body %d differs after round trip: %+v vs %+v", b.Name, i, back.Bodies[i], s.Bodies[i])
			}
		}
	}
}

func TestScenarioOrbitDirective(t *testing.T) {
	s, err := ParseScenario("G 1\nbody Sun m=1\nbody P m=1e-3 orbit=Sun a=2 e=0.25 i=10 raan=20 argp=30 ma=40\n")
	if err != nil {
		t.Fatal(err)
	}
	el, err := ElementsFromState(s.Bodies[1].Pos, s.Bodies[1].Vel, 1.001)
	if err != nil {
		t.Fatal(err)
	}
	d := 180 / math.Pi
	for name, p := range map[string][2]float64{"a": {el.A, 2}, "e": {el.E, 0.25}, "i": {el.I * d, 10}, "raan": {el.Raan * d, 20}, "argp": {el.Argp * d, 30}, "M": {el.M * d, 40}} {
		if math.Abs(p[0]-p[1]) > 1e-8 {
			t.Errorf("%s = %v, want %v", name, p[0], p[1])
		}
	}
}

func TestScenarioErrors(t *testing.T) {
	cases := map[string]string{
		"":                                   "no bodies",
		"body A":                             "missing m=",
		"body A m=0":                         "positive",
		"body A m=1 pos=1,2":                 "3 comma",
		"body A m=1 vel=a,b,c":               "bad number",
		"body A m=1 wat=3":                   "unknown keys",
		"body A m=1 m=2":                     "duplicate key",
		"G -1\nbody A m=1":                   "positive",
		"G 1 2\nbody A m=1":                  "exactly one",
		"eps x\nbody A m=1":                  "bad number",
		"body A m=1\nbody B m=1 orbit=A a=0": "a>0",
		"body A m=1\nbody B m=1 orbit=A a=1 pos=1,0,0": "unknown keys",
		"body A m=1 pos=1e999,0,0":                     "bad number",
		"nonsense":                                     "unknown directive",
	}
	for in, want := range cases {
		_, err := ParseScenario(in)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: error %v, want substring %q", in, err, want)
		}
	}
	if _, err := ParseScenario("body A m=1\nbody B m=1 pos=1,0,0 bogus"); err == nil || !strings.Contains(err.Error(), "line 2") {
		t.Errorf("errors must carry line numbers: %v", err)
	}
}

func TestValidateCoincidentAndSoftened(t *testing.T) {
	s := &System{G: 1, Bodies: []Body{{Name: "a", M: 1}, {Name: "b", M: 1}}}
	if err := s.Validate(); err == nil || !strings.Contains(err.Error(), "same point") {
		t.Errorf("coincident bodies must be rejected: %v", err)
	}
	s.Eps = 0.1
	if err := s.Validate(); err != nil {
		t.Errorf("softened coincident bodies are fine: %v", err)
	}
}

func TestBuiltinGeneratorLimits(t *testing.T) {
	for _, c := range []struct {
		name string
		n    int
	}{{"plummer", 1}, {"plummer", -3}, {"plummer", MaxGenerated + 1}, {"disc", -1}, {"disc", MaxGenerated + 1}} {
		if _, err := Builtin(c.name, c.n, 1); err == nil {
			t.Errorf("%s n=%d should fail", c.name, c.n)
		}
	}
	if _, err := Builtin("nope", 0, 1); err == nil {
		t.Error("unknown builtin should fail")
	}
	a, _ := Builtin("plummer", 50, 3)
	b, _ := Builtin("plummer", 50, 3)
	c, _ := Builtin("plummer", 50, 4)
	if a.Bodies[7] != b.Bodies[7] || a.Bodies[7] == c.Bodies[7] {
		t.Error("generators must be deterministic per seed and vary across seeds")
	}
}

func TestPlummerVirialAndEnergy(t *testing.T) {
	s, _ := Builtin("plummer", 2000, 11)
	d := s.Diagnose()
	if math.Abs(d.Virial-1) > 1e-9 {
		t.Errorf("virial ratio %g, want exactly 1", d.Virial)
	}
	p, v := s.COM()
	if p.Norm() > 1e-12 || v.Norm() > 1e-12 {
		t.Errorf("not barycentric: %v %v", p, v)
	}
}

func TestBarnesHutDynamicsTrack(t *testing.T) {
	s, _ := Builtin("plummer", 120, 2)
	s.Theta = 0
	ex, _ := Run(s, Leapfrog, 0.01, 1, 5, 0)
	s.Theta = 0.2
	ap, _ := Run(s, Leapfrog, 0.01, 1, 5, 0)
	if ex.Err != nil || ap.Err != nil {
		t.Fatal(ex.Err, ap.Err)
	}
	var worst float64
	for i := range ex.Final.Bodies {
		worst = math.Max(worst, ex.Final.Bodies[i].Pos.Sub(ap.Final.Bodies[i].Pos).Norm())
	}
	if worst > 5e-3 {
		t.Errorf("tree dynamics deviate from exact by %g after one time unit", worst)
	}
	if ap.Evals != ex.Evals {
		t.Errorf("same integrator should use same eval count")
	}
}

func TestReportIsWellFormed(t *testing.T) {
	s := mustBuiltin(t, "figure8")
	page, err := BuildReport(s, []Method{Euler, Leapfrog, RK4, DOPRI5}, Leapfrog, 0.01, 3, 1e-10)
	if err != nil {
		t.Fatal(err)
	}
	m := regexp.MustCompile(`(?s)<script id="data" type="application/json">(.*?)</script>`).FindStringSubmatch(page)
	if m == nil {
		t.Fatal("no data block")
	}
	var d map[string]any
	if err := json.Unmarshal([]byte(m[1]), &d); err != nil {
		t.Fatalf("embedded JSON invalid: %v", err)
	}
	if len(d["series"].([]any)) != 4 || len(d["frames"].([]any)) < 10 {
		t.Error("report is missing series or frames")
	}
	if strings.Contains(page, "%%") || strings.Contains(page, "http://") || strings.Contains(page, "https://") {
		t.Error("report must be self-contained with no placeholders or network references")
	}
	if _, err := BuildReport(s, []Method{Leapfrog}, RK4, 0.01, 1, 0); err == nil {
		t.Error("view method outside the compared set must fail")
	}
	if _, err := BuildReport(s, nil, Leapfrog, 0.01, 1, 0); err == nil {
		t.Error("empty method list must fail")
	}
	// a blown-up run must still yield valid JSON (no NaN/Inf)
	p, _ := Builtin("pythagorean", 0, 1)
	page, err = BuildReport(p, []Method{Leapfrog, DOPRI5}, DOPRI5, 0.05, 20, 1e-10)
	if err != nil {
		t.Fatal(err)
	}
	m = regexp.MustCompile(`(?s)<script id="data" type="application/json">(.*?)</script>`).FindStringSubmatch(page)
	if err := json.Unmarshal([]byte(m[1]), &d); err != nil {
		t.Fatalf("JSON invalid for chaotic system: %v", err)
	}
}

func TestDopriAdaptiveHandlesCloseEncounter(t *testing.T) {
	p := mustBuiltin(t, "pythagorean")
	res, err := Run(p, DOPRI5, 0.1, 70, 50, 1e-11)
	if err != nil || res.Err != nil {
		t.Fatal(err, res.Err)
	}
	if res.MaxAbsEnergyErr() > 1e-6 {
		t.Errorf("dopri5 energy error %g on the Pythagorean problem", res.MaxAbsEnergyErr())
	}
	if res.Steps < 700 {
		t.Errorf("expected many adaptive steps through close encounters, took %d", res.Steps)
	}
	lf, _ := Run(p, Leapfrog, 0.01, 70, 50, 0)
	if lf.MaxAbsEnergyErr() < 0.1 {
		t.Errorf("fixed-step leapfrog should fail badly here (that is why dopri5 exists), got %g", lf.MaxAbsEnergyErr())
	}
}

func TestDopriBackwardAndLanding(t *testing.T) {
	s := mustBuiltin(t, "twobody")
	w := s.Clone()
	it, _ := NewIntegrator(w, DOPRI5)
	it.Tol = 1e-12
	if err := it.Advance(3.7); err != nil {
		t.Fatal(err)
	}
	if math.Abs(w.T-3.7) > 1e-12 {
		t.Errorf("did not land on target time: %v", w.T)
	}
	if err := it.Advance(-3.7); err != nil {
		t.Fatal(err)
	}
	if d := w.Bodies[1].Pos.Sub(s.Bodies[1].Pos).Norm(); d > 1e-9 {
		t.Errorf("backward integration did not return: %g", d)
	}
}
