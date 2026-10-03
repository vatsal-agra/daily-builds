// Package dsp holds the signal-processing primitives: FFT, STFT, resampling, filtering.
package dsp

import (
	"math"
	"math/cmplx"
)

// FFT is a reusable radix-2 plan for a fixed power-of-two size.
type FFT struct {
	N       int
	twiddle []complex128
	rev     []int
}

// NewFFT builds a plan. n must be a power of two.
func NewFFT(n int) *FFT {
	if n < 2 || n&(n-1) != 0 {
		panic("dsp: FFT size must be a power of two >= 2")
	}
	f := &FFT{N: n, twiddle: make([]complex128, n/2), rev: make([]int, n)}
	for i := range f.twiddle {
		f.twiddle[i] = cmplx.Exp(complex(0, -2*math.Pi*float64(i)/float64(n)))
	}
	bits := 0
	for 1<<bits < n {
		bits++
	}
	for i := range f.rev {
		r := 0
		for b := 0; b < bits; b++ {
			if i&(1<<b) != 0 {
				r |= 1 << (bits - 1 - b)
			}
		}
		f.rev[i] = r
	}
	return f
}

// Transform computes the forward DFT of x in place.
func (f *FFT) Transform(x []complex128) {
	n := f.N
	for i, r := range f.rev {
		if i < r {
			x[i], x[r] = x[r], x[i]
		}
	}
	for size := 2; size <= n; size <<= 1 {
		half, step := size/2, n/size
		for start := 0; start < n; start += size {
			for k := 0; k < half; k++ {
				t := f.twiddle[k*step] * x[start+k+half]
				x[start+k+half] = x[start+k] - t
				x[start+k] += t
			}
		}
	}
}

// Hann returns a periodic Hann window.
func Hann(n int) []float64 {
	w := make([]float64, n)
	for i := range w {
		w[i] = 0.5 - 0.5*math.Cos(2*math.Pi*float64(i)/float64(n))
	}
	return w
}

// STFT returns magnitude spectra: frames × (nfft/2+1). Trailing partial frames are dropped.
func STFT(x []float64, nfft, hop int) [][]float32 {
	if len(x) < nfft {
		return nil
	}
	plan := NewFFT(nfft)
	win := Hann(nfft)
	nFrames := (len(x)-nfft)/hop + 1
	out := make([][]float32, nFrames)
	buf := make([]complex128, nfft)
	for t := 0; t < nFrames; t++ {
		off := t * hop
		for i := 0; i < nfft; i++ {
			buf[i] = complex(x[off+i]*win[i], 0)
		}
		plan.Transform(buf)
		row := make([]float32, nfft/2+1)
		for k := range row {
			row[k] = float32(cmplx.Abs(buf[k]))
		}
		out[t] = row
	}
	return out
}

func sinc(x float64) float64 {
	if x == 0 {
		return 1
	}
	return math.Sin(math.Pi*x) / (math.Pi * x)
}

// Resample converts x from rate `from` to rate `to` (arbitrary positive reals) using a
// Blackman-windowed sinc kernel; the cutoff drops to the output Nyquist when downsampling.
func Resample(x []float64, from, to float64) []float64 {
	if len(x) == 0 || from <= 0 || to <= 0 {
		return nil
	}
	if from == to {
		return append([]float64(nil), x...)
	}
	ratio := from / to // input samples per output sample
	cut := 1.0
	if ratio > 1 {
		cut = 1 / ratio
	}
	const zeros = 12
	half := float64(zeros) / cut
	n := int(float64(len(x)) / ratio)
	out := make([]float64, n)
	for i := range out {
		c := float64(i) * ratio
		lo := int(math.Ceil(c - half))
		hi := int(math.Floor(c + half))
		var acc, wsum float64
		for j := lo; j <= hi; j++ {
			d := (float64(j) - c) / half // -1..1
			w := 0.42 + 0.5*math.Cos(math.Pi*d) + 0.08*math.Cos(2*math.Pi*d)
			k := cut * sinc(cut*(float64(j)-c)) * w
			wsum += k
			if j >= 0 && j < len(x) {
				acc += x[j] * k
			}
		}
		if wsum != 0 {
			acc /= wsum // unity DC gain even at edges
		}
		out[i] = acc
	}
	return out
}

// Biquad is a direct-form-I second-order section.
type Biquad struct{ b0, b1, b2, a1, a2 float64 }

// LowpassBiquad designs an RBJ low-pass at cutoff fc (Hz) for sample rate fs with quality q.
func LowpassBiquad(fc, fs, q float64) Biquad {
	w := 2 * math.Pi * fc / fs
	al := math.Sin(w) / (2 * q)
	c := math.Cos(w)
	a0 := 1 + al
	return Biquad{(1 - c) / 2 / a0, (1 - c) / a0, (1 - c) / 2 / a0, -2 * c / a0, (1 - al) / a0}
}

// Apply filters x, returning a new slice.
func (b Biquad) Apply(x []float64) []float64 {
	y := make([]float64, len(x))
	var x1, x2, y1, y2 float64
	for i, v := range x {
		o := b.b0*v + b.b1*x1 + b.b2*x2 - b.a1*y1 - b.a2*y2
		x2, x1 = x1, v
		y2, y1 = y1, o
		y[i] = o
	}
	return y
}

// RMS returns the root-mean-square level.
func RMS(x []float64) float64 {
	if len(x) == 0 {
		return 0
	}
	var s float64
	for _, v := range x {
		s += v * v
	}
	return math.Sqrt(s / float64(len(x)))
}
