package life

import (
	"math/rand"
	"testing"
)

func soup(rng *rand.Rand, w, h int, density float64) []Point {
	var pts []Point
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			if rng.Float64() < density {
				pts = append(pts, Point{int64(x), int64(y)})
			}
		}
	}
	return pts
}

func TestGliderMoves(t *testing.T) {
	s := NewSim(Life)
	s.SetCells([]Point{{1, 0}, {2, 1}, {0, 2}, {1, 2}, {2, 2}}, false)
	if err := s.Step(400); err != nil {
		t.Fatal(err)
	}
	if s.Population() != 5 {
		t.Fatalf("pop %d", s.Population())
	}
	x0, y0, _, _, _ := s.BBox()
	if x0 != 100 || y0 != 100 {
		t.Fatalf("bbox %d,%d want 100,100", x0, y0)
	}
}

func TestMatchesNaive(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	rules := []string{"B3/S23", "B36/S23", "B2/S", "B3678/S34678", "B34/S34", "B1357/S1357"}
	for _, rs := range rules {
		r, _ := ParseRule(rs)
		for trial := 0; trial < 6; trial++ {
			pts := soup(rng, 5+rng.Intn(20), 5+rng.Intn(20), 0.2+rng.Float64()*0.4)
			s := NewSim(r)
			s.SetCells(append([]Point(nil), pts...), false)
			nv := NewNaive(r, pts)
			for _, steps := range []uint64{1, 2, 3, 7, 16, 33} {
				if err := s.Step(steps); err != nil {
					t.Fatal(err)
				}
				nv.StepN(steps)
				if !nv.EqualSim(s, 0, 0) {
					t.Fatalf("rule %s trial %d gen %d mismatch", rs, trial, nv.Gen)
				}
			}
		}
	}
}
