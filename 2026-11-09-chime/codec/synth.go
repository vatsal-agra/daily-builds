package codec

import (
	"fmt"
	"math"
	"math/rand"
)

// Procedural test signals. Everything is deterministic in (name, seconds, rate, seed).

// SignalNames lists the built-in generators.
var SignalNames = []string{"tones", "castanets", "bells", "voice", "noise", "sweep", "silence", "mix"}

type gen struct {
	rate int
	n    int
	r    *rand.Rand
}

func (g *gen) t(i int) float64 { return float64(i) / float64(g.rate) }

// Generate renders a named stereo test signal (16-bit range).
func Generate(name string, seconds float64, rate int, seed int64) (*Audio, error) {
	if !(seconds > 0 && seconds <= 600) {
		return nil, fmt.Errorf("duration must be in (0, 600] seconds")
	}
	if rate < 8000 || rate > 192000 {
		return nil, fmt.Errorf("sample rate out of range")
	}
	g := &gen{rate: rate, n: int(seconds * float64(rate)), r: rand.New(rand.NewSource(seed))}
	if g.n < 1 {
		g.n = 1
	}
	var l, r []float64
	switch name {
	case "tones":
		l, r = g.tones()
	case "castanets":
		l, r = g.castanets()
	case "bells":
		l, r = g.bells()
	case "voice":
		l, r = g.voice()
	case "noise":
		l, r = g.noise()
	case "sweep":
		l, r = g.sweep()
	case "silence":
		l, r = make([]float64, g.n), make([]float64, g.n)
	case "mix":
		l, r = g.mix()
	default:
		return nil, fmt.Errorf("unknown signal %q (have %v)", name, SignalNames)
	}
	return &Audio{Rate: rate, Ch: [][]float64{l, r}}, nil
}

func (g *gen) pair() ([]float64, []float64) { return make([]float64, g.n), make([]float64, g.n) }

func pan(l, r []float64, i int, v, p float64) { // p in [0,1]
	l[i] += v * math.Cos(p*math.Pi/2)
	r[i] += v * math.Sin(p*math.Pi/2)
}

func (g *gen) tones() ([]float64, []float64) {
	l, r := g.pair()
	freqs := []float64{220, 329.63, 440, 554.37, 880}
	pans := []float64{0.2, 0.7, 0.5, 0.3, 0.8}
	for i := 0; i < g.n; i++ {
		t := g.t(i)
		env := 0.6 + 0.4*math.Sin(2*math.Pi*0.3*t)
		for j, f := range freqs {
			vib := 1 + 0.004*math.Sin(2*math.Pi*(4.5+0.3*float64(j))*t)
			pan(l, r, i, 3500*env/float64(1+j/2)*math.Sin(2*math.Pi*f*vib*t), pans[j])
		}
	}
	return l, r
}

func (g *gen) castanets() ([]float64, []float64) {
	l, r := g.pair()
	t := 0.15
	for t < g.t(g.n)-0.05 {
		start := int(t * float64(g.rate))
		amp := 9000 + g.r.Float64()*7000
		p := g.r.Float64()
		tau := (0.004 + 0.004*g.r.Float64()) * float64(g.rate)
		prev := 0.0
		for i := start; i < g.n && float64(i-start) < 8*tau; i++ {
			w := g.r.NormFloat64()
			hp := w - 0.6*prev // spectral tilt toward the highs
			prev = w
			pan(l, r, i, amp*hp*math.Exp(-float64(i-start)/tau), p)
		}
		t += []float64{0.12, 0.12, 0.25, 0.12, 0.38}[g.r.Intn(5)] + g.r.Float64()*0.01
	}
	for i := 0; i < g.n; i++ { // faint pad so the gaps are not digital silence
		v := 30 * g.r.NormFloat64()
		l[i] += v
		r[i] += v
	}
	return l, r
}

func (g *gen) bells() ([]float64, []float64) {
	l, r := g.pair()
	ratios := []float64{1, 2.76, 5.40, 8.93, 13.34, 18.64}
	notes := []float64{523.25, 659.25, 783.99, 987.77, 698.46, 880, 1046.5}
	for s := 0; s*7 < int(g.t(g.n)*10)+1; s++ {
		t0 := 0.1 + float64(s)*0.7
		start := int(t0 * float64(g.rate))
		if start >= g.n {
			break
		}
		f0 := notes[s%len(notes)]
		p := float64(s%5) / 4
		for j, rt := range ratios {
			f := f0 * rt
			if f > float64(g.rate)*0.45 {
				continue
			}
			tau := 1.6 / (1 + 0.7*float64(j))
			a := 5000 / (1 + 0.8*float64(j))
			for i := start; i < g.n; i++ {
				tt := g.t(i - start)
				if tt > 8*tau {
					break
				}
				pan(l, r, i, a*math.Exp(-tt/tau)*math.Sin(2*math.Pi*f*tt), p)
			}
		}
	}
	return l, r
}

type biquad struct{ b0, a1, a2, z1, z2 float64 }

func resonator(f, bw, rate float64) biquad {
	rr := math.Exp(-math.Pi * bw / rate)
	th := 2 * math.Pi * f / rate
	return biquad{b0: 1 - rr, a1: -2 * rr * math.Cos(th), a2: rr * rr}
}

func (q *biquad) step(x float64) float64 {
	y := q.b0*x - q.a1*q.z1 - q.a2*q.z2
	q.z2, q.z1 = q.z1, y
	return y
}

func (g *gen) voice() ([]float64, []float64) {
	l, r := g.pair()
	vowels := [][3]float64{{800, 1200, 2500}, {400, 2000, 2550}, {300, 2300, 3000}, {500, 900, 2500}, {320, 800, 2300}}
	var res [3]biquad
	phase := 0.0
	seg := g.t(g.n) / float64(len(vowels))
	for i := 0; i < g.n; i++ {
		t := g.t(i)
		f0 := 110 + 50*t/g.t(g.n) + 3*math.Sin(2*math.Pi*5.5*t)
		phase += f0 / float64(g.rate)
		if phase >= 1 {
			phase -= 1
		}
		vi := int(t / seg)
		if vi >= len(vowels) {
			vi = len(vowels) - 1
		}
		frac := t/seg - float64(vi)
		nx := vi + 1
		if nx >= len(vowels) {
			nx = vi
		}
		sm := math.Min(1, math.Max(0, (frac-0.7)/0.3))
		var y float64
		src := (2*phase-1)*0.8 + 0.05*g.r.NormFloat64()
		src *= 1 - 0.3*math.Cos(2*math.Pi*phase) // crude glottal shape
		for k := 0; k < 3; k++ {
			f := vowels[vi][k]*(1-sm) + vowels[nx][k]*sm
			if i%32 == 0 {
				z1, z2 := res[k].z1, res[k].z2
				res[k] = resonator(f, 60+40*float64(k), float64(g.rate))
				res[k].z1, res[k].z2 = z1, z2
			}
			y += res[k].step(src) / float64(1+k)
		}
		gate := 0.5 + 0.5*math.Sin(2*math.Pi*1.7*t)
		v := 26000 * y * (0.4 + 0.6*gate)
		l[i], r[i] = v, v
	}
	return l, r
}

func (g *gen) noise() ([]float64, []float64) {
	l, r := g.pair()
	var bl, br [7]float64
	for i := 0; i < g.n; i++ {
		wl, wr := g.r.NormFloat64(), g.r.NormFloat64()
		// Paul Kellet's pink-noise filter
		bl[0] = 0.99886*bl[0] + wl*0.0555179
		bl[1] = 0.99332*bl[1] + wl*0.0750759
		bl[2] = 0.96900*bl[2] + wl*0.1538520
		bl[3] = 0.86650*bl[3] + wl*0.3104856
		bl[4] = 0.55000*bl[4] + wl*0.5329522
		bl[5] = -0.7616*bl[5] - wl*0.0168980
		l[i] = 2200 * (bl[0] + bl[1] + bl[2] + bl[3] + bl[4] + bl[5] + bl[6] + wl*0.5362)
		bl[6] = wl * 0.115926
		br[0] = 0.99886*br[0] + wr*0.0555179
		br[1] = 0.99332*br[1] + wr*0.0750759
		br[2] = 0.96900*br[2] + wr*0.1538520
		br[3] = 0.86650*br[3] + wr*0.3104856
		br[4] = 0.55000*br[4] + wr*0.5329522
		br[5] = -0.7616*br[5] - wr*0.0168980
		r[i] = 2200 * (br[0] + br[1] + br[2] + br[3] + br[4] + br[5] + br[6] + wr*0.5362)
		br[6] = wr * 0.115926
	}
	return l, r
}

func (g *gen) sweep() ([]float64, []float64) {
	l, r := g.pair()
	f0, f1 := 50.0, float64(g.rate)*0.45
	T := g.t(g.n)
	k := math.Log(f1/f0) / T
	for i := 0; i < g.n; i++ {
		t := g.t(i)
		ph := 2 * math.Pi * f0 * (math.Exp(k*t) - 1) / k
		v := 9000 * math.Sin(ph)
		l[i], r[i] = v, v*0.7
	}
	return l, r
}

func (g *gen) mix() ([]float64, []float64) {
	parts := []struct {
		f func() ([]float64, []float64)
		w float64
	}{
		{(&gen{g.rate, g.n, rand.New(rand.NewSource(g.r.Int63()))}).voice, 0.55},
		{(&gen{g.rate, g.n, rand.New(rand.NewSource(g.r.Int63()))}).bells, 0.5},
		{(&gen{g.rate, g.n, rand.New(rand.NewSource(g.r.Int63()))}).castanets, 0.45},
		{(&gen{g.rate, g.n, rand.New(rand.NewSource(g.r.Int63()))}).tones, 0.35},
	}
	l, r := g.pair()
	for _, p := range parts {
		a, b := p.f()
		for i := range l {
			l[i] += a[i] * p.w
			r[i] += b[i] * p.w
		}
	}
	return l, r
}
