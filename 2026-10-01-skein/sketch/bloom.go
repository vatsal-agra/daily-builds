package sketch

import (
	"errors"
	"fmt"
	"math"
	"math/bits"
)

// Bloom is a classic Bloom filter sized from (expected items, target FP rate)
// with Kirsch–Mitzenmacher double hashing.
type Bloom struct {
	m, k uint64
	n    uint64 // insertions (not distinct)
	bits []uint64
}

func NewBloom(n int, fpRate float64) (*Bloom, error) {
	if n < 1 || !(fpRate > 0 && fpRate < 1) {
		return nil, fmt.Errorf("bloom: need n>=1 and 0<fp<1, got %d, %v", n, fpRate)
	}
	m := math.Ceil(-float64(n) * math.Log(fpRate) / (math.Ln2 * math.Ln2))
	if m > 1<<36 {
		return nil, errors.New("bloom: requested filter too large")
	}
	k := math.Max(1, math.Round(m/float64(n)*math.Ln2))
	return NewBloomRaw(uint64(m), uint64(k))
}

func NewBloomRaw(m, k uint64) (*Bloom, error) {
	if m < 8 || k < 1 || k > 64 || m > 1<<36 {
		return nil, fmt.Errorf("bloom: bad m=%d k=%d", m, k)
	}
	return &Bloom{m: m, k: k, bits: make([]uint64, (m+63)/64)}, nil
}

func (b *Bloom) Bits() uint64  { return b.m }
func (b *Bloom) K() int        { return int(b.k) }
func (b *Bloom) Bytes() int    { return len(b.bits) * 8 }
func (b *Bloom) Added() uint64 { return b.n }

func (b *Bloom) Add(key []byte) {
	h1, h2 := pair(key)
	for i := uint64(0); i < b.k; i++ {
		p := (h1 + i*h2) % b.m
		b.bits[p>>6] |= 1 << (p & 63)
	}
	b.n++
}

func (b *Bloom) Contains(key []byte) bool {
	h1, h2 := pair(key)
	for i := uint64(0); i < b.k; i++ {
		p := (h1 + i*h2) % b.m
		if b.bits[p>>6]&(1<<(p&63)) == 0 {
			return false
		}
	}
	return true
}

func (b *Bloom) ones() uint64 {
	var c uint64
	for _, w := range b.bits {
		c += uint64(bits.OnesCount64(w))
	}
	return c
}

// FillRatio is the fraction of set bits.
func (b *Bloom) FillRatio() float64 { return float64(b.ones()) / float64(b.m) }

// EstimateCount infers the number of distinct inserted items from the fill ratio
// (Swamidass & Baldi): n ≈ -(m/k) ln(1 - X/m).
func (b *Bloom) EstimateCount() float64 {
	x := float64(b.ones())
	if x >= float64(b.m) {
		return math.Inf(1)
	}
	return -float64(b.m) / float64(b.k) * math.Log(1-x/float64(b.m))
}

// FalsePositiveRate is the current expected FP probability, from the fill ratio.
func (b *Bloom) FalsePositiveRate() float64 {
	return math.Pow(b.FillRatio(), float64(b.k))
}

// Merge unions o into b; both must share m and k.
func (b *Bloom) Merge(o *Bloom) error {
	if b.m != o.m || b.k != o.k {
		return errors.New("bloom: cannot merge filters with different geometry")
	}
	for i := range b.bits {
		b.bits[i] |= o.bits[i]
	}
	b.n += o.n
	return nil
}
