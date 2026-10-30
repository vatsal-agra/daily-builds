// Package scan finds and decodes QR codes in raster images: adaptive
// binarisation, finder-pattern detection, projective (homography) grid
// estimation with alignment-pattern refinement, and module sampling.
package scan

import (
	"errors"
	"math"
)

// Pt is a point in image (or module) coordinates.
type Pt struct{ X, Y float64 }

func (a Pt) Sub(b Pt) Pt      { return Pt{a.X - b.X, a.Y - b.Y} }
func (a Pt) Add(b Pt) Pt      { return Pt{a.X + b.X, a.Y + b.Y} }
func (a Pt) Mul(k float64) Pt { return Pt{a.X * k, a.Y * k} }
func (a Pt) Len() float64     { return math.Hypot(a.X, a.Y) }
func cross(a, b Pt) float64   { return a.X*b.Y - a.Y*b.X }
func dot(a, b Pt) float64     { return a.X*b.X + a.Y*b.Y }

// Homography is a 3x3 projective map with h[8] == 1.
type Homography [9]float64

// Apply maps (u,v) to image coordinates.
func (h *Homography) Apply(u, v float64) Pt {
	w := h[6]*u + h[7]*v + h[8]
	return Pt{(h[0]*u + h[1]*v + h[2]) / w, (h[3]*u + h[4]*v + h[5]) / w}
}

// Inverse returns the inverse projective map.
func (h *Homography) Inverse() (Homography, error) {
	a, b, c, d, e, f, g, hh, i := h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], h[8]
	det := a*(e*i-f*hh) - b*(d*i-f*g) + c*(d*hh-e*g)
	if math.Abs(det) < 1e-18 {
		return Homography{}, errors.New("scan: singular homography")
	}
	inv := Homography{
		(e*i - f*hh) / det, (c*hh - b*i) / det, (b*f - c*e) / det,
		(f*g - d*i) / det, (a*i - c*g) / det, (c*d - a*f) / det,
		(d*hh - e*g) / det, (b*g - a*hh) / det, (a*e - b*d) / det,
	}
	s := inv[8]
	if s == 0 {
		return Homography{}, errors.New("scan: degenerate inverse")
	}
	for k := range inv {
		inv[k] /= s
	}
	return inv, nil
}

// FitHomography solves the least-squares projective map from src to dst
// (n >= 4 correspondences) via the normal equations with partial pivoting.
func FitHomography(src, dst []Pt) (Homography, error) {
	if len(src) != len(dst) || len(src) < 4 {
		return Homography{}, errors.New("scan: need at least 4 point pairs")
	}
	// Normalise coordinates for conditioning.
	sc, sS := normaliser(src)
	dc, dS := normaliser(dst)
	var ata [8][9]float64
	add := func(row [8]float64, rhs float64) {
		for i := 0; i < 8; i++ {
			for j := 0; j < 8; j++ {
				ata[i][j] += row[i] * row[j]
			}
			ata[i][8] += row[i] * rhs
		}
	}
	for k := range src {
		u, v := (src[k].X-sc.X)*sS, (src[k].Y-sc.Y)*sS
		x, y := (dst[k].X-dc.X)*dS, (dst[k].Y-dc.Y)*dS
		add([8]float64{u, v, 1, 0, 0, 0, -u * x, -v * x}, x)
		add([8]float64{0, 0, 0, u, v, 1, -u * y, -v * y}, y)
	}
	// Gaussian elimination.
	for c := 0; c < 8; c++ {
		p := c
		for r := c + 1; r < 8; r++ {
			if math.Abs(ata[r][c]) > math.Abs(ata[p][c]) {
				p = r
			}
		}
		if math.Abs(ata[p][c]) < 1e-12 {
			return Homography{}, errors.New("scan: degenerate point configuration")
		}
		ata[c], ata[p] = ata[p], ata[c]
		for r := 0; r < 8; r++ {
			if r == c {
				continue
			}
			f := ata[r][c] / ata[c][c]
			for k := c; k < 9; k++ {
				ata[r][k] -= f * ata[c][k]
			}
		}
	}
	var hn Homography
	for i := 0; i < 8; i++ {
		hn[i] = ata[i][8] / ata[i][i]
	}
	hn[8] = 1
	// Undo normalisation: H = Td^-1 * Hn * Ts.
	ts := Homography{sS, 0, -sc.X * sS, 0, sS, -sc.Y * sS, 0, 0, 1}
	tdInv := Homography{1 / dS, 0, dc.X, 0, 1 / dS, dc.Y, 0, 0, 1}
	h := mul3(tdInv, mul3(hn, ts))
	s := h[8]
	if s == 0 {
		return Homography{}, errors.New("scan: degenerate fit")
	}
	for k := range h {
		h[k] /= s
	}
	return h, nil
}

func normaliser(p []Pt) (Pt, float64) {
	var c Pt
	for _, q := range p {
		c = c.Add(q)
	}
	c = c.Mul(1 / float64(len(p)))
	var d float64
	for _, q := range p {
		d += q.Sub(c).Len()
	}
	d /= float64(len(p))
	if d < 1e-9 {
		d = 1
	}
	return c, math.Sqrt2 / d
}

func mul3(a, b Homography) Homography {
	var o Homography
	for i := 0; i < 3; i++ {
		for j := 0; j < 3; j++ {
			for k := 0; k < 3; k++ {
				o[i*3+j] += a[i*3+k] * b[k*3+j]
			}
		}
	}
	return o
}
