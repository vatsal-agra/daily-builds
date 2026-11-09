package codec

import (
	"errors"
	"fmt"
	"math"
)

// Params control the encoder.
type Params struct {
	Kbps      float64 // target bitrate; 0 → fixed quality
	Quality   float64 // dB offset applied to the masking threshold (higher = finer) when Kbps == 0
	MS        bool    // allow adaptive M/S joint stereo
	NoiseFill bool
	Flat      bool // baseline: one global step for every band, no psychoacoustics
	Transient bool // allow block switching
}

// DefaultParams are the settings used by the CLI.
func DefaultParams() Params {
	return Params{Kbps: 128, MS: true, NoiseFill: false, Transient: true}
}

type chanFrame struct {
	blocks [][]float64
	thr    [][]float64
}

// Analysis is the encoder's rate-independent state.
type Analysis struct {
	Audio *Audio
	Short []bool
	lr    [][]chanFrame // [ch][frame]
	ms    [][]chanFrame // [2][frame] (stereo only)
	p     Params
}

const (
	offLo  = -40.0
	offHi  = 70.0
	dz     = 0.1 // dead-zone: round at 0.6 instead of 0.5
	nfGain = 0.5 // noise-fill level relative to the true band rms (−6 dB: fills holes without doubling the error)
)

func analyze(a *Audio, p Params) (*Analysis, error) {
	if len(a.Ch) < 1 || len(a.Ch) > 2 {
		return nil, errors.New("need 1 or 2 channels")
	}
	n := a.Frames()
	if n == 0 {
		return nil, errors.New("empty audio")
	}
	if n > 1<<30 {
		return nil, errors.New("audio too long (limit 2^30 samples per channel)")
	}
	for c := range a.Ch {
		if len(a.Ch[c]) != n {
			return nil, errors.New("channels have different lengths")
		}
		for i, v := range a.Ch[c] {
			if math.IsNaN(v) || math.IsInf(v, 0) || math.Abs(v) > 1<<24 {
				return nil, fmt.Errorf("channel %d sample %d is not a usable value (%g)", c, i, v)
			}
		}
	}
	an := &Analysis{Audio: a, p: p}
	nf := NumFrames(n)
	if p.Transient {
		an.Short = DetectTransients(a.Ch)
	} else {
		an.Short = make([]bool, nf)
	}
	nch := len(a.Ch)
	an.lr = make([][]chanFrame, nch)
	for c := 0; c < nch; c++ {
		an.lr[c] = make([]chanFrame, nf)
	}
	for f := 0; f < nf; f++ {
		for c := 0; c < nch; c++ {
			an.lr[c][f].blocks = AnalyzeFrame(a.Ch[c], f, an.Short)
		}
	}
	if nch == 2 && p.MS {
		an.ms = [][]chanFrame{make([]chanFrame, nf), make([]chanFrame, nf)}
		for f := 0; f < nf; f++ {
			l, r := an.lr[0][f].blocks, an.lr[1][f].blocks
			for c := 0; c < 2; c++ {
				an.ms[c][f].blocks = make([][]float64, len(l))
			}
			for i := range l {
				m := make([]float64, len(l[i]))
				s := make([]float64, len(l[i]))
				for k := range m {
					m[k] = (l[i][k] + r[i][k]) * math.Sqrt2 / 2
					s[k] = (l[i][k] - r[i][k]) * math.Sqrt2 / 2
				}
				an.ms[0][f].blocks[i], an.ms[1][f].blocks[i] = m, s
			}
		}
	}
	// psychoacoustic thresholds (temporal pre-echo limiter chains long→long)
	for c := 0; c < nch; c++ {
		var prev []float64
		for f := 0; f < nf; f++ {
			cf := &an.lr[c][f]
			cf.thr = make([][]float64, len(cf.blocks))
			for i, b := range cf.blocks {
				lay := LayoutFor(len(b), a.Rate)
				cf.thr[i] = MaskThreshold(b, lay, prev)
				prev = cf.thr[i]
			}
			if len(cf.blocks) > 1 {
				prev = nil
			}
		}
	}
	if an.ms != nil {
		for f := 0; f < nf; f++ {
			for c := 0; c < 2; c++ {
				an.ms[c][f].thr = make([][]float64, len(an.lr[0][f].blocks))
			}
			for i := range an.lr[0][f].blocks {
				tl, tr := an.lr[0][f].thr[i], an.lr[1][f].thr[i]
				lay := LayoutFor(len(an.lr[0][f].blocks[i]), a.Rate)
				tm := make([]float64, len(tl))
				ts := make([]float64, len(tl))
				sx := an.ms[1][f].blocks[i]
				for b := range tm {
					t := math.Min(tl[b], tr[b])
					// Noise in L and R is (nM+nS)/2, so M and S must share the budget:
					// S noise is limited to t; if S is below t it is quantised to zero and
					// only adds its own energy, leaving the rest of 2t for M.
					var eS float64
					lo, hi := lay.Edges[b], lay.Edges[b+1]
					for k := lo; k < hi; k++ {
						eS += sx[k] * sx[k]
					}
					eS /= float64(hi - lo)
					tm[b] = 2*t - math.Min(eS, t)
					ts[b] = t
				}
				an.ms[0][f].thr[i], an.ms[1][f].thr[i] = tm, ts
			}
		}
	}
	return an, nil
}

func clampSF(s int) int {
	if s < SFMin {
		return SFMin
	}
	if s > SFMax {
		return SFMax
	}
	return s
}

// quantBlock quantises one block given its per-band thresholds and the offset.
func quantBlock(x, thr []float64, lay *Layout, off float64, flat, nfill bool) BlockQ {
	b := newBlockQ(lay)
	gain := math.Pow(10, -off/10)
	flatSF := clampSF(int(math.Round(4 * (10 - off/6.0206))))
	for bd := 0; bd < lay.NB(); bd++ {
		lo, hi := lay.Edges[bd], lay.Edges[bd+1]
		s := flatSF
		if !flat {
			delta := math.Sqrt(12 * thr[bd] * gain)
			s = clampSF(int(math.Round(4 * math.Log2(delta))))
		}
		inv := 1 / Step(s)
		var any bool
		for k := lo; k < hi; k++ {
			v := math.Abs(x[k]) * inv
			q := int32(math.Floor(v + 0.5 - dz))
			if q > maxQ {
				q = maxQ
			}
			if q != 0 {
				any = true
				if x[k] < 0 {
					q = -q
				}
			}
			b.Q[k] = q
		}
		if any {
			b.NZ[bd] = true
			b.SF[bd] = s
		}
	}
	if nfill {
		assignNoise(&b, x, lay)
	}
	return b
}

// bitCost estimates the bits needed for x at the given per-band steps.
func bitCost(x, thr []float64, lay *Layout, off float64, flat bool) float64 {
	gain := math.Pow(10, -off/10)
	flatSF := clampSF(int(math.Round(4 * (10 - off/6.0206))))
	var bits float64
	for bd := 0; bd < lay.NB(); bd++ {
		s := flatSF
		if !flat {
			s = clampSF(int(math.Round(4 * math.Log2(math.Sqrt(12*thr[bd]*gain)))))
		}
		inv := 1 / Step(s)
		for k := lay.Edges[bd]; k < lay.Edges[bd+1]; k++ {
			bits += math.Log2(1 + math.Abs(x[k])*inv)
		}
	}
	return bits
}

func (an *Analysis) quantFrame(f int, off float64) *FrameQ {
	a := an.Audio
	nch := len(a.Ch)
	fr := &FrameQ{}
	src := an.lr
	if nch == 2 && an.ms != nil {
		var lrBits, msBits float64
		for i, bl := range an.lr[0][f].blocks {
			lay := LayoutFor(len(bl), a.Rate)
			for c := 0; c < 2; c++ {
				lrBits += bitCost(an.lr[c][f].blocks[i], an.lr[c][f].thr[i], lay, off, an.p.Flat)
				msBits += bitCost(an.ms[c][f].blocks[i], an.ms[c][f].thr[i], lay, off, an.p.Flat)
			}
		}
		if msBits < lrBits*0.97 {
			fr.MS = true
			src = an.ms
		}
	}
	for c := 0; c < nch; c++ {
		cf := &src[c][f]
		fr.Blocks[c] = make([]BlockQ, len(cf.blocks))
		for i, x := range cf.blocks {
			fr.Blocks[c][i] = quantBlock(x, cf.thr[i], LayoutFor(len(x), a.Rate), off, an.p.Flat, an.p.NoiseFill)
		}
	}
	return fr
}

// Stats describes an encode.
type Stats struct {
	Offset      float64
	Bytes       int
	Kbps        float64
	Frames      int
	ShortFrames int
	MSFrames    int
	SFBits      float64
	FlagBits    float64
	CoefBits    float64
	NoiseBits   float64
	BandBits    [2][]float64
	BlockCnt    [2]int
	Iterations  int
	Overshoot   bool // target bitrate could not be met even at the coarsest setting
	Capped      bool // target bitrate is more than the codec can spend (finest setting reached)
}

func (an *Analysis) encodeAt(off float64, track bool) ([]byte, *Stats) {
	a := an.Audio
	rc := NewEncoder()
	rc.Track = track
	sx := NewSyntax(rc, a.Rate, len(a.Ch), an.p.NoiseFill)
	sx.Flags(append([]bool(nil), an.Short...))
	st := &Stats{Offset: off, Frames: len(an.Short)}
	for f := range an.Short {
		fr := an.quantFrame(f, off)
		sx.Frame(fr, an.Short[f])
		if an.Short[f] {
			st.ShortFrames++
		}
		if fr.MS {
			st.MSFrames++
		}
	}
	out := rc.Finish()
	st.SFBits, st.FlagBits, st.CoefBits, st.NoiseBits = sx.SFBits, sx.FlagBits, sx.CoefBits, sx.NoiseBits
	st.BandBits, st.BlockCnt = sx.BandBits, sx.BlockCnt
	return out, st
}

// Encode compresses audio into a .chm file image.
func Encode(a *Audio, p Params) ([]byte, *Stats, error) {
	if p.Kbps < 0 || math.IsNaN(p.Kbps) || math.IsNaN(p.Quality) {
		return nil, nil, fmt.Errorf("invalid bitrate %g / quality %g (bitrate must be ≥ 0, quality finite)", p.Kbps, p.Quality)
	}
	if p.Kbps > 0 && p.Kbps < 1 {
		return nil, nil, fmt.Errorf("bitrate %.2f kbps is below the 1 kbps minimum", p.Kbps)
	}
	if a.Rate < 8000 {
		return nil, nil, errors.New("sample rate too low")
	}
	an, err := analyze(a, p)
	if err != nil {
		return nil, nil, err
	}
	dur := float64(a.Frames()) / float64(a.Rate)
	size := func(off float64) int {
		b, _ := an.encodeAt(off, false)
		return len(b) + headerSize
	}
	off := p.Quality
	iters := 0
	over, capped := false, false
	if p.Kbps > 0 {
		target := int(p.Kbps * 1000 * dur / 8)
		lo, hi := offLo, offHi
		switch {
		case size(lo) > target:
			off, over = lo, true
			iters = 1
		case size(hi) <= target:
			off, capped = hi, true
			iters = 2
		default:
			for i := 0; i < 16; i++ {
				mid := (lo + hi) / 2
				if size(mid) <= target {
					lo = mid
				} else {
					hi = mid
				}
				iters = i + 3
			}
			off = lo
		}
	} else if off < offLo || off > offHi {
		return nil, nil, fmt.Errorf("quality offset must be within [%g, %g] dB", offLo, offHi)
	}
	payload, st := an.encodeAt(off, true)
	st.Iterations = iters
	st.Overshoot = over
	st.Capped = capped
	file := packContainer(a, an, payload)
	st.Bytes = len(file)
	st.Kbps = float64(len(file)) * 8 / dur / 1000
	return file, st, nil
}

// assignNoise sets one noise-fill level per group of bands from the energy of
// the group's zero-quantised bands.
func assignNoise(b *BlockQ, x []float64, l *Layout) {
	G := l.NFGroup()
	for g0 := 0; g0 < l.NB(); g0 += G {
		var e, ath float64
		var w, cnt int
		for bd := g0; bd < g0+G && bd < l.NB(); bd++ {
			if b.NZ[bd] {
				continue
			}
			for k := l.Edges[bd]; k < l.Edges[bd+1]; k++ {
				e += x[k] * x[k]
			}
			w += l.Edges[bd+1] - l.Edges[bd]
			ath += l.ATH[bd]
			cnt++
		}
		if cnt == 0 {
			continue
		}
		rms := math.Sqrt(e/float64(w)) * nfGain
		level := 0
		if rms*rms > ath/float64(cnt) && rms > NoiseRMS(1) {
			level = int(math.Round(math.Log2(rms/0.25))) + 1
			if level > NFMax {
				level = NFMax
			}
		}
		for bd := g0; bd < g0+G && bd < l.NB(); bd++ {
			if !b.NZ[bd] {
				b.NF[bd] = level
			}
		}
	}
}
