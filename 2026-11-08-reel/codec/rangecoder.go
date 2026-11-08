package codec

import "errors"

// Ctx is an adaptive binary probability model: the mean of a fast and a slow
// exponentially-decaying estimate of P(bit==0), 16-bit scale.
type Ctx struct{ a, b uint16 }

// NewCtx returns a model initialised to P(0)=0.5.
func NewCtx() Ctx { return Ctx{1 << 15, 1 << 15} }

func (c *Ctx) p12() uint32 {
	p := (uint32(c.a) + uint32(c.b)) >> 5 // 12 bit
	if p < 1 {
		p = 1
	} else if p > 4095 {
		p = 4095
	}
	return p
}

func (c *Ctx) update(bit int) {
	if bit == 0 {
		c.a += (65535 - c.a) >> 4
		c.b += (65535 - c.b) >> 7
	} else {
		c.a -= c.a >> 4
		c.b -= c.b >> 7
	}
}

// bitIO is the symmetric interface the syntax code is written against. An
// encoder implementation writes v and returns it; a decoder implementation
// ignores v and returns the decoded value. This is what makes encoder and
// decoder grammar-identical by construction.
type bitIO interface {
	bit(c *Ctx, v int) int
	bypass(v int) int
	err() error
	decoding() bool
}

// ---------------------------------------------------------------- encoder

type rcEnc struct {
	low       uint64
	rng       uint32
	cache     byte
	cacheSize int64
	out       []byte
}

func newRCEnc() *rcEnc { return &rcEnc{rng: 0xFFFFFFFF, cacheSize: 1} }

func (e *rcEnc) shiftLow() {
	if uint32(e.low) < 0xFF000000 || (e.low>>32) != 0 {
		carry := byte(e.low >> 32)
		temp := e.cache
		for {
			e.out = append(e.out, temp+carry)
			temp = 0xFF
			e.cacheSize--
			if e.cacheSize == 0 {
				break
			}
		}
		e.cache = byte(uint32(e.low) >> 24)
	}
	e.cacheSize++
	e.low = uint64(uint32(e.low) << 8)
}

func (e *rcEnc) bit(c *Ctx, v int) int {
	bound := (e.rng >> 12) * c.p12()
	if v == 0 {
		e.rng = bound
	} else {
		e.low += uint64(bound)
		e.rng -= bound
	}
	c.update(v)
	for e.rng < 1<<24 {
		e.rng <<= 8
		e.shiftLow()
	}
	return v
}

func (e *rcEnc) bypass(v int) int {
	e.rng >>= 1
	if v != 0 {
		e.low += uint64(e.rng)
	}
	for e.rng < 1<<24 {
		e.rng <<= 8
		e.shiftLow()
	}
	return v
}

func (e *rcEnc) err() error     { return nil }
func (e *rcEnc) decoding() bool { return false }

func (e *rcEnc) finish() []byte {
	for i := 0; i < 5; i++ {
		e.shiftLow()
	}
	// first byte emitted is always the initial zero cache; drop it.
	return e.out[1:]
}

// bits written so far, fractional-free estimate (used by rate control only).
func (e *rcEnc) size() int { return len(e.out) }

// ---------------------------------------------------------------- decoder

var errTruncated = errors.New("reel: truncated or corrupt range-coded data")

type rcDec struct {
	data  []byte
	pos   int
	rng   uint32
	code  uint32
	over  int // bytes read past end
	fault error
}

func newRCDec(data []byte) *rcDec {
	d := &rcDec{data: data, rng: 0xFFFFFFFF}
	for i := 0; i < 4; i++ {
		d.code = d.code<<8 | uint32(d.next())
	}
	return d
}

func (d *rcDec) next() byte {
	if d.pos < len(d.data) {
		b := d.data[d.pos]
		d.pos++
		return b
	}
	d.over++
	// Tolerate the few implicit trailing bytes the encoder flush may omit,
	// but a stream that keeps demanding data is corrupt.
	if d.over > 8 {
		d.fault = errTruncated
	}
	return 0
}

func (d *rcDec) bit(c *Ctx, _ int) int {
	bound := (d.rng >> 12) * c.p12()
	var v int
	if d.code < bound {
		d.rng = bound
	} else {
		d.code -= bound
		d.rng -= bound
		v = 1
	}
	c.update(v)
	for d.rng < 1<<24 {
		d.rng <<= 8
		d.code = d.code<<8 | uint32(d.next())
	}
	return v
}

func (d *rcDec) bypass(_ int) int {
	d.rng >>= 1
	var v int
	if d.code >= d.rng {
		d.code -= d.rng
		v = 1
	}
	for d.rng < 1<<24 {
		d.rng <<= 8
		d.code = d.code<<8 | uint32(d.next())
	}
	return v
}

func (d *rcDec) err() error     { return d.fault }
func (d *rcDec) decoding() bool { return true }

// ---------------------------------------------------------------- helpers

// codeEG codes a non-negative integer with an order-k Exp-Golomb code using
// bypass bins, bounded so corrupt streams cannot loop forever.
func codeEG(io bitIO, v, k int) int {
	if !io.decoding() {
		v += 1 << k
		n := 0
		for (v >> (n + 1)) != 0 {
			n++
		}
		for i := k; i < n; i++ {
			io.bypass(1)
		}
		io.bypass(0)
		for i := n - 1; i >= 0; i-- {
			io.bypass((v >> i) & 1)
		}
		return v - (1 << k)
	}
	n := k
	for io.bypass(0) == 1 {
		n++
		if n > 24 || io.err() != nil {
			return 0
		}
	}
	x := 1
	for i := 0; i < n; i++ {
		x = x<<1 | io.bypass(0)
	}
	return x - (1 << k)
}
