package raster_test

import (
	"math"
	"testing"

	"glyph/raster"
	"glyph/ttf"
)

func rect(x0, y0, x1, y1 float64) []raster.Pt {
	return []raster.Pt{{X: x0, Y: y0}, {X: x1, Y: y0}, {X: x1, Y: y1}, {X: x0, Y: y1}} // clockwise on screen
}
func rectCCW(x0, y0, x1, y1 float64) []raster.Pt {
	return []raster.Pt{{X: x0, Y: y0}, {X: x0, Y: y1}, {X: x1, Y: y1}, {X: x1, Y: y0}}
}

func near(a, b, tol float64) bool { return math.Abs(a-b) <= tol }

func TestAxisAlignedBoxCoverageIsExact(t *testing.T) {
	// A box from x=2.25..6.75, y=1..3 (rows aligned): horizontal coverage is exact, vertical rows are whole.
	bm := raster.Fill(raster.Path{rect(2.25, 1, 6.75, 3)}, 10, 5, 32)
	want := map[int]float32{1: 0, 2: 0.75, 3: 1, 4: 1, 5: 1, 6: 0.75, 7: 0}
	for x, w := range want {
		for _, y := range []int{1, 2} {
			if got := bm.At(x, y); math.Abs(float64(got-w)) > 1e-5 {
				t.Errorf("pixel (%d,%d) = %v, want %v", x, y, got, w)
			}
		}
	}
	if bm.At(4, 0) != 0 || bm.At(4, 3) != 0 {
		t.Error("coverage leaked outside the box rows")
	}
	if !near(bm.Sum(), 4.5*2, 1e-4) {
		t.Errorf("area %v != 9", bm.Sum())
	}
}

func TestFractionalVerticalEdges(t *testing.T) {
	// top edge at y=1.5 → row 1 half covered (to the resolution of 32 sub-scanlines)
	bm := raster.Fill(raster.Path{rect(1, 1.5, 4, 3)}, 6, 5, 32)
	if got := bm.At(2, 1); !near(float64(got), 0.5, 1.0/32) {
		t.Errorf("half-covered row = %v", got)
	}
	if !near(bm.Sum(), 3*1.5, 0.05) {
		t.Errorf("area %v != 4.5", bm.Sum())
	}
	// 1/64 px offset must change the answer by a sub-scanline's worth at most
	bm2 := raster.Fill(raster.Path{rect(1, 1.5+1.0/64, 4, 3)}, 6, 5, 32)
	if math.Abs(float64(bm.At(2, 1)-bm2.At(2, 1))) > 1.0/32+1e-6 {
		t.Error("coverage not continuous in y")
	}
}

func TestWindingRules(t *testing.T) {
	// two overlapping same-direction squares → union (non-zero), not xor
	same := raster.Path{rect(1, 1, 5, 5), rect(3, 3, 7, 7)}
	if a := raster.Fill(same, 9, 9, 16).Sum(); !near(a, 16+16-4, 1e-3) {
		t.Errorf("same-direction overlap area %v, want 28", a)
	}
	// opposite direction inner square → hole
	hole := raster.Path{rect(1, 1, 7, 7), rectCCW(3, 3, 5, 5)}
	bm := raster.Fill(hole, 9, 9, 16)
	if !near(bm.Sum(), 36-4, 1e-3) || bm.At(4, 4) != 0 || bm.At(2, 2) != 1 {
		t.Errorf("hole area %v centre %v", bm.Sum(), bm.At(4, 4))
	}
	// same-direction inner square must NOT make a hole (winding 2 stays filled)
	filled := raster.Path{rect(1, 1, 7, 7), rect(3, 3, 5, 5)}
	if a := raster.Fill(filled, 9, 9, 16).Sum(); !near(a, 36, 1e-3) {
		t.Errorf("nested same-direction area %v, want 36", a)
	}
	// opposite-direction overlapping squares: overlap region has winding 0 → removed
	cancel := raster.Path{rect(1, 1, 5, 5), rectCCW(3, 3, 7, 7)}
	if a := raster.Fill(cancel, 9, 9, 16).Sum(); !near(a, 16+16-8, 1e-3) {
		t.Errorf("opposite overlap area %v, want 24", a)
	}
}

func TestClippingAndDegenerate(t *testing.T) {
	// shape larger than the bitmap on every side: fully covered, no panic
	bm := raster.Fill(raster.Path{rect(-100, -100, 100, 100)}, 6, 4, 8)
	if !near(bm.Sum(), 24, 1e-4) {
		t.Errorf("clipped full cover = %v", bm.Sum())
	}
	// partially outside left/top
	bm = raster.Fill(raster.Path{rect(-3, -2, 2, 1)}, 6, 4, 8)
	if !near(bm.Sum(), 2*1, 1e-4) {
		t.Errorf("partial clip = %v", bm.Sum())
	}
	// degenerate inputs
	for name, p := range map[string]raster.Path{
		"empty":       nil,
		"point":       {{{X: 1, Y: 1}}},
		"line":        {{{X: 1, Y: 1}, {X: 5, Y: 5}}},
		"zero-height": {rect(1, 2, 5, 2)},
		"nan":         {{{X: math.NaN(), Y: 1}, {X: 3, Y: 1}, {X: 3, Y: 3}}},
		"inf":         {{{X: math.Inf(1), Y: 1}, {X: 3, Y: 1}, {X: 3, Y: 3}}},
	} {
		if s := raster.Fill(p, 8, 8, 8).Sum(); s != 0 && name != "nan" && name != "inf" {
			t.Errorf("%s: coverage %v, want 0", name, s)
		}
	}
	if bm := raster.Fill(raster.Path{rect(0, 0, 1, 1)}, 0, 0, 8); bm.W != 0 || len(bm.Pix) != 0 {
		t.Error("zero-size bitmap")
	}
}

func TestSlantedEdgeAreaAndMonotonicity(t *testing.T) {
	tri := raster.Path{{{X: 0.5, Y: 0.5}, {X: 9.5, Y: 2.25}, {X: 3.5, Y: 8.5}}}
	want := math.Abs(tri.Area())
	if got := raster.Fill(tri, 12, 12, 64).Sum(); !near(got, want, 0.02) {
		t.Errorf("triangle coverage %v vs shoelace %v", got, want)
	}
	// translating by whole pixels must translate coverage exactly
	a := raster.Fill(tri, 12, 12, 32)
	shifted := raster.Path{{{X: 2.5, Y: 1.5}, {X: 11.5, Y: 3.25}, {X: 5.5, Y: 9.5}}}
	b := raster.Fill(shifted, 14, 14, 32)
	for y := 0; y < 12; y++ {
		for x := 0; x < 12; x++ {
			if math.Abs(float64(a.At(x, y)-b.At(x+2, y+1))) > 1e-5 {
				t.Fatalf("not translation invariant at (%d,%d)", x, y)
			}
		}
	}
	for _, v := range a.Pix {
		if v < 0 || v > 1 {
			t.Fatalf("coverage %v outside [0,1]", v)
		}
	}
}

func TestMoreSamplesConverge(t *testing.T) {
	path := raster.Flatten(ttfCircle(100), raster.Affine{A: 0.05, D: -0.05, E: 12, F: 12}, 0.005)
	want := math.Abs(path.Area()) // exact area of the flattened polygon
	bound := map[int]float64{2: 1.5, 8: 0.5, 32: 0.15, 128: 0.1}
	for _, s := range []int{2, 8, 32, 128} {
		if err := math.Abs(raster.Render(path, s).Sum() - want); err > bound[s] {
			t.Errorf("%d samples: area error %.4f px² exceeds %.2f", s, err, bound[s])
		}
	}
}

// ttfCircle approximates a circle of radius r with 8 quadratic segments (off-curve at the tangent corners).
func ttfCircle(r float64) ttf.Outline {
	k := r * math.Tan(math.Pi/8)
	var c ttf.Contour
	for i := 0; i < 8; i++ {
		a0 := float64(i) * math.Pi / 4
		a1 := a0 + math.Pi/4
		c = append(c, ttf.Point{X: r * math.Cos(a0), Y: r * math.Sin(a0), On: true})
		// control point = intersection of tangents
		cx := r*math.Cos(a0) - k*math.Sin(a0)
		cy := r*math.Sin(a0) + k*math.Cos(a0)
		_ = a1
		c = append(c, ttf.Point{X: cx, Y: cy})
	}
	return ttf.Outline{Contours: []ttf.Contour{c}}
}

func segDist(p, a, b raster.Pt) float64 {
	dx, dy := b.X-a.X, b.Y-a.Y
	t := 0.0
	if l := dx*dx + dy*dy; l > 0 {
		t = math.Max(0, math.Min(1, ((p.X-a.X)*dx+(p.Y-a.Y)*dy)/l))
	}
	return math.Hypot(p.X-(a.X+t*dx), p.Y-(a.Y+t*dy))
}

// The flattened polyline must stay within `tol` of the TRUE quadratic curves
// (Hausdorff distance, measured by dense sampling of the exact Bézier).
func TestFlattenTolerance(t *testing.T) {
	o := ttfCircle(400)
	c := o.Contours[0]
	var counts []int
	for _, tol := range []float64{0.5, 0.1, 0.02} {
		poly := raster.Flatten(o, raster.Affine{A: 1, D: 1}, tol)[0]
		worst := 0.0
		for i := 0; i < len(c); i += 2 { // on, off, on, off … (closed)
			p0, p1, p2 := c[i], c[i+1], c[(i+2)%len(c)]
			for k := 0; k <= 200; k++ {
				u := float64(k) / 200
				pt := raster.Pt{
					X: (1-u)*(1-u)*p0.X + 2*(1-u)*u*p1.X + u*u*p2.X,
					Y: (1-u)*(1-u)*p0.Y + 2*(1-u)*u*p1.Y + u*u*p2.Y,
				}
				best := math.Inf(1)
				for j := range poly {
					best = math.Min(best, segDist(pt, poly[j], poly[(j+1)%len(poly)]))
				}
				worst = math.Max(worst, best)
			}
		}
		if worst > tol*1.05 {
			t.Errorf("tol %v: polyline strays %.4f from the curve", tol, worst)
		}
		t.Logf("tol %.2f → %d vertices, max deviation %.4f", tol, len(poly), worst)
		counts = append(counts, len(poly))
	}
	if !(counts[0] < counts[1] && counts[1] < counts[2]) {
		t.Errorf("vertex counts should grow as tolerance shrinks: %v", counts)
	}
}

func TestFlattenImpliedOnCurvePoints(t *testing.T) {
	// all-off-curve contour (a "circle" from 4 control points) starts at an implied midpoint and closes
	o := ttf.Outline{Contours: []ttf.Contour{{{X: 0, Y: 0}, {X: 100, Y: 0}, {X: 100, Y: 100}, {X: 0, Y: 100}}}}
	poly := raster.Flatten(o, raster.Affine{A: 1, D: 1}, 0.05)[0]
	if poly[0] != (raster.Pt{X: 0, Y: 50}) {
		t.Errorf("implied start = %v, want (0,50)", poly[0])
	}
	x0, y0, x1, y1, _ := raster.Path{poly}.Bounds()
	if x0 < -0.01 || y0 < -0.01 || x1 > 100.01 || y1 > 100.01 || x1 < 40 {
		t.Errorf("bounds %v %v %v %v", x0, y0, x1, y1)
	}
	// a contour starting off-curve but ending on-curve begins at that last point
	o = ttf.Outline{Contours: []ttf.Contour{{{X: 50, Y: 100}, {X: 0, Y: 0, On: true}, {X: 100, Y: 0, On: true}}}}
	poly = raster.Flatten(o, raster.Affine{A: 1, D: 1}, 0.05)[0]
	if poly[0] != (raster.Pt{X: 100, Y: 0}) {
		t.Errorf("start = %v, want last on-curve point", poly[0])
	}
	// 1-point contours are ignored
	if len(raster.Flatten(ttf.Outline{Contours: []ttf.Contour{{{X: 1, Y: 1, On: true}}}}, raster.Affine{A: 1, D: 1}, 0)) != 0 {
		t.Error("single-point contour should be dropped")
	}
}

func TestScaleMatrix(t *testing.T) {
	m := raster.Scale(0.5, 10, 20, 0.25)
	o := ttf.Outline{Contours: []ttf.Contour{{{X: 100, Y: 200, On: true}, {X: 0, Y: 0, On: true}}}}
	p := raster.Flatten(o, m, 0)[0]
	// x' = 0.5*100 + 0.5*0.25*200 + 10 = 85 ; y' = -0.5*200 + 20 = -80
	if !near(p[0].X, 85, 1e-9) || !near(p[0].Y, -80, 1e-9) {
		t.Errorf("transform gave %v", p[0])
	}
}

func TestSignedDistanceSquare(t *testing.T) {
	sdf := raster.SignedDistance(raster.Path{rect(4, 4, 12, 12)}, 4)
	at := func(x, y int) float64 { return float64(sdf.Dist[(y-sdf.Y0)*sdf.W+(x-sdf.X0)]) }
	// pixel (8,8) centre (8.5,8.5): nearest edge x=12 → 3.5 inside; nearest of left edge is 4.5
	if !near(at(8, 8), 3.5, 1e-9) {
		t.Errorf("centre distance %v", at(8, 8))
	}
	if !near(at(2, 8), -1.5, 1e-9) { // centre x=2.5, edge at 4 → 1.5 outside
		t.Errorf("outside distance %v", at(2, 8))
	}
	if !near(at(14, 14), -math.Hypot(2.5, 2.5), 1e-9) { // corner distance
		t.Errorf("corner distance %v", at(14, 14))
	}
	if at(5, 5) <= 0 || at(1, 1) >= 0 {
		t.Error("sign wrong")
	}
}

func TestLCDMatchesGrayAreaAndShowsFringes(t *testing.T) {
	path := raster.Path{rect(3.4, 2, 9.7, 8)}
	gray := raster.Render(path, 32)
	lcd := raster.RenderLCD(path, 32)
	if !near(lcd.Sum(), gray.Sum(), 0.2) {
		t.Errorf("LCD area %v vs gray %v", lcd.Sum(), gray.Sum())
	}
	// interior pixels are fully covered in all channels
	mid := func(x, y, k int) float32 { return lcd.Pix[3*((y-lcd.Y0)*lcd.W+(x-lcd.X0))+k] }
	for k := 0; k < 3; k++ {
		if mid(6, 5, k) < 0.999 {
			t.Errorf("interior channel %d = %v", k, mid(6, 5, k))
		}
	}
	// at the left edge (x=3.4) the three stripes must differ: R (leftmost) < G < B
	r, g, b := mid(3, 5, 0), mid(3, 5, 1), mid(3, 5, 2)
	if !(r < g && g < b) {
		t.Errorf("left-edge stripes not ordered: %v %v %v", r, g, b)
	}
	if lcd.W == 0 || lcd.X0 > 2 {
		t.Error("LCD bitmap lost its margin")
	}
}

func lcdSub(b *raster.LCDBitmap, sub int) float64 { // coverage of absolute sub-pixel index (3*px + channel)
	px, k := sub/3, sub%3
	if sub < 0 {
		px, k = (sub-2)/3, ((sub%3)+3)%3
	}
	x, y := px-b.X0, 5-b.Y0
	if x < 0 || x >= b.W || y < 0 || y >= b.H {
		return 0
	}
	return float64(b.Pix[3*(y*b.W+x)+k])
}

// A one-sub-pixel-wide sliver is an impulse: the output must be exactly the FIR taps.
func TestLCDFilterImpulseResponse(t *testing.T) {
	lcd := raster.RenderLCD(raster.Path{rect(3, 2, 3+1.0/3, 9)}, 32) // exactly sub-pixel 9 (px 3, channel R)
	want := map[int]float64{7: 8.0 / 256, 8: 77.0 / 256, 9: 86.0 / 256, 10: 77.0 / 256, 11: 8.0 / 256}
	for sub := 3; sub < 18; sub++ {
		if got := lcdSub(lcd, sub); !near(got, want[sub], 1e-4) {
			t.Errorf("sub-pixel %d = %.4f, want %.4f", sub, got, want[sub])
		}
	}
}

// Mirroring the shape must mirror the LCD result, with R and B swapping places.
func TestLCDMirrorSymmetry(t *testing.T) {
	const c = 16 // mirror axis at x = 8 → x' = 16 - x
	a := raster.RenderLCD(raster.Path{rect(3.4, 2, 9.7, 8)}, 32)
	b := raster.RenderLCD(raster.Path{rectCCW(c-9.7, 2, c-3.4, 8)}, 32)
	for sub := 0; sub < 3*c; sub++ {
		if x, y := lcdSub(a, sub), lcdSub(b, 3*c-1-sub); !near(x, y, 1e-4) {
			t.Fatalf("sub-pixel %d: %.4f vs mirrored %.4f", sub, x, y)
		}
	}
}
