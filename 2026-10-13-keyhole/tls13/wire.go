package tls13

import "errors"

// builder is a tiny length-prefix-aware byte writer for TLS presentation language.
type builder struct{ b []byte }

func (b *builder) u8(v uint8)   { b.b = append(b.b, v) }
func (b *builder) u16(v uint16) { b.b = append(b.b, byte(v>>8), byte(v)) }
func (b *builder) u24(v uint32) { b.b = append(b.b, byte(v>>16), byte(v>>8), byte(v)) }
func (b *builder) u32(v uint32) { b.b = append(b.b, byte(v>>24), byte(v>>16), byte(v>>8), byte(v)) }
func (b *builder) raw(p []byte) { b.b = append(b.b, p...) }

func (b *builder) vec(width int, f func(*builder)) {
	start := len(b.b)
	b.b = append(b.b, make([]byte, width)...)
	f(b)
	n := len(b.b) - start - width
	switch width {
	case 1:
		b.b[start] = byte(n)
	case 2:
		b.b[start], b.b[start+1] = byte(n>>8), byte(n)
	case 3:
		b.b[start], b.b[start+1], b.b[start+2] = byte(n>>16), byte(n>>8), byte(n)
	}
}
func (b *builder) vec8(f func(*builder))  { b.vec(1, f) }
func (b *builder) vec16(f func(*builder)) { b.vec(2, f) }
func (b *builder) vec24(f func(*builder)) { b.vec(3, f) }

var errShort = errors.New("tls13: truncated or malformed structure")

// parser reads big-endian TLS structures with a sticky error: after the first
// underflow every read returns zero values and ok() reports false.
type parser struct {
	b   []byte
	bad bool
}

func newParser(b []byte) *parser { return &parser{b: b} }

func (p *parser) ok() bool    { return !p.bad }
func (p *parser) empty() bool { return len(p.b) == 0 }
func (p *parser) left() int   { return len(p.b) }

func (p *parser) take(n int) []byte {
	if p.bad || n < 0 || n > len(p.b) {
		p.bad = true
		return nil
	}
	r := p.b[:n:n]
	p.b = p.b[n:]
	return r
}
func (p *parser) u8() uint8 {
	s := p.take(1)
	if s == nil {
		return 0
	}
	return s[0]
}
func (p *parser) u16() uint16 {
	s := p.take(2)
	if s == nil {
		return 0
	}
	return uint16(s[0])<<8 | uint16(s[1])
}
func (p *parser) u24() uint32 {
	s := p.take(3)
	if s == nil {
		return 0
	}
	return uint32(s[0])<<16 | uint32(s[1])<<8 | uint32(s[2])
}
func (p *parser) u32() uint32 {
	s := p.take(4)
	if s == nil {
		return 0
	}
	return uint32(s[0])<<24 | uint32(s[1])<<16 | uint32(s[2])<<8 | uint32(s[3])
}
func (p *parser) bytes(n int) []byte { return p.take(n) }

// sub returns a parser over a length-prefixed vector.
func (p *parser) sub(width int) *parser {
	var n int
	switch width {
	case 1:
		n = int(p.u8())
	case 2:
		n = int(p.u16())
	case 3:
		n = int(p.u24())
	}
	s := p.take(n)
	if s == nil && !p.bad {
		s = []byte{}
	}
	return &parser{b: s, bad: p.bad}
}
func (p *parser) sub8() *parser  { return p.sub(1) }
func (p *parser) sub16() *parser { return p.sub(2) }
func (p *parser) sub24() *parser { return p.sub(3) }

// vecBytes reads a length-prefixed opaque vector.
func (p *parser) vecBytes(width int) []byte {
	s := p.sub(width)
	if !s.ok() {
		p.bad = true
		return nil
	}
	if s.b == nil {
		return []byte{}
	}
	return s.b
}
