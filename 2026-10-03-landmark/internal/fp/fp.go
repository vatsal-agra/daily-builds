// Package fp turns audio into a constellation of spectral peaks and time-shift-invariant landmark hashes.
package fp

import (
	"fmt"
	"math"
	"sort"

	"landmark/internal/dsp"
)

// Params fixes every knob of the fingerprint. Index files store them so queries always match.
type Params struct {
	Rate        int     // analysis sample rate (Hz)
	NFFT        int     // FFT size
	Hop         int     // STFT hop (samples)
	MinBin      int     // lowest spectral bin considered
	MaxBin      int     // highest spectral bin considered (<=511 so bins fit 9 bits)
	TimeR       int     // peak must be the maximum within ±TimeR frames
	FreqR       int     // ... and within ±FreqR bins
	RangeDB     float64 // peaks must lie within this many dB of the loudest spectrogram cell
	PeaksPerSec int     // density cap: strongest N peaks per second kept
	Fan         int     // max pairs formed per anchor peak when indexing
	QueryFan    int     // ... and when querying (larger: asymmetric, tolerates peaks lost to noise)
	MinDT       int     // target zone: minimum frames after the anchor
	MaxDT       int     // ... maximum frames after the anchor (<=63, 6 bits)
	MaxDF       int     // ... maximum |bin difference|
}

// Default is the tuned parameter set.
func Default() Params {
	return Params{Rate: 8000, NFFT: 1024, Hop: 256, MinBin: 8, MaxBin: 450, TimeR: 7, FreqR: 12,
		RangeDB: 60, PeaksPerSec: 24, Fan: 5, QueryFan: 5, MinDT: 2, MaxDT: 63, MaxDF: 80}
}

// FrameSeconds is the duration of one STFT frame step.
func (p Params) FrameSeconds() float64 { return float64(p.Hop) / float64(p.Rate) }

// Peak is a spectrogram local maximum.
type Peak struct {
	T, F int
	DB   float32
}

// Hash is a landmark: a 24-bit key (f1|f2|dt) anchored at frame T.
type Hash struct {
	H uint32
	T int32
}

// Pair is a hash together with the peaks that produced it (used for visualisation).
type Pair struct {
	Hash
	A, B Peak
}

// Spectrogram resamples to p.Rate and returns the dB-magnitude spectrogram (frames × bins).
func Spectrogram(x []float64, rate float64, p Params) [][]float32 {
	y := dsp.Resample(x, rate, float64(p.Rate))
	mag := dsp.STFT(y, p.NFFT, p.Hop)
	for _, row := range mag {
		for k, v := range row {
			row[k] = float32(20 * math.Log10(float64(v)+1e-9))
		}
	}
	return mag
}

func maxFilter1D(src, dst []float32, r int) {
	// monotonic-deque sliding window maximum over [i-r, i+r]
	n := len(src)
	dq := make([]int, 0, 2*r+2)
	head := 0
	for i := 0; i < n+r; i++ {
		if i < n {
			for len(dq) > head && src[dq[len(dq)-1]] <= src[i] {
				dq = dq[:len(dq)-1]
			}
			dq = append(dq, i)
		}
		out := i - r
		if out >= 0 {
			for dq[head] < out-r {
				head++
			}
			dst[out] = src[dq[head]]
		}
	}
}

// FindPeaks picks time-frequency local maxima and thins them to the strongest PeaksPerSec per second.
func FindPeaks(spec [][]float32, p Params) []Peak {
	T := len(spec)
	if T == 0 {
		return nil
	}
	lo, hi := p.MinBin, p.MaxBin
	if hi >= len(spec[0]) {
		hi = len(spec[0]) - 1
	}
	W := hi - lo + 1
	if W < 1 {
		return nil
	}
	// global dB ceiling inside the band
	ceil := float32(-1e9)
	for _, row := range spec {
		for k := lo; k <= hi; k++ {
			if row[k] > ceil {
				ceil = row[k]
			}
		}
	}
	if ceil < -40 { // digital silence / inaudible: nothing to fingerprint
		return nil
	}
	floor := ceil - float32(p.RangeDB)
	// separable max filter: along frequency, then along time
	fm := make([][]float32, T)
	for t := range spec {
		fm[t] = make([]float32, W)
		maxFilter1D(spec[t][lo:hi+1], fm[t], p.FreqR)
	}
	col, colOut := make([]float32, T), make([]float32, T)
	tm := make([][]float32, T)
	for t := range tm {
		tm[t] = make([]float32, W)
	}
	for k := 0; k < W; k++ {
		for t := 0; t < T; t++ {
			col[t] = fm[t][k]
		}
		maxFilter1D(col, colOut, p.TimeR)
		for t := 0; t < T; t++ {
			tm[t][k] = colOut[t]
		}
	}
	var peaks []Peak
	for t := 0; t < T; t++ {
		for k := 0; k < W; k++ {
			v := spec[t][lo+k]
			if v >= tm[t][k] && v > floor {
				peaks = append(peaks, Peak{T: t, F: lo + k, DB: v})
			}
		}
	}
	// density cap per one-second block
	framesPerSec := int(math.Round(1 / p.FrameSeconds()))
	if framesPerSec < 1 {
		framesPerSec = 1
	}
	var kept []Peak
	for i := 0; i < len(peaks); {
		j := i
		blk := peaks[i].T / framesPerSec
		for j < len(peaks) && peaks[j].T/framesPerSec == blk {
			j++
		}
		chunk := append([]Peak(nil), peaks[i:j]...)
		if len(chunk) > p.PeaksPerSec {
			sort.Slice(chunk, func(a, b int) bool { return chunk[a].DB > chunk[b].DB })
			chunk = chunk[:p.PeaksPerSec]
		}
		kept = append(kept, chunk...)
		i = j
	}
	sort.Slice(kept, func(a, b int) bool {
		if kept[a].T != kept[b].T {
			return kept[a].T < kept[b].T
		}
		return kept[a].F < kept[b].F
	})
	return kept
}

// MakeHash packs (f1, f2, dt) into 24 bits: f1:9 | f2:9 | dt:6.
func MakeHash(f1, f2, dt int) uint32 {
	return uint32(f1&0x1FF)<<15 | uint32(f2&0x1FF)<<6 | uint32(dt&0x3F)
}

// Pairs forms anchor→target landmarks: each anchor pairs with its Fan strongest peaks in the target zone.
func Pairs(peaks []Peak, p Params) []Pair { return PairsFan(peaks, p, p.Fan) }

// PairsFan is Pairs with an explicit fan-out.
func PairsFan(peaks []Peak, p Params, fan int) []Pair {
	var out []Pair
	var cand []int
	for i, a := range peaks {
		cand = cand[:0]
		for j := i + 1; j < len(peaks); j++ {
			dt := peaks[j].T - a.T
			if dt > p.MaxDT {
				break
			}
			if dt < p.MinDT {
				continue
			}
			df := peaks[j].F - a.F
			if df < 0 {
				df = -df
			}
			if df <= p.MaxDF {
				cand = append(cand, j)
			}
		}
		if len(cand) > fan {
			sort.Slice(cand, func(x, y int) bool { return peaks[cand[x]].DB > peaks[cand[y]].DB })
			cand = cand[:fan]
		}
		for _, j := range cand {
			b := peaks[j]
			out = append(out, Pair{Hash: Hash{H: MakeHash(a.F, b.F, b.T-a.T), T: int32(a.T)}, A: a, B: b})
		}
	}
	return out
}

// Fingerprint runs the whole pipeline on mono audio at the given sample rate.
func Fingerprint(x []float64, rate float64, p Params) ([]Peak, []Hash) {
	spec := Spectrogram(x, rate, p)
	peaks := FindPeaks(spec, p)
	pairs := Pairs(peaks, p)
	hs := make([]Hash, len(pairs))
	for i, pr := range pairs {
		hs[i] = pr.Hash
	}
	return peaks, hs
}

// Validate rejects parameter sets that would overflow the 24-bit hash or make the pipeline degenerate.
func (p Params) Validate() error {
	switch {
	case p.Rate < 1000 || p.NFFT < 64 || p.NFFT&(p.NFFT-1) != 0 || p.Hop < 1 || p.Hop > p.NFFT:
		return fmt.Errorf("invalid analysis params (rate %d, fft %d, hop %d)", p.Rate, p.NFFT, p.Hop)
	case p.MinBin < 0 || p.MaxBin <= p.MinBin || p.MaxBin > 511 || p.MaxBin > p.NFFT/2:
		return fmt.Errorf("invalid bin range %d–%d (must fit 9 bits and the FFT)", p.MinBin, p.MaxBin)
	case p.MinDT < 1 || p.MaxDT < p.MinDT || p.MaxDT > 63:
		return fmt.Errorf("invalid target zone dt %d–%d (must fit 6 bits)", p.MinDT, p.MaxDT)
	case p.Fan < 1 || p.QueryFan < 1 || p.TimeR < 0 || p.FreqR < 0 || p.PeaksPerSec < 1:
		return fmt.Errorf("invalid peak/fan parameters")
	}
	return nil
}
