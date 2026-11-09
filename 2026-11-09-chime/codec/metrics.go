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
	// NMR
	lay := LayoutFor(nmrN/2, orig.Rate)
	plan := newFFT(nmrN)
	hann := make([]float64, nmrN)
	var w2 float64
	for i := range hann {
		hann[i] = 0.5 - 0.5*math.Cos(2*math.Pi*(float64(i)+0.5)/nmrN)
		w2 += hann[i] * hann[i]
	}
	buf := make([]complex128, nmrN)
	pow := func(x []float64, s int) []float64 {
		for i := 0; i < nmrN; i++ {
			v := 0.0
			if s+i < len(x) {
				v = x[s+i]
			}
			buf[i] = complex(v*hann[i], 0)
		}
		plan.transform(buf)
		p := make([]float64, nmrN/2)
		for k := range p {
			re, im := real(buf[k]), imag(buf[k])
			p[k] = (re*re + im*im) / w2
		}
		return p
	}
	var nmrSum, excess float64
	var all []float64
	var bad, total int
	worst := math.Inf(-1)
	for c := range orig.Ch {
		diff := make([]float64, orig.Frames())
		for i := range diff {
			diff[i] = dec.Ch[c][i] - orig.Ch[c][i]
		}
		for s := 0; s < orig.Frames(); s += nmrN / 2 {
			po := pow(orig.Ch[c], s)
			pn := pow(diff, s)
			thr := maskFromPower(po, lay, nil)
			var fsum float64
			var fcnt int
			for b := 0; b < lay.NB(); b++ {
				var e, nn float64
				for k := lay.Edges[b]; k < lay.Edges[b+1]; k++ {
					e += po[k]
					nn += pn[k]
				}
				w := float64(lay.Edges[b+1] - lay.Edges[b])
				e /= w
				nn /= w
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
			}
			if fcnt > 0 {
				worst = math.Max(worst, fsum/float64(fcnt))
			}
		}
	}
	m.BandFrames = total
	if total > 0 {
		m.MeanNMR = nmrSum / float64(total)
		m.AudibleFrac = float64(bad) / float64(total)
		m.WorstNMR = worst
		m.MeanExcess = excess / float64(total)
		sort.Float64s(all)
		m.P95NMR = all[int(0.95*float64(len(all)-1))]
	}
	return m, nil
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
