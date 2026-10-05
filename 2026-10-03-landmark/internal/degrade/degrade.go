// Package degrade applies realistic signal damage to audio so the matcher can be stress-tested.
package degrade

import (
	"math"
	"math/rand"

	"landmark/internal/dsp"
)

// Crop returns x[start:start+length] (seconds), clamped to the signal.
func Crop(x []float64, rate int, start, length float64) []float64 {
	a := int(start * float64(rate))
	b := a + int(length*float64(rate))
	if a < 0 {
		a = 0
	}
	if b > len(x) {
		b = len(x)
	}
	if a >= b {
		return nil
	}
	return append([]float64(nil), x[a:b]...)
}

// Noise mixes noise into x at the requested signal-to-noise ratio (dB). pink=true uses 1/f-ish noise.
func Noise(x []float64, snrDB float64, pink bool, rng *rand.Rand) []float64 {
	n := make([]float64, len(x))
	var b0, b1, b2 float64
	for i := range n {
		w := rng.NormFloat64()
		if pink { // Paul Kellet's economy pink filter
			b0 = 0.99765*b0 + w*0.0990460
			b1 = 0.96300*b1 + w*0.2965164
			b2 = 0.57000*b2 + w*1.0526913
			w = b0 + b1 + b2 + w*0.1848
		}
		n[i] = w
	}
	ps, pn := dsp.RMS(x), dsp.RMS(n)
	if pn == 0 || ps == 0 {
		return append([]float64(nil), x...)
	}
	k := ps / math.Pow(10, snrDB/20) / pn
	out := make([]float64, len(x))
	for i := range x {
		out[i] = x[i] + k*n[i]
	}
	return out
}

// Gain scales by a decibel amount.
func Gain(x []float64, db float64) []float64 {
	k := math.Pow(10, db/20)
	out := make([]float64, len(x))
	for i, v := range x {
		out[i] = v * k
	}
	return out
}

// Lowpass applies a cascaded pair of biquads (4th-order) at fc Hz.
func Lowpass(x []float64, rate int, fc float64) []float64 {
	b := dsp.LowpassBiquad(fc, float64(rate), 0.707)
	return b.Apply(b.Apply(x))
}

// Distort applies tanh soft-clipping with the given drive (>=1), renormalised to the input RMS.
func Distort(x []float64, drive float64) []float64 {
	out := make([]float64, len(x))
	for i, v := range x {
		out[i] = math.Tanh(drive * v)
	}
	if r, r0 := dsp.RMS(out), dsp.RMS(x); r > 0 {
		for i := range out {
			out[i] *= r0 / r
		}
	}
	return out
}

// Reverb adds a dense multi-tap decaying echo tail (a crude room), `wet` is the tail level 0..1.
func Reverb(x []float64, rate int, wet float64, rng *rand.Rand) []float64 {
	out := append([]float64(nil), x...)
	taps := 24
	for k := 0; k < taps; k++ {
		delay := int((0.012 + 0.22*rng.Float64()) * float64(rate))
		g := wet * math.Exp(-3*float64(delay)/float64(rate)/0.25) * (rng.Float64()*0.6 + 0.4) / math.Sqrt(float64(taps)/4)
		if rng.Intn(2) == 0 {
			g = -g
		}
		for i := delay; i < len(x); i++ {
			out[i] += g * x[i-delay]
		}
	}
	return out
}

// Speed plays x `factor`× faster (pitch and tempo both scale), keeping the nominal sample rate.
func Speed(x []float64, factor float64) []float64 {
	return dsp.Resample(x, factor, 1)
}
