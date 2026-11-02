package lab

import "testing"

func base() Config { return Config{Runs: 400, Steps: 30, Dt: 2, Q: 0.5, Seed: 11, Alpha: 0.001} }

func TestHonestFiltersAreConsistent(t *testing.T) {
	for _, c := range []struct{ f, s string }{{"kf", "cartesian"}, {"ekf", "radar"}, {"ukf", "radar"}, {"ekf", "cartesian"}} {
		cfg := base()
		cfg.Filter, cfg.Sensor = c.f, c.s
		r, err := Consistency(cfg)
		if err != nil {
			t.Fatal(err)
		}
		if !r.NEES.Consistent || !r.NIS.Consistent {
			t.Errorf("%s/%s: NEES %.3f [%.3f,%.3f] NIS %.3f [%.3f,%.3f]", c.f, c.s, r.NEES.Mean, r.NEES.Lo, r.NEES.Hi, r.NIS.Mean, r.NIS.Lo, r.NIS.Hi)
		}
	}
}

func TestMismatchedNoiseIsCaught(t *testing.T) {
	cfg := base()
	cfg.Filter, cfg.Sensor, cfg.MismatchQ = "kf", "cartesian", 0.005
	r, err := Consistency(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if r.NEES.Consistent || r.NEES.Mean < 8 {
		t.Errorf("100x too-small Q must be flagged: NEES mean %.2f consistent=%v", r.NEES.Mean, r.NEES.Consistent)
	}
	cfg.MismatchQ = 50 // far too large: conservative filter, NEES well below 4
	r, _ = Consistency(cfg)
	if r.NEES.Consistent || r.NEES.Mean > 3.5 {
		t.Errorf("too-large Q must be flagged conservative: NEES %.2f", r.NEES.Mean)
	}
}

func TestInvalidConfigs(t *testing.T) {
	for _, c := range []Config{
		{Filter: "kf", Sensor: "radar", Runs: 10, Steps: 10, Dt: 1, Q: 1},
		{Filter: "kf", Sensor: "cartesian", Runs: 1, Steps: 10, Dt: 1, Q: 1},
		{Filter: "kf", Sensor: "cartesian", Runs: 10, Steps: 10, Dt: 0, Q: 1},
		{Filter: "zzz", Sensor: "cartesian", Runs: 10, Steps: 10, Dt: 1, Q: 1},
		{Filter: "kf", Sensor: "lidar", Runs: 10, Steps: 10, Dt: 1, Q: 1},
	} {
		if _, err := Consistency(c); err == nil {
			t.Errorf("config %+v accepted", c)
		}
	}
}

func TestSmootherBeatsFilterAndStaysConsistent(t *testing.T) {
	r, err := Smoothing(Config{Runs: 300, Steps: 30, Dt: 2, Q: 0.5, Seed: 3})
	if err != nil {
		t.Fatal(err)
	}
	if r.SmoothedRMSE >= 0.6*r.FilteredRMSE {
		t.Errorf("smoothed %.1f vs filtered %.1f: expected a large gain", r.SmoothedRMSE, r.FilteredRMSE)
	}
	if !r.SmoothedNEES.Consistent {
		t.Errorf("smoothed NEES %.3f outside [%.3f,%.3f]", r.SmoothedNEES.Mean, r.SmoothedNEES.Lo, r.SmoothedNEES.Hi)
	}
}
