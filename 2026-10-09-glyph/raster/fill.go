package raster

import (
	"math"
	"sort"
)

// Bitmap is a coverage map in [0,1]. (X0,Y0) is the pixel position of Pix[0]
// relative to the glyph origin it was rendered for.
type Bitmap struct {
	W, H   int
	X0, Y0 int
	Pix    []float32
}

// Sum returns total coverage (≈ filled area in px²).
func (b *Bitmap) Sum() float64 {
	s := 0.0
	for _, v := range b.Pix {
		s += float64(v)
	}
	return s
}

// At returns coverage at pixel (x,y) of the bitmap, 0 outside.
func (b *Bitmap) At(x, y int) float32 {
	if x < 0 || y < 0 || x >= b.W || y >= b.H {
		return 0
	}
	return b.Pix[y*b.W+x]
}

// DefaultSamples is the number of sub-scanlines per pixel row.
const DefaultSamples = 32

type edge struct {
	x0, y0, x1, y1 float64
	dir            int8 // +1 if originally downward
}

type crossing struct {
	x   float64
	dir int8
}

// Fill rasterizes the path into a w×h bitmap using the non-zero winding rule.
// Vertical resolution is `samples` sub-scanlines per pixel; horizontal coverage
// of every span is computed exactly (fractional pixel ends), so vertical stems
// and slanted edges alike get smooth edges. Coordinates are bitmap-local.
func Fill(p Path, w, h, samples int) *Bitmap {
	if samples <= 0 {
		samples = DefaultSamples
	}
	bm := &Bitmap{W: w, H: h}
	if w <= 0 || h <= 0 {
		return bm
	}
	bm.Pix = make([]float32, w*h)
	rows := make([][]int, h) // edge indexes touching each pixel row
	var edges []edge
	for _, poly := range p {
		for i := range poly {
			a, b := poly[i], poly[(i+1)%len(poly)]
			if a.Y == b.Y || math.IsNaN(a.X+a.Y+b.X+b.Y) || math.IsInf(a.X+a.Y+b.X+b.Y, 0) {
				continue
			}
			e := edge{a.X, a.Y, b.X, b.Y, 1}
			if a.Y > b.Y {
				e = edge{b.X, b.Y, a.X, a.Y, -1}
			}
			if e.y1 <= 0 || e.y0 >= float64(h) {
				continue
			}
			idx := len(edges)
			edges = append(edges, e)
			r0 := max(0, int(math.Floor(e.y0)))
			r1 := min(h-1, int(math.Floor(e.y1)))
			for r := r0; r <= r1; r++ {
				rows[r] = append(rows[r], idx)
			}
		}
	}
	diff := make([]float64, w+1)
	acc := make([]float64, w+1)
	var xs []crossing
	wt := 1.0 / float64(samples)
	for row := 0; row < h; row++ {
		if len(rows[row]) == 0 {
			continue
		}
		for i := range acc {
			acc[i], diff[i] = 0, 0
		}
		for s := 0; s < samples; s++ {
			y := float64(row) + (float64(s)+0.5)*wt
			xs = xs[:0]
			for _, ei := range rows[row] {
				e := edges[ei]
				if y >= e.y0 && y < e.y1 {
					xs = append(xs, crossing{e.x0 + (y-e.y0)*(e.x1-e.x0)/(e.y1-e.y0), e.dir})
				}
			}
			if len(xs) < 2 {
				continue
			}
			sort.Slice(xs, func(i, j int) bool { return xs[i].x < xs[j].x })
			wind := 0
			var sx float64
			for _, c := range xs {
				was := wind != 0
				wind += int(c.dir)
				now := wind != 0
				if !was && now {
					sx = c.x
				} else if was && !now {
					addSpan(acc, diff, sx, c.x, w, wt)
				}
			}
		}
		run := 0.0
		line := bm.Pix[row*w : (row+1)*w]
		for x := 0; x < w; x++ {
			run += diff[x]
			v := acc[x] + run
			line[x] = float32(math.Min(1, math.Max(0, v)))
		}
	}
	return bm
}

// addSpan adds weight wt over [xa,xb) using exact fractional coverage at the
// ends and a difference array for the fully covered interior.
func addSpan(acc, diff []float64, xa, xb float64, w int, wt float64) {
	xa, xb = math.Max(xa, 0), math.Min(xb, float64(w))
	if xb <= xa {
		return
	}
	ia, ib := int(xa), int(xb)
	if ia == ib {
		acc[ia] += (xb - xa) * wt
		return
	}
	acc[ia] += (float64(ia+1) - xa) * wt
	diff[ia+1] += wt
	diff[ib] -= wt
	if ib < w {
		acc[ib] += (xb - float64(ib)) * wt
	}
}

// Render flattens and fills a glyph outline. The returned bitmap is tightly
// cropped; X0/Y0 give its top-left pixel offset from the glyph origin.
func Render(path Path, samples int) *Bitmap {
	x0, y0, x1, y1, ok := path.Bounds()
	if !ok {
		return &Bitmap{}
	}
	ix0, iy0 := int(math.Floor(x0))-1, int(math.Floor(y0))-1
	ix1, iy1 := int(math.Ceil(x1))+1, int(math.Ceil(y1))+1
	w, h := ix1-ix0, iy1-iy0
	shifted := make(Path, len(path))
	for i, poly := range path {
		sp := make([]Pt, len(poly))
		for j, q := range poly {
			sp[j] = Pt{q.X - float64(ix0), q.Y - float64(iy0)}
		}
		shifted[i] = sp
	}
	bm := Fill(shifted, w, h, samples)
	bm.X0, bm.Y0 = ix0, iy0
	return bm
}
