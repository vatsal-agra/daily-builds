package cm

// Binary arithmetic coder, 32-bit carry-less (as in lpaq). Probabilities are P(bit=1) in 1..65535.

type encoder struct {
	x1, x2 uint32
	out    []byte
}

func newEncoder() *encoder { return &encoder{x2: 0xffffffff} }

func split(x1, x2 uint32, p uint32) uint32 {
	r := x2 - x1
	return x1 + r>>16*p + (r&0xffff)*p>>16
}

func (e *encoder) encode(bit int, p uint32) {
	xm := split(e.x1, e.x2, p)
	if bit == 1 {
		e.x2 = xm
	} else {
		e.x1 = xm + 1
	}
	for (e.x1^e.x2)&0xff000000 == 0 {
		e.out = append(e.out, byte(e.x2>>24))
		e.x1 <<= 8
		e.x2 = e.x2<<8 | 255
	}
}

func (e *encoder) finish() []byte {
	// flush enough bytes to pin the final interval
	e.out = append(e.out, byte(e.x1>>24), byte(e.x1>>16), byte(e.x1>>8), byte(e.x1))
	return e.out
}

type decoder struct {
	x1, x2, x uint32
	in        []byte
	pos       int
}

func newDecoder(in []byte) *decoder {
	d := &decoder{x2: 0xffffffff, in: in}
	for i := 0; i < 4; i++ {
		d.x = d.x<<8 | uint32(d.next())
	}
	return d
}

func (d *decoder) next() byte {
	if d.pos < len(d.in) {
		b := d.in[d.pos]
		d.pos++
		return b
	}
	d.pos++
	return 0
}

func (d *decoder) decode(p uint32) int {
	xm := split(d.x1, d.x2, p)
	var bit int
	if d.x <= xm {
		bit = 1
		d.x2 = xm
	} else {
		d.x1 = xm + 1
	}
	for (d.x1^d.x2)&0xff000000 == 0 {
		d.x1 <<= 8
		d.x2 = d.x2<<8 | 255
		d.x = d.x<<8 | uint32(d.next())
	}
	return bit
}

// overrun reports whether the decoder consumed more than a few bytes past the end.
func (d *decoder) overrun() bool { return d.pos > len(d.in)+8 }
