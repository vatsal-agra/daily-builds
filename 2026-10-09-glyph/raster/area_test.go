package raster_test

import (
	"math"
	"os"
	"path/filepath"
	"testing"

	"glyph/raster"
	"glyph/ttf"
)

func fonts(t testing.TB) []string {
	m, _ := filepath.Glob("../testdata/fonts/*.ttf")
	if len(m) == 0 {
		t.Skip("no bundled fonts")
	}
	return m
}

// windingAt is an independent reference: the non-zero winding number of a point
// computed by ray casting against the flattened polylines.
func windingAt(p raster.Path, x, y float64) int {
	w := 0
	for _, poly := range p {
		for i := range poly {
			a, b := poly[i], poly[(i+1)%len(poly)]
			if (a.Y <= y) != (b.Y <= y) {
				t := (y - a.Y) / (b.Y - a.Y)
				if a.X+t*(b.X-a.X) > x {
					if b.Y > a.Y {
						w++
					} else {
						w--
					}
				}
			}
		}
	}
	return w
}

// Property: rendered coverage integrates to the non-zero-winding area measured
// by brute-force point sampling (a different algorithm than the scanline filler),
// across glyphs of every bundled font — including glyphs with overlapping contours.
func TestCoverageMatchesBruteForceArea(t *testing.T) {
	for _, p := range fonts(t) {
		b, _ := os.ReadFile(p)
		f, err := ttf.Parse(b)
		if err != nil {
			t.Fatal(err)
		}
		checked := 0
		for gid := 1; gid < f.NumGlyphs; gid += 31 {
			o, _ := f.Glyph(uint16(gid))
			if len(o.Contours) == 0 {
				continue
			}
			path := raster.Flatten(o, raster.Scale(40/float64(f.UnitsPerEm), 3.3, 50.7, 0), 0)
			bm := raster.Render(path, 64)
			x0, y0, x1, y1, _ := path.Bounds()
			const n = 10
			in := 0
			for yy := math.Floor(y0); yy < y1; yy += 1.0 / n {
				for xx := math.Floor(x0); xx < x1; xx += 1.0 / n {
					if windingAt(path, xx+0.5/n, yy+0.5/n) != 0 {
						in++
					}
				}
			}
			want := float64(in) / (n * n)
			if d := math.Abs(bm.Sum() - want); d > 0.025*want+0.8 {
				t.Errorf("%s glyph %d: coverage %.3f vs brute force %.3f", filepath.Base(p), gid, bm.Sum(), want)
			}
			checked++
		}
		if checked < 12 {
			t.Errorf("%s: only %d glyphs checked", p, checked)
		}
	}
}
