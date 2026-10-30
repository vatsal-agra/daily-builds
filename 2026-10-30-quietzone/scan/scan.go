package scan

import (
	"errors"
	"fmt"
	"image"
	"math"
	"sort"

	"quietzone/qr"
)

// Detection is one decoded symbol found in an image.
type Detection struct {
	Result   *qr.Result
	Matrix   *qr.Matrix
	Corners  [4]Pt // outer corners TL, TR, BR, BL in image pixels
	Strategy string
	Module   float64 // estimated module size in pixels
	Aligns   int     // alignment patterns used to refine the grid
}

// Options tunes Scan.
type Options struct {
	MaxCodes   int        // stop after this many symbols (0 = all)
	Strategies []Strategy // nil = defaults
	Debug      func(string)
}

// ErrNotFound is returned when no QR symbol could be decoded.
var ErrNotFound = errors.New("scan: no QR code found")

// Scan finds and decodes every QR symbol it can in img.
func Scan(img image.Image, opt Options) ([]Detection, error) {
	g := FromImage(img)
	if g.W < 21 || g.H < 21 {
		return nil, errors.New("scan: image too small")
	}
	strats := opt.Strategies
	if strats == nil {
		strats = Strategies()
	}
	var found []Detection
	dup := func(d Detection) bool {
		for _, f := range found {
			c1, c2 := centre(f.Corners), centre(d.Corners)
			if c1.Sub(c2).Len() < f.Module*float64(f.Matrix.N)*0.35 {
				return true
			}
		}
		return false
	}
	for _, st := range strats {
		bin := g.Binarize(st)
		fs := FindFinders(bin)
		if opt.Debug != nil {
			opt.Debug(fmt.Sprintf("%s: %d finder candidates", st.Name+map[bool]string{true: "/inv"}[st.Inverted], len(fs)))
		}
		if len(fs) < 3 {
			continue
		}
		for i := range fs {
			fs[i].Module = CoreModule(bin, fs[i].C, fs[i].Module)
		}
		used := map[int]bool{}
		for _, tr := range rankTriples(fs) {
			if used[tr.a] || used[tr.b] || used[tr.c] {
				continue
			}
			d, err := decodeTriple(bin, fs[tr.a], fs[tr.b], fs[tr.c])
			if err != nil {
				continue
			}
			d.Strategy = st.Name
			if st.Inverted {
				d.Strategy += "/inverted"
			}
			if dup(d) {
				used[tr.a], used[tr.b], used[tr.c] = true, true, true
				continue
			}
			found = append(found, d)
			used[tr.a], used[tr.b], used[tr.c] = true, true, true
			if opt.MaxCodes > 0 && len(found) >= opt.MaxCodes {
				return found, nil
			}
		}
		// If every finder is accounted for by decoded symbols there is nothing
		// left for the remaining strategies to find.
		if len(found) > 0 && len(fs)-len(used) < 3 {
			break
		}
	}
	if len(found) == 0 {
		return nil, ErrNotFound
	}
	sort.SliceStable(found, func(i, j int) bool {
		a, b := centre(found[i].Corners), centre(found[j].Corners)
		if math.Abs(a.Y-b.Y) > 1 {
			return a.Y < b.Y
		}
		return a.X < b.X
	})
	return found, nil
}

func centre(c [4]Pt) Pt { return c[0].Add(c[1]).Add(c[2]).Add(c[3]).Mul(0.25) }

type triple struct {
	a, b, c int
	score   float64
}

// rankTriples orders all plausible finder triples (right-angled, near-isosceles,
// consistent module size) from most to least convincing.
func rankTriples(fs []Finder) []triple {
	n := min(len(fs), 14)
	var out []triple
	for i := 0; i < n; i++ {
		for j := i + 1; j < n; j++ {
			for k := j + 1; k < n; k++ {
				idx := [3]int{i, j, k}
				best := triple{score: math.Inf(1)}
				for v := 0; v < 3; v++ {
					o := fs[idx[v]]
					p, q := fs[idx[(v+1)%3]], fs[idx[(v+2)%3]]
					a, b := p.C.Sub(o.C), q.C.Sub(o.C)
					la, lb := a.Len(), b.Len()
					if la < 1 || lb < 1 {
						continue
					}
					cos := math.Abs(dot(a, b) / (la * lb))
					ratio := math.Min(la, lb) / math.Max(la, lb)
					ms := (o.Module + p.Module + q.Module) / 3
					msVar := math.Max(math.Max(o.Module, p.Module), q.Module) / math.Min(math.Min(o.Module, p.Module), q.Module)
					dim := (la+lb)/2/ms + 7
					if cos > 0.5 || ratio < 0.6 || msVar > 1.8 || dim < 19 || dim > 185 {
						continue
					}
					sc := cos*2 + (1 - ratio)*2 + (msVar - 1)
					if sc < best.score {
						best = triple{idx[v], idx[(v+1)%3], idx[(v+2)%3], sc}
					}
				}
				if !math.IsInf(best.score, 1) {
					out = append(out, best)
				}
			}
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].score < out[j].score })
	return out
}

// decodeTriple tries to read a symbol whose top-left finder is f0.
func decodeTriple(b *Bin, f0, f1, f2 Finder) (Detection, error) {
	tl, tr, bl := f0, f1, f2
	if cross(tr.C.Sub(tl.C), bl.C.Sub(tl.C)) < 0 {
		tr, bl = bl, tr
	}
	ms := (tl.Module + tr.Module + bl.Module) / 3
	side := (tr.C.Sub(tl.C).Len() + bl.C.Sub(tl.C).Len()) / 2
	est := side/ms + 7
	ver0 := int(math.Round((est - 17) / 4))
	var versions []int
	for _, d := range []int{0, -1, 1, -2, 2} {
		v := ver0 + d
		if v >= 1 && v <= 40 {
			versions = append(versions, v)
		}
	}
	var lastErr error = errors.New("scan: no candidate version")
	for _, v := range versions {
		d, err := tryVersion(b, tl, tr, bl, ms, v)
		if err == nil {
			return d, nil
		}
		lastErr = err
	}
	return Detection{}, lastErr
}

func tryVersion(b *Bin, tl, tr, bl Finder, ms float64, version int) (Detection, error) {
	n := float64(qr.Size(version))
	src := []Pt{{3.5, 3.5}, {n - 3.5, 3.5}, {3.5, n - 3.5}}
	dst := []Pt{tl.C, tr.C, bl.C}
	h, err := affine3(src, dst)
	if err != nil {
		return Detection{}, err
	}
	aligns := 0
	if version >= 2 {
		ap := alignCentres(version)
		pts, imgs := append([]Pt(nil), src...), append([]Pt(nil), dst...)
		cur := h
		for iter := 0; iter < 3; iter++ {
			radius := 2.4
			if iter > 0 {
				radius = 1.4
			}
			pts, imgs = append([]Pt(nil), src...), append([]Pt(nil), dst...)
			// Process nearest-to-finder first on iteration 0 so the grid grows outward.
			for _, a := range ap {
				if p, ok := findAlign(b, &cur, a, radius); ok {
					pts = append(pts, a)
					imgs = append(imgs, p)
				}
			}
			if len(pts) < 4 {
				break
			}
			nh, err := FitHomography(pts, imgs)
			if err != nil {
				break
			}
			cur = nh
			aligns = len(pts) - 3
		}
		h = cur
	}
	m := sampleMatrix(b, &h, qr.Size(version))
	res, err := qr.Decode(m)
	if err != nil {
		return Detection{}, err
	}
	N := float64(qr.Size(version))
	det := Detection{Result: res, Matrix: m, Module: ms, Aligns: aligns}
	det.Corners = [4]Pt{h.Apply(0, 0), h.Apply(N, 0), h.Apply(N, N), h.Apply(0, N)}
	return det, nil
}

// affine3 builds the exact affine map through three correspondences.
func affine3(src, dst []Pt) (Homography, error) {
	d1, d2 := src[1].Sub(src[0]), src[2].Sub(src[0])
	det := cross(d1, d2)
	if math.Abs(det) < 1e-9 {
		return Homography{}, errors.New("scan: collinear finders")
	}
	e1, e2 := dst[1].Sub(dst[0]), dst[2].Sub(dst[0])
	// Solve [a b; c d] * [d1 d2] = [e1 e2]
	a := (e1.X*d2.Y - e2.X*d1.Y) / det
	bb := (e2.X*d1.X - e1.X*d2.X) / det
	c := (e1.Y*d2.Y - e2.Y*d1.Y) / det
	d := (e2.Y*d1.X - e1.Y*d2.X) / det
	tx := dst[0].X - a*src[0].X - bb*src[0].Y
	ty := dst[0].Y - c*src[0].X - d*src[0].Y
	return Homography{a, bb, tx, c, d, ty, 0, 0, 1}, nil
}

// alignCentres lists alignment-pattern centres in module-corner coordinates.
func alignCentres(version int) []Pt {
	pos := qr.AlignPositions(version)
	var out []Pt
	for i, cy := range pos {
		for j, cx := range pos {
			if (i == 0 && j == 0) || (i == 0 && j == len(pos)-1) || (i == len(pos)-1 && j == 0) {
				continue
			}
			out = append(out, Pt{float64(cx) + 0.5, float64(cy) + 0.5})
		}
	}
	return out
}

// sampleModule votes over five points in the centre of module cell (u,v).
func sampleModule(b *Bin, h *Homography, u, v float64) bool {
	votes := 0
	for _, o := range [5][2]float64{{0, 0}, {-0.2, -0.2}, {0.2, -0.2}, {-0.2, 0.2}, {0.2, 0.2}} {
		p := h.Apply(u+o[0], v+o[1])
		if b.At(int(math.Floor(p.X)), int(math.Floor(p.Y))) {
			votes++
		}
	}
	return votes >= 3
}

// findAlign searches around the predicted position of the alignment pattern
// centred at module coordinates c for the best 5x5 bull's-eye match.
func findAlign(b *Bin, h *Homography, c Pt, radius float64) (Pt, bool) {
	score := func(a, bb float64) int {
		s := 0
		for j := -2; j <= 2; j++ {
			for i := -2; i <= 2; i++ {
				want := max(abs(i), abs(j)) != 1
				if sampleModule(b, h, c.X+a+float64(i), c.Y+bb+float64(j)) == want {
					s++
				}
			}
		}
		return s
	}
	best, ba, bb := -1, 0.0, 0.0
	bestD := math.Inf(1)
	try := func(a, b2 float64) {
		s := score(a, b2)
		d := math.Hypot(a, b2)
		if s > best || (s == best && d < bestD) {
			best, ba, bb, bestD = s, a, b2, d
		}
	}
	for a := -radius; a <= radius+1e-9; a += 0.25 {
		for b2 := -radius; b2 <= radius+1e-9; b2 += 0.25 {
			try(a, b2)
		}
	}
	// local polish
	ca, cb := ba, bb
	for a := ca - 0.2; a <= ca+0.2+1e-9; a += 0.1 {
		for b2 := cb - 0.2; b2 <= cb+0.2+1e-9; b2 += 0.1 {
			try(a, b2)
		}
	}
	if best < 22 {
		return Pt{}, false
	}
	// Weighted refinement: the true centre is the centroid of all offsets scoring within 1 of the best.
	var sa, sb, sw float64
	for a := ba - 0.4; a <= ba+0.4+1e-9; a += 0.1 {
		for b2 := bb - 0.4; b2 <= bb+0.4+1e-9; b2 += 0.1 {
			if score(a, b2) >= best-1 {
				sa += a
				sb += b2
				sw++
			}
		}
	}
	return h.Apply(c.X+sa/sw, c.Y+sb/sw), true
}

func sampleMatrix(b *Bin, h *Homography, n int) *qr.Matrix {
	m := qr.NewMatrix(n)
	for y := 0; y < n; y++ {
		for x := 0; x < n; x++ {
			m.Set(x, y, sampleModule(b, h, float64(x)+0.5, float64(y)+0.5))
		}
	}
	return m
}

func abs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}
