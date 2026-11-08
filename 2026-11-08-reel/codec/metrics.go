package codec

import (
	"errors"
	"math"
)

// PlaneMSE returns the mean squared error between visible areas of plane i.
func planeSSE(a, b *Frame, i int) (sse float64, n int) {
	pa, pb := a.planes()[i], b.planes()[i]
	w, h := a.visW(i), a.visH(i)
	for y := 0; y < h; y++ {
		ra := pa.Pix[pa.idx(0, y) : pa.idx(0, y)+w]
		rb := pb.Pix[pb.idx(0, y) : pb.idx(0, y)+w]
		for x := 0; x < w; x++ {
			d := float64(int(ra[x]) - int(rb[x]))
			sse += d * d
		}
	}
	return sse, w * h
}

// psnrFromSSE converts to dB, capping at 100 for identical planes.
func psnrFromSSE(sse float64, n int) float64 {
	if sse == 0 {
		return 100
	}
	return 10 * math.Log10(255*255*float64(n)/sse)
}

// PSNR returns per-plane PSNR of b against reference a.
func PSNR(a, b *Frame) (y, u, v float64) {
	s0, n0 := planeSSE(a, b, 0)
	s1, n1 := planeSSE(a, b, 1)
	s2, n2 := planeSSE(a, b, 2)
	return psnrFromSSE(s0, n0), psnrFromSSE(s1, n1), psnrFromSSE(s2, n2)
}

// CombinedPSNR is the usual (6Y+U+V)/8 weighting.
func CombinedPSNR(y, u, v float64) float64 { return (6*y + u + v) / 8 }

// SSIM computes mean structural similarity of the luma planes (8x8 windows, stride 4).
func SSIM(a, b *Frame) float64 {
	pa, pb := a.Y, b.Y
	w, h := a.Width, a.Height
	const c1, c2 = 6.5025, 58.5225
	var sum float64
	var cnt int
	for y := 0; y+8 <= h; y += 4 {
		for x := 0; x+8 <= w; x += 4 {
			var sa, sb, saa, sbb, sab float64
			for j := 0; j < 8; j++ {
				i0 := pa.idx(x, y+j)
				i1 := pb.idx(x, y+j)
				for i := 0; i < 8; i++ {
					va, vb := float64(pa.Pix[i0+i]), float64(pb.Pix[i1+i])
					sa += va
					sb += vb
					saa += va * va
					sbb += vb * vb
					sab += va * vb
				}
			}
			ma, mb := sa/64, sb/64
			va, vb, cov := saa/64-ma*ma, sbb/64-mb*mb, sab/64-ma*mb
			sum += ((2*ma*mb + c1) * (2*cov + c2)) / ((ma*ma + mb*mb + c1) * (va + vb + c2))
			cnt++
		}
	}
	if cnt == 0 {
		return 1
	}
	return sum / float64(cnt)
}

// SeqMetrics are whole-sequence quality numbers.
type SeqMetrics struct {
	PSNRY, PSNRU, PSNRV, PSNR float64
	SSIM                      float64
	Frames                    int
	Min                       float64 // worst-frame combined PSNR
}

// Compare computes mean metrics between two sequences of equal size.
func Compare(a, b *Video) (SeqMetrics, error) {
	var m SeqMetrics
	if a.Width != b.Width || a.Height != b.Height {
		return m, errors.New("psnr: size mismatch")
	}
	n := len(a.Frames)
	if len(b.Frames) < n {
		n = len(b.Frames)
	}
	if n == 0 {
		return m, errors.New("psnr: no frames")
	}
	m.Min = 1e9
	for i := 0; i < n; i++ {
		y, u, v := PSNR(a.Frames[i], b.Frames[i])
		m.PSNRY += y
		m.PSNRU += u
		m.PSNRV += v
		c := CombinedPSNR(y, u, v)
		if c < m.Min {
			m.Min = c
		}
		m.SSIM += SSIM(a.Frames[i], b.Frames[i])
	}
	f := float64(n)
	m.PSNRY /= f
	m.PSNRU /= f
	m.PSNRV /= f
	m.SSIM /= f
	m.PSNR = CombinedPSNR(m.PSNRY, m.PSNRU, m.PSNRV)
	m.Frames = n
	return m, nil
}

// RDPoint is one (bitrate, quality) sample of a rate-distortion curve.
type RDPoint struct{ Rate, PSNR float64 }

// polyFit fits a polynomial of the given degree by least squares.
func polyFit(xs, ys []float64, deg int) []float64 {
	n := deg + 1
	a := make([][]float64, n)
	for i := range a {
		a[i] = make([]float64, n+1)
	}
	for k := range xs {
		pw := make([]float64, 2*n)
		pw[0] = 1
		for i := 1; i < 2*n; i++ {
			pw[i] = pw[i-1] * xs[k]
		}
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				a[i][j] += pw[i+j]
			}
			a[i][n] += pw[i] * ys[k]
		}
	}
	for c := 0; c < n; c++ {
		p := c
		for r := c + 1; r < n; r++ {
			if math.Abs(a[r][c]) > math.Abs(a[p][c]) {
				p = r
			}
		}
		a[c], a[p] = a[p], a[c]
		if a[c][c] == 0 {
			continue
		}
		for r := 0; r < n; r++ {
			if r == c {
				continue
			}
			f := a[r][c] / a[c][c]
			for k := c; k <= n; k++ {
				a[r][k] -= f * a[c][k]
			}
		}
	}
	co := make([]float64, n)
	for i := range co {
		if a[i][i] != 0 {
			co[i] = a[i][n] / a[i][i]
		}
	}
	return co
}

func polyInt(co []float64, lo, hi float64) float64 {
	f := func(x float64) float64 {
		s, p := 0.0, x
		for i, c := range co {
			s += c * p / float64(i+1)
			p *= x
		}
		return s
	}
	return f(hi) - f(lo)
}

// BDRate is the Bjøntegaard delta-rate (%) of `test` relative to `anchor`:
// negative means test needs fewer bits at equal quality. Needs >= 4 points each.
func BDRate(anchor, test []RDPoint) (float64, error) {
	if len(anchor) < 4 || len(test) < 4 {
		return 0, errors.New("bdrate: need at least 4 points per curve")
	}
	curve := func(pts []RDPoint) (co []float64, lo, hi float64) {
		xs := make([]float64, len(pts))
		ys := make([]float64, len(pts))
		lo, hi = math.Inf(1), math.Inf(-1)
		for i, p := range pts {
			xs[i], ys[i] = p.PSNR, math.Log10(p.Rate)
			lo, hi = math.Min(lo, p.PSNR), math.Max(hi, p.PSNR)
		}
		return polyFit(xs, ys, 3), lo, hi
	}
	ca, la, ha := curve(anchor)
	ct, lt, ht := curve(test)
	lo, hi := math.Max(la, lt), math.Min(ha, ht)
	if hi <= lo {
		return 0, errors.New("bdrate: quality ranges do not overlap")
	}
	d := (polyInt(ct, lo, hi) - polyInt(ca, lo, hi)) / (hi - lo)
	return (math.Pow(10, d) - 1) * 100, nil
}
