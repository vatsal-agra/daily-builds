package tracker

import (
	"math"
	"strings"
	"testing"

	"kestrel/mat"
	"kestrel/sim"
)

func run(t *testing.T, scn, fl, as string, seed int64, trace bool) *Run {
	t.Helper()
	sc, err := sim.Lookup(scn)
	if err != nil {
		t.Fatal(err)
	}
	o := DefaultOptions()
	o.Filter, o.Assoc, o.Trace = fl, as, trace
	cfg, err := ForScenario(sc, o)
	if err != nil {
		t.Fatal(err)
	}
	fr, _ := sc.Run(seed)
	r, err := RunFrames(sc, fr, cfg)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestEveryScenarioTracksWell(t *testing.T) {
	for _, sc := range sim.Scenarios() {
		if sc.Name == "knot" { // stress test: judged separately
			continue
		}
		for _, fl := range []string{"ekf", "ukf", "imm-ekf"} {
			var cov, sw, tracks float64
			for seed := int64(1); seed <= 4; seed++ {
				r := run(t, sc.Name, fl, "gnn", seed, false)
				cov += r.Score.Coverage
				sw += float64(r.Score.IDSwitches)
				tracks += float64(r.Score.Tracks)
			}
			cov /= 4
			if cov < 0.88 {
				t.Errorf("%s/%s coverage %.2f", sc.Name, fl, cov)
			}
			if sw > 0 {
				t.Errorf("%s/%s ID switches %v", sc.Name, fl, sw)
			}
			// CV-only filters legitimately lose manoeuvring targets (that is what the IMM is for)
			if !(sc.Name == "manoeuvre" && !strings.HasPrefix(fl, "imm")) && tracks/4 > float64(len(sc.Targets))+1.5 {
				t.Errorf("%s/%s averaged %.1f tracks for %d targets", sc.Name, fl, tracks/4, len(sc.Targets))
			}
		}
	}
}

func TestIMMBeatsCVOnManoeuvres(t *testing.T) {
	var ekf, imm float64
	for seed := int64(1); seed <= 6; seed++ {
		ekf += run(t, "manoeuvre", "ekf", "gnn", seed, false).Score.MeanOSPA
		imm += run(t, "manoeuvre", "imm-ekf", "gnn", seed, false).Score.MeanOSPA
	}
	if imm > 0.7*ekf {
		t.Errorf("IMM OSPA %.0f vs EKF %.0f: expected at least 30%% better", imm/6, ekf/6)
	}
}

func TestTrackBirthAndDeath(t *testing.T) {
	r := run(t, "birthdeath", "ekf", "gnn", 2, false)
	var born2, ended1 bool
	for _, tr := range r.Tracker.AllTracks() {
		if tr.Hits < 10 {
			continue
		}
		last := tr.History[len(tr.History)-1].T
		if tr.Born >= 18 && tr.Born <= 30 { // target 2 appears at t=20
			born2 = true
		}
		if last >= 66 && last <= 84 && tr.Status == Deleted { // target 1 vanishes at t=70
			ended1 = true
		}
	}
	if !born2 || !ended1 {
		t.Errorf("birth of target 2 detected=%v, death of target 1 detected=%v", born2, ended1)
	}
}

func TestPureClutterMakesNoConfirmedTracksMostly(t *testing.T) {
	sc, _ := sim.Lookup("cruise")
	sc.Targets = nil
	sc.Duration = 200
	cfg, _ := ForScenario(sc, DefaultOptions())
	fr, _ := sc.Run(4)
	r, err := RunFrames(sc, fr, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if r.Score.Tracks > 2 {
		t.Errorf("%d tracks confirmed from pure clutter in 100 scans", r.Score.Tracks)
	}
}

func TestJPDAandGNNBothHandleKnot(t *testing.T) {
	for _, as := range []string{"gnn", "jpda"} {
		var sw int
		var cov float64
		for seed := int64(1); seed <= 5; seed++ {
			r := run(t, "knot", "ekf", as, seed, false)
			sw += r.Score.IDSwitches
			cov += r.Score.Coverage
		}
		if cov/5 < 0.8 {
			t.Errorf("%s knot coverage %.2f", as, cov/5)
		}
		if sw > 8 {
			t.Errorf("%s knot ID switches %d over 5 seeds", as, sw)
		}
	}
	if _, err := New(Config{}); err == nil {
		t.Error("empty config must be rejected")
	}
}

func TestJPDARejectsIMM(t *testing.T) {
	sc, _ := sim.Lookup("cruise")
	o := DefaultOptions()
	o.Filter, o.Assoc = "imm-ekf", "jpda"
	cfg, _ := ForScenario(sc, o)
	fr, _ := sc.Run(1)
	if _, err := RunFrames(sc, fr, cfg); err == nil || !strings.Contains(err.Error(), "IMM") {
		t.Errorf("want clear IMM/JPDA error, got %v", err)
	}
}

func TestMalformedInputIsRejectedNotPanicked(t *testing.T) {
	sc, _ := sim.Lookup("cruise")
	cfg, _ := ForScenario(sc, DefaultOptions())
	tr, _ := New(cfg)
	for _, bad := range []*mat.M{mat.Vec(math.NaN(), 0), mat.Vec(math.Inf(1), 0), mat.Vec(1), nil} {
		if err := tr.Step(1, []*mat.M{bad}); err == nil {
			t.Errorf("malformed detection %v accepted", bad)
		}
	}
	if err := tr.Step(2, nil); err != nil {
		t.Errorf("empty scan must be fine: %v", err)
	}
	if err := tr.Step(2, nil); err == nil {
		t.Error("repeated timestamp must be rejected")
	}
	if err := tr.Step(1, nil); err == nil {
		t.Error("backwards timestamp must be rejected")
	}
}

func TestConfigValidation(t *testing.T) {
	sc, _ := sim.Lookup("cruise")
	base, _ := ForScenario(sc, DefaultOptions())
	muts := map[string]func(*Config){
		"pd":      func(c *Config) { c.Pd = 1 },
		"clutter": func(c *Config) { c.ClutterDensity = 0 },
		"gate":    func(c *Config) { c.GateProb = 1 },
		"confirm": func(c *Config) { c.ConfirmM = 6 },
		"maxmiss": func(c *Config) { c.MaxMiss = 0 },
		"assoc":   func(c *Config) { c.Assoc = "nn" },
		"noradar": func(c *Config) { c.Radar = nil },
	}
	for name, m := range muts {
		c := base
		m(&c)
		if _, err := New(c); err == nil {
			t.Errorf("%s: invalid config accepted", name)
		}
	}
	if _, err := ForScenario(sc, Options{Filter: "kf"}); err == nil {
		t.Error("unknown tracker filter must error")
	}
}

func TestSmoothedTracksAreMoreAccurate(t *testing.T) {
	r := run(t, "cruise", "ekf", "gnn", 1, true)
	truth := map[float64][]sim.Truth{}
	for _, f := range r.Frames {
		truth[f.T] = f.Truth
	}
	near := func(tm, x, y float64) float64 {
		best := math.Inf(1)
		for _, g := range truth[tm] {
			best = math.Min(best, (g.X-x)*(g.X-x)+(g.Y-y)*(g.Y-y))
		}
		return best
	}
	var sf, ss float64
	var n int
	for _, tr := range r.Tracker.Confirmed() {
		sp, err := tr.Smoothed()
		if err != nil {
			t.Fatal(err)
		}
		for i, p := range tr.History {
			sf += near(p.T, p.X, p.Y)
			ss += near(sp[i].T, sp[i].X, sp[i].Y)
			n++
		}
	}
	if n == 0 || math.Sqrt(ss/float64(n)) >= math.Sqrt(sf/float64(n)) {
		t.Errorf("smoothed RMSE %.1f not better than filtered %.1f", math.Sqrt(ss/float64(n)), math.Sqrt(sf/float64(n)))
	}
	if _, err := run(t, "cruise", "ekf", "gnn", 1, false).Tracker.Confirmed()[0].Smoothed(); err == nil {
		t.Error("Smoothed without Trace must error")
	}
}

func TestTrackerNISIsCalibrated(t *testing.T) {
	// innovations of confirmed tracks in a benign scenario should average ≈ 2 (2-DOF measurement)
	r := run(t, "cruise", "ekf", "gnn", 1, false)
	if len(r.Tracker.NISLog) < 50 {
		t.Fatal("too few NIS samples")
	}
	s := 0.0
	for _, v := range r.Tracker.NISLog {
		s += v
	}
	if m := s / float64(len(r.Tracker.NISLog)); m < 1.2 || m > 3.0 {
		t.Errorf("mean NIS %.2f, want ≈ 2", m)
	}
}
