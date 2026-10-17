package cm

import (
	"errors"
	"math"
)

// ErrCorrupt reports a stream that cannot be a valid cm encoding.
var ErrCorrupt = errors.New("cm: corrupt stream")

// Encode compresses src. The length is not stored; the caller must supply it to Decode.
func Encode(src []byte) []byte {
	m := NewModel(len(src))
	e := newEncoder()
	for _, b := range src {
		for i := 7; i >= 0; i-- {
			bit := int(b>>uint(i)) & 1
			e.encode(bit, m.P())
			m.Update(bit)
		}
	}
	return e.finish()
}

// Decode reverses Encode, producing exactly n bytes.
func Decode(data []byte, n int) ([]byte, error) {
	m := NewModel(n)
	d := newDecoder(data)
	out := make([]byte, n)
	for k := range out {
		c := 0
		for i := 0; i < 8; i++ {
			bit := d.decode(m.P())
			m.Update(bit)
			c = c<<1 | bit
		}
		out[k] = byte(c)
		if d.overrun() {
			return nil, ErrCorrupt
		}
	}
	return out, nil
}

// Costs runs the model over src and reports the information content, in bits, that the
// model assigned to every byte (the exact amount an ideal arithmetic coder would spend).
func Costs(src []byte) []float32 {
	m := NewModel(len(src))
	out := make([]float32, len(src))
	for k, b := range src {
		var bits float64
		for i := 7; i >= 0; i-- {
			bit := int(b>>uint(i)) & 1
			p := float64(m.P()) / 65536
			if bit == 0 {
				p = 1 - p
			}
			bits -= math.Log2(p)
			m.Update(bit)
		}
		out[k] = float32(bits)
	}
	return out
}
