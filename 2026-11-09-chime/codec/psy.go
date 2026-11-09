package codec

import "math"

// MaskThreshold returns, per band, the noise power per coefficient that stays
// below the masking threshold for the block spectrum x (MDCT coefficients).
// prev, if non-nil, is the previous block's threshold at the same layout and is
// used to limit pre-echo (a threshold may not jump more than preEchoRise× up).
func MaskThreshold(x []float64, l *Layout, prev []float64) []float64 {
	m := len(x)
	p := make([]float64, m)
	for k := 0; k < m; k++ {
		var d float64
		switch {
		case k == 0:
			d = x[1]
		case k == m-1:
			d = -x[m-2]
		default:
			d = x[k+1] - x[k-1]
		}
		p[k] = (x[k]*x[k] + 0.5*d*d) / 2
	}
	return maskFromPower(p, l, prev)
}

const preEchoRise = 3.0

// maskFromPower is the shared core: p is power per coefficient (any transform
// with the same bin spacing as the layout).
func maskFromPower(p []float64, l *Layout, prev []float64) []float64 {
	nb := l.NB()
	e := make([]float64, nb)    // mean power per coef
	tone := make([]float64, nb) // tonality 0..1
	for b := 0; b < nb; b++ {
		lo, hi := l.Edges[b], l.Edges[b+1]
		var sum, logsum float64
		for k := lo; k < hi; k++ {
			v := p[k] + 1e-3
			sum += v
			logsum += math.Log(v)
		}
		w := float64(hi - lo)
		am := sum / w
		e[b] = sum/w - 1e-3
		if e[b] < 0 {
			e[b] = 0
		}
		if hi-lo >= 4 {
			sfm := 10 * math.Log10(math.Exp(logsum/w)/am) // ≤ 0 dB
			tone[b] = math.Min(1, math.Max(0, sfm/-40))
		}
	}
	thr := make([]float64, nb)
	for i := 0; i < nb; i++ {
		var masked float64
		row := l.Spr[i]
		for j := 0; j < nb; j++ {
			masked += e[j] * row[j]
		}
		offDB := tone[i]*(14.5+l.Bark[i]) + (1-tone[i])*5.5
		t := masked * math.Pow(10, -offDB/10)
		if prev != nil && len(prev) == nb {
			if lim := prev[i] * preEchoRise; t > lim {
				t = lim
			}
		}
		if t < l.ATH[i] {
			t = l.ATH[i]
		}
		thr[i] = t
	}
	return thr
}
