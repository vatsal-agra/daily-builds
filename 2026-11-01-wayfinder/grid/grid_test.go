package grid

import (
	"math/big"
	"math/rand"
	"strings"
	"testing"
)

// refLOS is an independent exact reference for LineOfSight using rational
// arithmetic: every cell whose open interior the segment crosses must be open,
// and every lattice vertex the segment passes through needs all four
// surrounding cells open.
func refLOS(g *Grid, a, b Point) bool {
	if !g.Open(a.X, a.Y) || !g.Open(b.X, b.Y) {
		return false
	}
	// Doubled coordinates: centres at (2x,2y), cell (i,j) = [2i-1,2i+1]x[2j-1,2j+1].
	ax, ay, bx, by := int64(2*a.X), int64(2*a.Y), int64(2*b.X), int64(2*b.Y)
	minX, maxX := min(a.X, b.X)-1, max(a.X, b.X)+1
	minY, maxY := min(a.Y, b.Y)-1, max(a.Y, b.Y)+1
	for j := minY; j <= maxY; j++ {
		for i := minX; i <= maxX; i++ {
			if g.Open(i, j) {
				continue
			}
			if segCrossesOpenSquare(ax, ay, bx, by, int64(2*i-1), int64(2*j-1), int64(2*i+1), int64(2*j+1)) {
				return false
			}
		}
	}
	// vertices on the segment (strictly between endpoints)
	dx, dy := bx-ax, by-ay
	for j := minY; j <= maxY+1; j++ {
		for i := minX; i <= maxX+1; i++ {
			vx, vy := int64(2*i-1), int64(2*j-1)
			if (vx-ax)*dy-(vy-ay)*dx != 0 {
				continue
			}
			// within segment bounds, excluding endpoints (which are cell centres, never vertices)
			if vx < min(ax, bx) || vx > max(ax, bx) || vy < min(ay, by) || vy > max(ay, by) {
				continue
			}
			if !g.Open(i-1, j-1) || !g.Open(i, j-1) || !g.Open(i-1, j) || !g.Open(i, j) {
				return false
			}
		}
	}
	return true
}

// segCrossesOpenSquare: does segment A-B intersect the open square (x0,x1)x(y0,y1) with positive length?
func segCrossesOpenSquare(ax, ay, bx, by, x0, y0, x1, y1 int64) bool {
	// Liang–Barsky on rationals: t range where x0<x<x1 and y0<y<y1.
	lo, hi := big.NewRat(0, 1), big.NewRat(1, 1)
	clip := func(p, q int64) bool { // constraint p*t < q  (strict) with t in [lo,hi]
		if p == 0 {
			return q > 0
		}
		r := big.NewRat(q, p)
		if p > 0 { // t < r
			if r.Cmp(hi) < 0 {
				hi = r
			}
		} else { // t > r
			if r.Cmp(lo) > 0 {
				lo = r
			}
		}
		return true
	}
	dx, dy := bx-ax, by-ay
	if !clip(dx, x1-ax) || !clip(-dx, -(x0-ax)) || !clip(dy, y1-ay) || !clip(-dy, -(y0-ay)) {
		return false
	}
	return lo.Cmp(hi) < 0
}

func TestLineOfSightMatchesExactReference(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	checked, trueCount := 0, 0
	for it := 0; it < 400; it++ {
		g := New(12, 12)
		dens := 0.05 + rng.Float64()*0.3
		for i := range g.Cost {
			if rng.Float64() < dens {
				g.Cost[i] = 0
			}
		}
		for k := 0; k < 60; k++ {
			a := Point{rng.Intn(12), rng.Intn(12)}
			b := Point{rng.Intn(12), rng.Intn(12)}
			got, want := g.LineOfSight(a, b), refLOS(g, a, b)
			if got != want {
				t.Fatalf("LOS(%v,%v)=%v want %v\n%s", a, b, got, want, g.Format())
			}
			if got != g.LineOfSight(b, a) {
				t.Fatalf("LOS not symmetric for %v %v\n%s", a, b, g.Format())
			}
			checked++
			if got {
				trueCount++
			}
		}
	}
	if trueCount < 2000 || checked-trueCount < 2000 {
		t.Fatalf("test not discriminating: %d true of %d", trueCount, checked)
	}
}

func TestParseFormatRoundTrip(t *testing.T) {
	for _, kind := range Kinds {
		g, err := Generate(kind, 30, 20, 4, 0.2, 0.4)
		if err != nil {
			t.Fatal(kind, err)
		}
		g2, err := Parse(g.Format())
		if err != nil {
			t.Fatal(kind, err)
		}
		if g2.Format() != g.Format() || string(g2.Cost) != string(g.Cost) || g2.Start != g.Start || g2.Goal != g.Goal {
			t.Fatalf("%s: round trip changed the map (terrain under S/G?)", kind)
		}
	}
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"empty":        "",
		"only comment": "// hi\n",
		"no start":     "...\n..G\n",
		"two goals":    "S.G\nG..\n",
		"ragged":       "S..\n..G.\n",
		"bad glyph":    "S?.\n..G\n",
	}
	for name, in := range cases {
		if _, err := Parse(in); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	g, err := Parse("// c\r\nS.#\r\n..G  \r\n")
	if err != nil || g.W != 3 || g.H != 2 {
		t.Fatalf("CRLF/trailing spaces: %v %+v", err, g)
	}
}

func TestGenerateValidation(t *testing.T) {
	bad := []struct {
		kind string
		w, h int
		d, t float64
	}{{"nope", 10, 10, .1, 0}, {"random", 2, 10, .1, 0}, {"random", 10, 10, .9, 0}, {"random", 10, 10, .1, 2}, {"random", 5000, 10, .1, 0}}
	for _, b := range bad {
		if _, err := Generate(b.kind, b.w, b.h, 1, b.d, b.t); err == nil {
			t.Errorf("expected error for %+v", b)
		}
	}
	// every kind at awkward sizes must either error cleanly or give a solvable pair
	for _, kind := range Kinds {
		for _, sz := range [][2]int{{3, 3}, {4, 4}, {5, 5}, {6, 9}, {20, 3}} {
			for seed := int64(0); seed < 20; seed++ {
				g, err := Generate(kind, sz[0], sz[1], seed, 0.3, 0)
				if err != nil {
					continue
				}
				comp := g.Component(g.Start)
				ok := false
				for _, p := range comp {
					if p == g.Goal {
						ok = true
					}
				}
				if !ok || g.Start == g.Goal {
					t.Fatalf("%s %v seed %d: bad endpoints\n%s", kind, sz, seed, g.Format())
				}
			}
		}
	}
	if !strings.Contains(New(3, 3).Format(), "S") {
		t.Fatal("format lost start")
	}
}
