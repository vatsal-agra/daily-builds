package codec

import (
	"math"
	"sort"
)

// Quality metrics. SNR/segSNR are the classical waveform measures; NMR
// (noise-to-mask ratio) is the perceptual one: for every analysis frame and
// critical-ish band the coding-noise power is compared with the masking
// threshold of the *original*, estimated here from a Hann-windowed FFT
// (a different spectral estimator than the MDCT pseudo-spectrum the encoder uses).

// Metrics summarises decoded vs. original audio.
type Metrics struct {
	SNR         float64 // dB, whole signal, all channels
	SegSNR      float64 // dB, mean of 20 ms segment SNRs (clamped to [-10, 35])
	MeanNMR     float64 // dB, mean over audible band-frames
	AudibleFrac float64 // fraction of audible band-frames whose noise exceeds the mask (NMR > 0 dB)
	WorstNMR    float64 // dB, highest per-frame mean NMR
	MeanExcess  float64 // dB, mean of max(0, NMR) over audible band-frames: how far noise pokes above the mask on average
	P95NMR      float64 // dB, 95th percentile of per-band NMR
	HoleFrac    float64 // fraction of audible band-frames that lost >6 dB of energy (spectral holes)
	TempExcess  float64 // like MeanExcess but at 256-sample time resolution (exposes pre-echo)
	TempP95     float64 // like P95NMR at 256-sample resolution
	BandFrames  int
}

const nmrN = 2048

// Compare computes all metrics. Lengths must match.
func Compare(orig, dec *Audio) (*Metrics, error) {
	if len(orig.Ch) != len(dec.Ch) || orig.Frames() != dec.Frames() || orig.Rate != dec.Rate {
		return nil, errShape
	}
	m := &Metrics{}
	var sig, noi float64
	for c := range orig.Ch {
		for i, v := range orig.Ch[c] {
			d := dec.Ch[c][i] - v
			sig += v * v
			noi += d * d
		}
	}
	m.SNR = ratioDB(sig, noi)
	// segmental SNR
	seg := orig.Rate / 50
	var sum float64
	var cnt int
	for c := range orig.Ch {
		for s := 0; s+seg <= len(orig.Ch[c]); s += seg {
			var a, b float64
			for i := s; i < s+seg; i++ {
				d := dec.Ch[c][i] - orig.Ch[c][i]
				a += orig.Ch[c][i] * orig.Ch[c][i]
				b += d * d
			}
			if a < 1e-9 && b < 1e-9 {
				continue // digital silence on both sides carries no information
			}
			v := ratioDB(a, b)
			sum += math.Max(-10, math.Min(35, v))
			cnt++
		}
	}
	if cnt > 0 {
		m.SegSNR = sum / float64(cnt)
	}
	// NMR at two time/frequency resolutions: 2048-point (frequency view) and
	// 256-point (time view — the one that exposes pre-echo smeared across a long block).
	long := nmrPass(orig, dec, nmrN)
	m.BandFrames = long.total
	m.MeanNMR, m.AudibleFrac, m.WorstNMR = long.mean, long.frac, long.worst
	m.MeanExcess, m.P95NMR, m.HoleFrac = long.excess, long.p95, long.holes
	short := nmrPass(orig, dec, 2*ShortM)
	m.TempExcess, m.TempP95 = short.excess, short.p95
	return m, nil
}

type nmrResult struct {
	total                                 int
	mean, frac, worst, excess, p95, holes float64
}

// nmrPass slides an n-point Hann FFT (hop n/2) over original and error, comparing
// error power per band with the masking threshold of the original.
func nmrPass(orig, dec *Audio, n int) nmrResult {
	lay := LayoutFor(n/2, orig.Rate)
	plan := newFFT(n)
	hann := make([]float64, n)
	var w2 float64
	for i := range hann {
		hann[i] = 0.5 - 0.5*math.Cos(2*math.Pi*(float64(i)+0.5)/float64(n))
		w2 += hann[i] * hann[i]
	}
	buf := make([]complex128, n)
	pow := func(x []float64, s int) []float64 {
		for i := 0; i < n; i++ {
			v := 0.0
			if s+i < len(x) {
				v = x[s+i]
			}
			buf[i] = complex(v*hann[i], 0)
		}
		plan.transform(buf)
		p := make([]float64, n/2)
		for k := range p {
			re, im := real(buf[k]), imag(buf[k])
			p[k] = (re*re + im*im) / w2
		}
		return p
	}
	var nmrSum, excess float64
	var all []float64
	var bad, holes, total int
	worst := math.Inf(-1)
	for c := range orig.Ch {
		diff := make([]float64, orig.Frames())
		for i := range diff {
			diff[i] = dec.Ch[c][i] - orig.Ch[c][i]
		}
		for s := 0; s < orig.Frames(); s += n / 2 {
			po := pow(orig.Ch[c], s)
			pn := pow(diff, s)
			pd := pow(dec.Ch[c], s)
			thr := maskFromPower(po, lay, nil)
			var fsum float64
			var fcnt int
			for b := 0; b < lay.NB(); b++ {
				var e, nn, dd float64
				for k := lay.Edges[b]; k < lay.Edges[b+1]; k++ {
					e += po[k]
					nn += pn[k]
					dd += pd[k]
				}
				w := float64(lay.Edges[b+1] - lay.Edges[b])
				e /= w
				nn /= w
				dd /= w
				if e < lay.ATH[b] { // band is below audibility — ignore
					continue
				}
				v := 10 * math.Log10((nn+1e-9)/thr[b])
				nmrSum += v
				excess += math.Max(0, v)
				all = append(all, v)
				total++
				fsum += v
				fcnt++
				if v > 0 {
					bad++
				}
				if dd < 0.25*e { // decoded band lost >6 dB of energy: a spectral hole
					holes++
				}
			}
			if fcnt > 0 {
				worst = math.Max(worst, fsum/float64(fcnt))
			}
		}
	}
	r := nmrResult{total: total}
	if total > 0 {
		r.mean = nmrSum / float64(total)
		r.frac = float64(bad) / float64(total)
		r.worst = worst
		r.excess = excess / float64(total)
		r.holes = float64(holes) / float64(total)
		sort.Float64s(all)
		r.p95 = all[int(0.95*float64(len(all)-1))]
	}
	return r
}

func ratioDB(sig, noise float64) float64 {
	if noise < 1e-9 {
		return 120
	}
	if sig < 1e-9 {
		return -120
	}
	return 10 * math.Log10(sig/noise)
}

var errShape = errString("metrics: audio shapes differ")

type errString string

func (e errString) Error() string { return string(e) }
