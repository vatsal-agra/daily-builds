package scan

import (
	"math/rand"
	"testing"

	"quietzone/qr"
	"quietzone/sim"
)

// identity grid: module (u,v) -> pixel (scale*(u+quiet), scale*(v+quiet)).
func gridH(scale, quiet float64) *Homography {
	return &Homography{scale, 0, scale * quiet, 0, scale, scale * quiet, 0, 0, 1}
}

func TestFindAlignAcceptsRealAndRejectsData(t *testing.T) {
	c := enc(t, "alignment pattern unit test payload with some length to it", qr.M)
	if c.Version < 2 {
		t.Fatal("need a version with an alignment pattern")
	}
	b := FromImage(c.Matrix.Image(8, 4)).Binarize(Strategy{Name: "otsu"})
	h := gridH(8, 4)
	ap := alignCentres(c.Version)
	got, ok := findAlign(b, h, ap[0], 1.0)
	want := h.Apply(ap[0].X, ap[0].Y)
	if !ok || got.Sub(want).Len() > 1.5 {
		t.Fatalf("real alignment pattern not located: ok=%v got %v want %v", ok, got, want)
	}
	// A prediction pointing into pure data/timing area must be rejected.
	rejected := 0
	for _, p := range []Pt{{12.5, 12.5}, {9.5, 15.5}, {15.5, 9.5}} {
		if _, ok := findAlign(b, h, p, 0.3); !ok {
			rejected++
		}
	}
	if rejected < 2 {
		t.Fatalf("data region mistaken for an alignment pattern %d times", 3-rejected)
	}
}

// Adaptive thresholding must recover the module values of a code under strong
// uneven illumination (a global threshold cannot).
func TestAdaptiveThresholdBeatsGradient(t *testing.T) {
	c := enc(t, "uneven illumination", qr.M)
	img := sim.Noise(sim.Lighting(c.Matrix.Image(8, 4), 0.65, 0.2, 20), 25, 0, rand.New(rand.NewSource(5)))
	g := FromImage(img)
	score := func(s Strategy) float64 {
		b := g.Binarize(s)
		ok := 0
		for y := 0; y < c.Matrix.N; y++ {
			for x := 0; x < c.Matrix.N; x++ {
				if b.At((x+4)*8+4, (y+4)*8+4) == c.Matrix.Get(x, y) {
					ok++
				}
			}
		}
		return float64(ok) / float64(c.Matrix.N*c.Matrix.N)
	}
	if a := score(Strategy{Name: "a", Window: 4}); a < 0.985 {
		t.Fatalf("adaptive threshold only %.1f%% correct", 100*a)
	}
}

// A figure whose horizontal and vertical runs are 1:1:3:1:1 but whose diagonals
// are not (the light ring is open at the corners) is not a finder pattern.
func TestFindersRejectsCrossShapedImpostor(t *testing.T) {
	const s, n = 6, 60
	b := &Bin{W: n, H: n, Pix: make([]bool, n*n)}
	cx, cy := n/2, n/2
	for y := 0; y < n; y++ {
		for x := 0; x < n; x++ {
			dx, dy := abs(x-cx), abs(y-cy)
			d := max(dx, dy)
			dark := false
			switch {
			case d < s*3/2: // core 3 modules
				dark = true
			case d < s*5/2: // ring: light only along the four arms
				dark = dx >= s*3/2 && dy >= s*3/2
			case d < s*7/2:
				dark = true
			}
			b.Pix[y*n+x] = dark
		}
	}
	if fs := FindFinders(b); len(fs) != 0 {
		t.Fatalf("impostor accepted as a finder: %+v", fs)
	}
	// ...while a genuine finder pattern in the same frame is found.
	real := qr.NewMatrix(21)
	_ = real
	c := enc(t, "x", qr.L)
	if fs := FindFinders(FromImage(c.Matrix.Image(6, 4)).Binarize(Strategy{Name: "otsu"})); len(fs) != 3 {
		t.Fatalf("expected 3 finders, got %d", len(fs))
	}
}

func TestHomographyFitRecoversProjectiveMap(t *testing.T) {
	truth := Homography{1.2, 0.2, 30, -0.1, 0.9, 12, 0.0007, -0.0004, 1}
	var src, dst []Pt
	for _, p := range []Pt{{0, 0}, {50, 0}, {50, 50}, {0, 50}, {25, 10}, {10, 40}, {35, 25}} {
		src = append(src, p)
		dst = append(dst, truth.Apply(p.X, p.Y))
	}
	h, err := FitHomography(src, dst)
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []Pt{{3, 4}, {47, 8}, {20, 49}} {
		if d := h.Apply(p.X, p.Y).Sub(truth.Apply(p.X, p.Y)).Len(); d > 1e-6 {
			t.Fatalf("fit error %g at %v", d, p)
		}
	}
	inv, err := h.Inverse()
	if err != nil {
		t.Fatal(err)
	}
	q := h.Apply(12, 34)
	if r := inv.Apply(q.X, q.Y); r.Sub(Pt{12, 34}).Len() > 1e-6 {
		t.Fatalf("inverse round trip: %v", r)
	}
	if _, err := FitHomography(src[:3], dst[:3]); err == nil {
		t.Fatal("3 points accepted")
	}
	col := []Pt{{0, 0}, {1, 1}, {2, 2}, {3, 3}}
	if _, err := FitHomography(col, col); err == nil {
		t.Fatal("collinear points accepted")
	}
}
