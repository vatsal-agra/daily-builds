package assoc

import (
	"math"
	"math/rand"
	"testing"
)

func brute(c [][]float64) float64 {
	n, m := len(c), len(c[0])
	best := math.Inf(1)
	used := make([]bool, m)
	var rec func(i int, s float64)
	rec = func(i int, s float64) {
		if i == n {
			best = math.Min(best, s)
			return
		}
		for j := 0; j < m; j++ {
			if !used[j] && !math.IsInf(c[i][j], 1) {
				used[j] = true
				rec(i+1, s+c[i][j])
				used[j] = false
			}
		}
	}
	rec(0, 0)
	return best
}

func TestHungarianAgainstBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for it := 0; it < 3000; it++ {
		n := 1 + rng.Intn(5)
		m := n + rng.Intn(4)
		c := make([][]float64, n)
		for i := range c {
			c[i] = make([]float64, m)
			for j := range c[i] {
				if rng.Float64() < 0.3 {
					c[i][j] = math.Inf(1)
				} else {
					c[i][j] = rng.NormFloat64() * 10
				}
			}
		}
		want := brute(c)
		col, got, err := Hungarian(c)
		if math.IsInf(want, 1) {
			if err != ErrInfeasible {
				t.Fatalf("expected ErrInfeasible, got %v", err)
			}
			continue
		}
		if err != nil || math.Abs(got-want) > 1e-9 {
			t.Fatalf("got %v (%v) want %v", got, err, want)
		}
		seen := map[int]bool{}
		for _, j := range col {
			if seen[j] {
				t.Fatal("column assigned twice")
			}
			seen[j] = true
		}
	}
}

func TestHungarianInputErrors(t *testing.T) {
	if _, _, err := Hungarian([][]float64{{1}, {2}}); err == nil {
		t.Error("rows>cols must error")
	}
	if _, _, err := Hungarian([][]float64{{1, 2}, {3}}); err == nil {
		t.Error("ragged must error")
	}
	if _, _, err := Hungarian([][]float64{{math.NaN(), 1}}); err == nil {
		t.Error("NaN must error")
	}
	if col, tot, err := Hungarian(nil); err != nil || col != nil || tot != 0 {
		t.Error("empty problem is trivially solved")
	}
}

func TestGNNPrefersMissOverBadMatch(t *testing.T) {
	par := Params{Gate: 13.8, Pd: 0.9, ClutterDensity: 1e-3}
	// one track, one detection with very low likelihood: a miss is cheaper than a clutter-grade pairing
	weak := [][]*Candidate{{{D2: 13, LogLik: -30}}}
	got, err := GNN(weak, par)
	if err != nil || got[0] != -1 {
		t.Fatalf("weak pairing should be declined, got %v %v", got, err)
	}
	strong := [][]*Candidate{{{D2: 0.5, LogLik: -8}}}
	got, _ = GNN(strong, par)
	if got[0] != 0 {
		t.Fatalf("strong pairing should be taken, got %v", got)
	}
}

func TestGNNResolvesConflictGlobally(t *testing.T) {
	par := Params{Gate: 13.8, Pd: 0.95, ClutterDensity: 1e-4}
	// track0 likes det0 slightly more than det1; track1 can ONLY take det0.
	// Greedy nearest-neighbour would give det0 to track0 and starve track1; GNN must give det1 to track0.
	c := [][]*Candidate{
		{{LogLik: -5.0}, {LogLik: -5.5}},
		{{LogLik: -5.0}, nil},
	}
	got, err := GNN(c, par)
	if err != nil {
		t.Fatal(err)
	}
	if got[0] != 1 || got[1] != 0 {
		t.Fatalf("assignment %v, want [1 0]", got)
	}
}
