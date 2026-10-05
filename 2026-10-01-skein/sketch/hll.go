package sketch

import (
	"errors"
	"fmt"
	"math"
	"math/bits"
)

// HLL is a HyperLogLog cardinality sketch using Ertl's improved estimator
// ("New cardinality estimation algorithms for HyperLogLog sketches", 2017),
// which needs no empirical bias tables and is accurate across the full range.
type HLL struct {
	p    uint8
	regs []uint8
}

// NewHLL creates a sketch with 2^p registers (p in 4..18). Standard error ≈ 1.04/sqrt(2^p).
func NewHLL(p int) (*HLL, error) {
	if p < 4 || p > 18 {
		return nil, fmt.Errorf("hll: precision %d out of range 4..18", p)
	}
	return &HLL{p: uint8(p), regs: make([]uint8, 1<<uint(p))}, nil
}

func (h *HLL) Precision() int { return int(h.p) }

// StdError is the theoretical relative standard error.
func (h *HLL) StdError() float64 { return 1.04 / math.Sqrt(float64(len(h.regs))) }

// Bytes is the sketch's register memory.
func (h *HLL) Bytes() int { return len(h.regs) }

func (h *HLL) Add(b []byte)       { h.AddHash(Hash64(b, 0)) }
func (h *HLL) AddString(s string) { h.Add([]byte(s)) }

// AddHash inserts a pre-hashed element.
func (h *HLL) AddHash(x uint64) {
	idx := x >> (64 - h.p)
	// rank = position of leftmost 1 in the remaining bits (1-based), capped at q+1.
	w := x<<h.p | (1 << (h.p - 1))
	r := uint8(bits.LeadingZeros64(w)) + 1
	if r > h.regs[idx] {
		h.regs[idx] = r
	}
}

func sigma(x float64) float64 {
	if x == 1 {
		return math.Inf(1)
	}
	y := 1.0
	z := x
	for {
		x *= x
		zOld := z
		z += x * y
		y += y
		if z == zOld {
			return z
		}
	}
}

func tau(x float64) float64 {
	if x == 0 || x == 1 {
		return 0
	}
	y := 1.0
	z := 1 - x
	for {
		x = math.Sqrt(x)
		zOld := z
		y *= 0.5
		z -= (1 - x) * (1 - x) * y
		if z == zOld {
			return z / 3
		}
	}
}

// Estimate returns the estimated number of distinct elements.
func (h *HLL) Estimate() float64 {
	m := float64(len(h.regs))
	q := 64 - int(h.p)
	c := make([]float64, q+2)
	for _, r := range h.regs {
		c[r]++
	}
	z := m * tau(1-c[q+1]/m)
	for k := q; k >= 1; k-- {
		z = 0.5 * (z + c[k])
	}
	z += m * sigma(c[0]/m)
	if math.IsInf(z, 1) {
		return 0
	}
	return m * m / (2 * math.Ln2 * z)
}

// Merge folds o into h (register-wise max). Precisions must match.
func (h *HLL) Merge(o *HLL) error {
	if h.p != o.p {
		return errors.New("hll: cannot merge different precisions")
	}
	for i, r := range o.regs {
		if r > h.regs[i] {
			h.regs[i] = r
		}
	}
	return nil
}

func (h *HLL) Clone() *HLL {
	c := &HLL{p: h.p, regs: make([]uint8, len(h.regs))}
	copy(c.regs, h.regs)
	return c
}

// Intersect estimates |A ∩ B| by inclusion–exclusion (noisy when overlap is small).
func HLLIntersect(a, b *HLL) (float64, error) {
	u := a.Clone()
	if err := u.Merge(b); err != nil {
		return 0, err
	}
	v := a.Estimate() + b.Estimate() - u.Estimate()
	if v < 0 {
		v = 0
	}
	return v, nil
}
