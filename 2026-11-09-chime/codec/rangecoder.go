package codec

import (
	"errors"
	"math"
)

// Adaptive binary range coder (LZMA style carry handling) with two-rate
// probability estimators. One symmetric type serves as encoder and decoder so
// the bitstream syntax is written exactly once.

const (
	probBits = 15
	probOne  = 1 << probBits
	topValue = 1 << 24
)

// Prob is an adaptive probability of a 0 bit: the average of a fast and a slow estimator.
type Prob struct{ fast, slow uint16 }

func NewProb() Prob { return Prob{probOne / 2, probOne / 2} }

func (p *Prob) p0() uint32 {
	v := (uint32(p.fast) + uint32(p.slow)) >> 1
	if v < 64 {
		v = 64
	} else if v > probOne-64 {
		v = probOne - 64
	}
	return v
}

func (p *Prob) update(bit int) {
	if bit == 0 {
		p.fast += (probOne - p.fast) >> 4
		p.slow += (probOne - p.slow) >> 7
	} else {
		p.fast -= p.fast >> 4
		p.slow -= p.slow >> 7
	}
}

// RC is a symmetric range coder. In encode mode Bit writes its argument; in
// decode mode it ignores the argument and returns the decoded bit.
type RC struct {
	dec bool
	// encoder
	low       uint64
	rng       uint32
	cache     byte
	cacheSize int64
	out       []byte
	// decoder
	in   []byte
	pos  int
	code uint32
	over int // bytes read beyond end
	Err  error
	// optional ideal-cost accounting (encode mode)
	Track bool
	Cost  float64 // bits
}

func NewEncoder() *RC {
	return &RC{rng: 0xFFFFFFFF, cacheSize: 1}
}

func NewDecoder(in []byte) *RC {
	r := &RC{dec: true, rng: 0xFFFFFFFF, in: in}
	for i := 0; i < 5; i++ {
		r.code = r.code<<8 | uint32(r.next())
	}
	return r
}

func (r *RC) Decoding() bool { return r.dec }

func (r *RC) next() byte {
	if r.pos < len(r.in) {
		b := r.in[r.pos]
		r.pos++
		return b
	}
	r.over++
	if r.over > 8 && r.Err == nil {
		r.Err = errors.New("range decoder: unexpected end of data")
	}
	return 0
}

func (r *RC) shiftLow() {
	if uint32(r.low) < 0xFF000000 || (r.low>>32) != 0 {
		carry := byte(r.low >> 32)
		temp := r.cache
		for {
			r.out = append(r.out, temp+carry)
			temp = 0xFF
			r.cacheSize--
			if r.cacheSize == 0 {
				break
			}
		}
		r.cache = byte(uint32(r.low) >> 24)
	}
	r.cacheSize++
	r.low = uint64(uint32(r.low) << 8)
}

// Bit codes one modelled bit.
func (r *RC) Bit(p *Prob, bit int) int {
	bound := (r.rng >> probBits) * p.p0()
	if !r.dec {
		if r.Track {
			if bit == 0 {
				r.Cost -= math.Log2(float64(p.p0()) / probOne)
			} else {
				r.Cost -= math.Log2(1 - float64(p.p0())/probOne)
			}
		}
		if bit == 0 {
			r.rng = bound
		} else {
			r.low += uint64(bound)
			r.rng -= bound
		}
		p.update(bit)
		for r.rng < topValue {
			r.rng <<= 8
			r.shiftLow()
		}
		return bit
	}
	if r.code < bound {
		r.rng = bound
		bit = 0
	} else {
		r.code -= bound
		r.rng -= bound
		bit = 1
	}
	p.update(bit)
	for r.rng < topValue {
		r.rng <<= 8
		r.code = r.code<<8 | uint32(r.next())
	}
	return bit
}

// Bypass codes one equiprobable bit.
func (r *RC) Bypass(bit int) int {
	if !r.dec {
		if r.Track {
			r.Cost++
		}
		r.rng >>= 1
		if bit != 0 {
			r.low += uint64(r.rng)
		}
		for r.rng < topValue {
			r.rng <<= 8
			r.shiftLow()
		}
		return bit
	}
	r.rng >>= 1
	if r.code >= r.rng {
		r.code -= r.rng
		bit = 1
	} else {
		bit = 0
	}
	for r.rng < topValue {
		r.rng <<= 8
		r.code = r.code<<8 | uint32(r.next())
	}
	return bit
}

// Finish flushes the encoder and returns the byte stream.
func (r *RC) Finish() []byte {
	for i := 0; i < 5; i++ {
		r.shiftLow()
	}
	return r.out
}

// Size is the approximate number of bytes produced so far.
func (r *RC) Size() int { return len(r.out) + int(r.cacheSize) }

// Bypass multi-bit helper (MSB first).
func (r *RC) Bits(v uint32, n int) uint32 {
	var o uint32
	for i := n - 1; i >= 0; i-- {
		o = o<<1 | uint32(r.Bypass(int(v>>uint(i))&1))
	}
	return o
}

// ExpGolomb codes a non-negative integer (order 0) with bypass bits; returns it.
// In decode mode the prefix is capped at 30 to bound hostile input.
func (r *RC) ExpGolomb(v uint32) uint32 {
	if !r.dec {
		x := v + 1
		n := 0
		for x>>uint(n+1) != 0 {
			n++
		}
		for i := 0; i < n; i++ {
			r.Bypass(1)
		}
		r.Bypass(0)
		r.Bits(x&((1<<uint(n))-1), n)
		return v
	}
	n := 0
	for n < 30 && r.Bypass(0) == 1 {
		n++
		if r.Err != nil {
			return 0
		}
	}
	low := r.Bits(0, n)
	return (1<<uint(n) | low) - 1
}
