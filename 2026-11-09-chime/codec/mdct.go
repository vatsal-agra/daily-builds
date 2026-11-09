package codec

import (
	"math"
	"math/cmplx"
)

// fftPlan is an iterative radix-2 complex FFT of fixed power-of-two size.
type fftPlan struct {
	n   int
	rev []int
	tw  []complex128
}

func newFFT(n int) *fftPlan {
	p := &fftPlan{n: n, rev: make([]int, n), tw: make([]complex128, n/2)}
	lg := 0
	for 1<<lg < n {
		lg++
	}
	for i := 0; i < n; i++ {
		r := 0
		for b := 0; b < lg; b++ {
			if i>>b&1 == 1 {
				r |= 1 << (lg - 1 - b)
			}
		}
		p.rev[i] = r
	}
	for i := range p.tw {
		p.tw[i] = cmplx.Exp(complex(0, -2*math.Pi*float64(i)/float64(n)))
	}
	return p
}

func (p *fftPlan) transform(x []complex128) {
	n := p.n
	for i := 0; i < n; i++ {
		if j := p.rev[i]; j > i {
			x[i], x[j] = x[j], x[i]
		}
	}
	for size := 2; size <= n; size <<= 1 {
		half := size / 2
		step := n / size
		for s := 0; s < n; s += size {
			for k := 0; k < half; k++ {
				t := x[s+k+half] * p.tw[k*step]
				x[s+k+half] = x[s+k] - t
				x[s+k] += t
			}
		}
	}
}

// MDCT computes a size-M (2M inputs → M coefficients) orthonormal MDCT using
// an M/2-point complex FFT (the classic DCT-IV via half-size FFT algorithm).
type MDCT struct {
	M     int
	fft   *fftPlan
	twid  []complex128
	post  []complex128
	buf   []complex128
	u     []float64
	scale float64
}

func NewMDCT(m int) *MDCT {
	t := &MDCT{M: m, fft: newFFT(m / 2), twid: make([]complex128, m/2), post: make([]complex128, m/2),
		buf: make([]complex128, m/2), u: make([]float64, m), scale: math.Sqrt(2 / float64(m))}
	for n := range t.twid {
		t.twid[n] = cmplx.Exp(complex(0, -math.Pi*float64(4*n+1)/float64(4*m)))
		t.post[n] = cmplx.Exp(complex(0, -math.Pi*float64(n)/float64(m)))
	}
	return t
}

// dct4 computes out[k] = scale * Σ in[m] cos(π/M (m+½)(k+½)).
func (t *MDCT) dct4(in, out []float64) {
	m := t.M
	h := m / 2
	for n := 0; n < h; n++ {
		t.buf[n] = complex(in[2*n], in[m-1-2*n]) * t.twid[n]
	}
	t.fft.transform(t.buf)
	for k := 0; k < h; k++ {
		y := t.buf[k] * t.post[k]
		out[2*k] = real(y) * t.scale
		out[m-1-2*k] = -imag(y) * t.scale
	}
}

// Forward: x has 2M (already windowed) samples, out has M coefficients.
func (t *MDCT) Forward(x, out []float64) {
	m := t.M
	h := m / 2
	u := t.u
	for i := range u {
		u[i] = 0
	}
	for n := 0; n < h; n++ {
		u[n+h] += x[n]
	}
	for n := h; n < 3*h; n++ {
		u[3*h-1-n] -= x[n]
	}
	for n := 3 * h; n < 2*m; n++ {
		u[n-3*h] -= x[n]
	}
	t.dct4(u, out)
}

// Inverse: X has M coefficients, out has 2M time-aliased samples (not yet windowed).
func (t *MDCT) Inverse(X, out []float64) {
	m := t.M
	h := m / 2
	y := t.u
	t.dct4(X, y)
	for n := 0; n < h; n++ {
		out[n] = y[n+h]
	}
	for n := h; n < 3*h; n++ {
		out[n] = -y[3*h-1-n]
	}
	for n := 3 * h; n < 2*m; n++ {
		out[n] = -y[n-3*h]
	}
}
