package codec

import (
	"math"
	"sync"
)

const (
	FrameN     = 1024 // new samples per frame (hop)
	LongM      = 1024
	ShortM     = 128
	NumShort   = 8
	shortStart = 448 // offset of the first short window inside the 2048 frame
)

// Layout is the scale-factor band partition of one block size at a sample rate.
type Layout struct {
	M     int
	Rate  int
	Edges []int     // len NB+1
	Bark  []float64 // centre of each band in Bark
	Hz    []float64 // centre frequency
	ATH   []float64 // absolute-threshold noise power per coefficient
	Spr   [][]float64
}

func (l *Layout) NB() int { return len(l.Edges) - 1 }

func barkOf(f float64) float64 {
	return 13*math.Atan(0.00076*f) + 3.5*math.Atan((f/7500)*(f/7500))
}

// critical bandwidth (Zwicker/Terhardt) in Hz at frequency f.
func critBW(f float64) float64 {
	k := f / 1000
	return 25 + 75*math.Pow(1+1.4*k*k, 0.69)
}

// athDB: Terhardt absolute threshold of hearing in dB SPL.
func athDB(f float64) float64 {
	if f < 20 {
		f = 20
	}
	k := f / 1000
	v := 3.64*math.Pow(k, -0.8) - 6.5*math.Exp(-0.6*(k-3.3)*(k-3.3)) + 1e-3*math.Pow(k, 4)
	if v > 90 {
		v = 90
	}
	return v
}

// athPower converts dB SPL to a white-noise power per orthonormal coefficient,
// assuming 16-bit full scale (±32768) plays back at 96 dB SPL.
func athPower(db float64) float64 {
	amp := 32768 * math.Pow(10, (db-96)/20)
	return amp * amp
}

var layoutCache sync.Map

type layoutKey struct{ m, rate int }

// LayoutFor builds (and caches) the band layout for block size m at the given rate.
func LayoutFor(m, rate int) *Layout {
	key := layoutKey{m, rate}
	if v, ok := layoutCache.Load(key); ok {
		return v.(*Layout)
	}
	l := buildLayout(m, rate)
	layoutCache.Store(key, l)
	return l
}

func buildLayout(m, rate int) *Layout {
	l := &Layout{M: m, Rate: rate}
	binHz := float64(rate) / 2 / float64(m)
	minW, maxW := 4, 32
	if m == ShortM {
		minW, maxW = 4, 16
	}
	k := 0
	l.Edges = append(l.Edges, 0)
	for k < m {
		f := (float64(k) + 0.5) * binHz
		w := int(math.Round(critBW(f) * 0.5 / binHz))
		if w < minW {
			w = minW
		}
		if w > maxW {
			w = maxW
		}
		if k+w > m || m-(k+w) < minW {
			w = m - k // absorb a tiny tail
		}
		k += w
		l.Edges = append(l.Edges, k)
	}
	nb := l.NB()
	l.Bark = make([]float64, nb)
	l.Hz = make([]float64, nb)
	l.ATH = make([]float64, nb)
	for b := 0; b < nb; b++ {
		lo, hi := l.Edges[b], l.Edges[b+1]
		f := (float64(lo+hi) / 2) * binHz
		l.Hz[b] = f
		l.Bark[b] = barkOf(f)
		minDB := math.Inf(1)
		for _, kk := range []int{lo, (lo + hi) / 2, hi - 1} {
			if d := athDB((float64(kk) + 0.5) * binHz); d < minDB {
				minDB = d
			}
		}
		l.ATH[b] = athPower(minDB)
	}
	l.Spr = make([][]float64, nb)
	for i := range l.Spr {
		l.Spr[i] = make([]float64, nb)
		for j := range l.Spr[i] {
			l.Spr[i][j] = math.Pow(10, spreadDB(l.Bark[i]-l.Bark[j])/10)
		}
	}
	return l
}

// spreadDB is the Schroeder spreading function; dz = maskee Bark − masker Bark.
func spreadDB(dz float64) float64 {
	x := dz + 0.474
	return 15.81 + 7.5*x - 17.5*math.Sqrt(1+x*x)
}

// NFGroup is the number of consecutive bands that share one noise-fill level.
func (l *Layout) NFGroup() int {
	if l.M == ShortM {
		return 5
	}
	return 6
}
