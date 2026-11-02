package metrics

import (
	"math"
	"math/rand"
	"testing"

	"kestrel/stat"
)

func TestOSPAKnown(t *testing.T) {
	a := []Pt{{1, 0, 0}, {2, 100, 0}}
	if d, _, _, _ := OSPA(a, a, 500, 2); d != 0 {
		t.Errorf("identical sets: %v", d)
	}
	if d, _, c, _ := OSPA(a, nil, 500, 2); d != 500 || c != 500 {
		t.Errorf("empty estimate: %v %v", d, c)
	}
	if d, _, _, _ := OSPA(nil, nil, 500, 2); d != 0 {
		t.Error("both empty")
	}
	// one extra false estimate: cardinality term sqrt(c²·1/2)
	d, loc, card, _ := OSPA(a, append(append([]Pt{}, a...), Pt{3, 5000, 5000}), 500, 2)
	if math.Abs(loc) > 1e-9 || math.Abs(card-500/math.Sqrt(3)) > 1e-9 || math.Abs(d-card) > 1e-9 {
		t.Errorf("extra track: total %v loc %v card %v", d, loc, card)
	}
	// localisation only: shift both by 30 m
	b := []Pt{{1, 30, 0}, {2, 130, 0}}
	if d, _, _, _ := OSPA(a, b, 500, 2); math.Abs(d-30) > 1e-9 {
		t.Errorf("shift: %v", d)
	}
	if _, _, _, err := OSPA(a, a, 0, 2); err == nil {
		t.Error("c<=0 must error")
	}
}

func TestOSPAMetricProperties(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	mk := func() []Pt {
		n := rng.Intn(4)
		p := make([]Pt, n)
		for i := range p {
			p[i] = Pt{i, rng.Float64() * 800, rng.Float64() * 800}
		}
		return p
	}
	for i := 0; i < 300; i++ {
		x, y, z := mk(), mk(), mk()
		xy, _, _, _ := OSPA(x, y, 400, 2)
		yx, _, _, _ := OSPA(y, x, 400, 2)
		xz, _, _, _ := OSPA(x, z, 400, 2)
		zy, _, _, _ := OSPA(z, y, 400, 2)
		if math.Abs(xy-yx) > 1e-9 {
			t.Fatal("OSPA not symmetric")
		}
		if xy > xz+zy+1e-9 {
			t.Fatalf("triangle inequality violated: %v > %v + %v", xy, xz, zy)
		}
		if xy < 0 || xy > 400+1e-9 {
			t.Fatal("OSPA outside [0,c]")
		}
	}
}

func TestScorerIDSwitchAndMisses(t *testing.T) {
	s := NewScorer(100)
	truth := []Pt{{1, 0, 0}, {2, 50, 0}}
	s.Add(truth, []Pt{{10, 0, 0}, {11, 50, 0}})
	s.Add(truth, []Pt{{10, 0, 0}, {11, 50, 0}})
	// tracks swap targets
	s.Add(truth, []Pt{{10, 50, 0}, {11, 0, 0}})
	s.Add(truth, []Pt{{10, 0, 0}}) // track 11 lost: one missed target
	s.Add(truth[:1], []Pt{{10, 0, 0}, {12, 900, 900}})
	r := s.Summary()
	// 10: T1→T2 (1), 11: T2→T1 (2), then 10 returns to T1 (3)
	if r.IDSwitches != 3 {
		t.Errorf("ID switches %d want 3", r.IDSwitches)
	}
	if r.MissedScans != 1 || r.FalseTrackScans != 1 {
		t.Errorf("missed %d false %d want 1,1", r.MissedScans, r.FalseTrackScans)
	}
	if r.Tracks != 3 || r.Frames != 5 {
		t.Errorf("tracks %d frames %d", r.Tracks, r.Frames)
	}
}

func TestConsistencyTestCalibration(t *testing.T) {
	// samples drawn from a true χ²₄ pass; inflated samples fail
	rng := stat.NewRNG(1)
	draw := func(scale float64, n int) []float64 {
		out := make([]float64, n)
		for i := range out {
			s := 0.0
			for k := 0; k < 4; k++ {
				z := rng.Norm()
				s += z * z
			}
			out[i] = s * scale
		}
		return out
	}
	if c, err := ConsistencyTest(draw(1, 5000), 4, 0.01); err != nil || !c.Consistent {
		t.Errorf("honest samples rejected: %+v %v", c, err)
	}
	if c, _ := ConsistencyTest(draw(1.2, 5000), 4, 0.05); c.Consistent {
		t.Errorf("20%% overconfident samples accepted: %+v", c)
	}
	if _, err := ConsistencyTest(nil, 4, 0.05); err == nil {
		t.Error("no samples must error")
	}
	if _, err := ConsistencyTest([]float64{-1}, 2, 0.05); err == nil {
		t.Error("negative sample must error")
	}
}
