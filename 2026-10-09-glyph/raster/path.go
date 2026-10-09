// Package raster turns glyph outlines into anti-aliased coverage bitmaps.
package raster

import (
	"math"

	"glyph/ttf"
)

// Pt is a point in pixel space (y grows downward).
type Pt struct{ X, Y float64 }

// Path is a set of closed polylines.
type Path [][]Pt

// Affine maps x' = A*x + C*y + E, y' = B*x + D*y + F.
type Affine struct{ A, B, C, D, E, F float64 }

// Scale returns the font-unit → pixel transform for the given pixel size:
// y is flipped (fonts are y-up) and the origin sits at (ox, oy) on the baseline.
// slant > 0 shears the glyph to the right (synthetic oblique).
func Scale(pxPerUnit, ox, oy, slant float64) Affine {
	return Affine{A: pxPerUnit, B: 0, C: pxPerUnit * slant, D: -pxPerUnit, E: ox, F: oy}
}

func (m Affine) apply(x, y float64) Pt {
	return Pt{m.A*x + m.C*y + m.E, m.B*x + m.D*y + m.F}
}

// DefaultTolerance is the maximum curve-flattening error in pixels.
const DefaultTolerance = 0.02

// Flatten converts an outline to polylines, subdividing each quadratic Bézier
// so the chord error stays under tol pixels. Implied on-curve points between
// consecutive off-curve points are inserted per the TrueType rules.
func Flatten(o ttf.Outline, m Affine, tol float64) Path {
	if tol <= 0 {
		tol = DefaultTolerance
	}
	var out Path
	for _, c := range o.Contours {
		if len(c) < 2 {
			continue
		}
		pts := make([]Pt, len(c))
		on := make([]bool, len(c))
		for i, p := range c {
			pts[i], on[i] = m.apply(p.X, p.Y), p.On
		}
		// choose a start that is on-curve (real or implied)
		var start Pt
		first := 0
		switch {
		case on[0]:
			start, first = pts[0], 1
		case on[len(c)-1]:
			start = pts[len(c)-1]
			pts, on = pts[:len(c)-1], on[:len(c)-1]
		default:
			start = Pt{(pts[0].X + pts[len(c)-1].X) / 2, (pts[0].Y + pts[len(c)-1].Y) / 2}
		}
		poly := []Pt{start}
		cur := start
		var ctrl Pt
		haveCtrl := false
		emitQuad := func(p0, p1, p2 Pt) {
			dx, dy := p0.X-2*p1.X+p2.X, p0.Y-2*p1.Y+p2.Y
			n := int(math.Ceil(math.Sqrt(math.Hypot(dx, dy) / (4 * tol))))
			n = max(1, min(n, 256))
			for i := 1; i <= n; i++ {
				t := float64(i) / float64(n)
				u := 1 - t
				poly = append(poly, Pt{u*u*p0.X + 2*u*t*p1.X + t*t*p2.X, u*u*p0.Y + 2*u*t*p1.Y + t*t*p2.Y})
			}
		}
		for i := first; i < len(pts); i++ {
			p := pts[i]
			switch {
			case on[i] && !haveCtrl:
				poly = append(poly, p)
				cur = p
			case on[i]:
				emitQuad(cur, ctrl, p)
				cur, haveCtrl = p, false
			case haveCtrl:
				mid := Pt{(ctrl.X + p.X) / 2, (ctrl.Y + p.Y) / 2}
				emitQuad(cur, ctrl, mid)
				cur, ctrl = mid, p
			default:
				ctrl, haveCtrl = p, true
			}
		}
		if haveCtrl {
			emitQuad(cur, ctrl, start)
		}
		out = append(out, poly)
	}
	return out
}

// Area returns the total signed shoelace area (sum over contours), in px².
func (p Path) Area() float64 {
	a := 0.0
	for _, poly := range p {
		for i := range poly {
			j := (i + 1) % len(poly)
			a += poly[i].X*poly[j].Y - poly[j].X*poly[i].Y
		}
	}
	return a / 2
}

// Bounds returns the polyline bounding box; ok=false for an empty path.
func (p Path) Bounds() (x0, y0, x1, y1 float64, ok bool) {
	for _, poly := range p {
		for _, q := range poly {
			if !ok {
				x0, y0, x1, y1, ok = q.X, q.Y, q.X, q.Y, true
				continue
			}
			x0, x1 = math.Min(x0, q.X), math.Max(x1, q.X)
			y0, y1 = math.Min(y0, q.Y), math.Max(y1, q.Y)
		}
	}
	return
}
