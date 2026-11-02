package sim

import (
	"math"
	"strings"
	"testing"
)

func TestDeterministicAndSeedSensitive(t *testing.T) {
	sc, _ := Lookup("cruise")
	a, _ := sc.Run(5)
	b, _ := sc.Run(5)
	c, _ := sc.Run(6)
	if len(a) != len(b) || len(a[3].Dets) != len(b[3].Dets) || a[3].Dets[0].Z.D[0] != b[3].Dets[0].Z.D[0] {
		t.Fatal("same seed must reproduce identical frames")
	}
	same := true
	for i := range a {
		if len(a[i].Dets) != len(c[i].Dets) {
			same = false
		}
	}
	if same {
		t.Fatal("different seeds should differ")
	}
}

func TestStatisticsMatchRadarModel(t *testing.T) {
	sc, _ := Lookup("cruise")
	sc.Duration = 4000
	sc.Targets = []Target{{ID: 1, Dies: 1e9, X: 6000, Y: 6000}} // hovering, always in coverage
	fr, _ := sc.Run(1)
	var det, opp, clut int
	var errR []float64
	for _, f := range fr {
		for _, g := range f.Truth {
			if g.ID == 1 && g.InCoverage {
				opp++
			}
		}
		for _, d := range f.Dets {
			if d.Source == 0 {
				clut++
			} else if d.Source == 1 {
				det++
				for _, g := range f.Truth {
					if g.ID == 1 {
						errR = append(errR, d.Z.D[0]-math.Hypot(g.X, g.Y))
					}
				}
			}
		}
	}
	if pd := float64(det) / float64(opp); math.Abs(pd-0.95) > 0.02 {
		t.Errorf("empirical Pd %.3f want 0.95", pd)
	}
	if m := float64(clut) / float64(len(fr)); math.Abs(m-2) > 0.1 {
		t.Errorf("clutter/scan %.2f want 2", m)
	}
	var s2 float64
	for _, e := range errR {
		s2 += e * e
	}
	if sd := math.Sqrt(s2 / float64(len(errR))); math.Abs(sd-25) > 1.5 {
		t.Errorf("range error σ %.2f want 25", sd)
	}
}

func TestTruthKinematics(t *testing.T) {
	// coordinated turn of 90° at constant speed
	tg := Target{ID: 1, Dies: 1e9, VX: 100, Legs: []Leg{{Until: 1e9, Omega: math.Pi / 20}}}
	tr := tg.truthAt(10) // ω·t = π/2
	if math.Abs(math.Hypot(tr.VX, tr.VY)-100) > 1e-6 || math.Abs(tr.VX) > 1e-6 || math.Abs(tr.VY-100) > 1e-6 {
		t.Errorf("turn velocity %+v", tr)
	}
	acc := Target{ID: 2, Dies: 1e9, VX: 0, Legs: []Leg{{Until: 1e9, Ax: 2}}}
	if a := acc.truthAt(10); math.Abs(a.X-100) > 1e-6 || math.Abs(a.VX-20) > 1e-6 {
		t.Errorf("acceleration %+v", a)
	}
}

func TestValidation(t *testing.T) {
	good, _ := Lookup("cruise")
	bad := []func(*Scenario){
		func(s *Scenario) { s.Dt = 0 },
		func(s *Scenario) { s.Radar.Pd = 1.2 },
		func(s *Scenario) { s.Radar.SigR = 0 },
		func(s *Scenario) { s.Radar.RMax = s.Radar.RMin },
		func(s *Scenario) { s.Targets[1].ID = s.Targets[0].ID },
		func(s *Scenario) { s.Targets[0].Dies = -1 },
		func(s *Scenario) { s.Targets[0].Legs = []Leg{{Until: 10}, {Until: 5}} },
	}
	for i, mut := range bad {
		s := good
		s.Targets = append([]Target(nil), good.Targets...)
		mut(&s)
		if _, err := s.Run(1); err == nil {
			t.Errorf("case %d: invalid scenario accepted", i)
		}
	}
	if _, err := Lookup("nonexistent"); err == nil || !strings.Contains(err.Error(), "available") {
		t.Error("unknown scenario should list the available ones")
	}
}

func TestCoverageFlag(t *testing.T) {
	sc, _ := Lookup("cruise")
	sc.Targets = []Target{{ID: 1, Dies: 1e9, X: 19700, VX: 100}}
	fr, _ := sc.Run(1)
	if !fr[0].Truth[0].InCoverage || fr[len(fr)-1].Truth[0].InCoverage {
		t.Error("target should start in coverage and leave it")
	}
	for _, d := range fr[len(fr)-1].Dets {
		if d.Source == 1 {
			t.Error("target outside coverage must not be detected")
		}
	}
}
