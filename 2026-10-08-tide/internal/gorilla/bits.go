package gorilla

import "errors"

// bitWriter appends bits MSB-first to a byte slice.
type bitWriter struct {
	buf  []byte
	free uint8 // unused low bits in the last byte
}

func (w *bitWriter) writeBit(b bool) {
	if w.free == 0 {
		w.buf = append(w.buf, 0)
		w.free = 8
	}
	if b {
		w.buf[len(w.buf)-1] |= 1 << (w.free - 1)
	}
	w.free--
}

// writeBits writes the low n bits of v (n in 0..64), most significant first.
func (w *bitWriter) writeBits(v uint64, n int) {
	for i := n - 1; i >= 0; i-- {
		w.writeBit(v>>uint(i)&1 == 1)
	}
}

var errEOF = errors.New("gorilla: unexpected end of chunk")

// bitReader reads bits MSB-first.
type bitReader struct {
	buf []byte
	pos int // bit position
}

func (r *bitReader) readBit() (bool, error) {
	if r.pos >= len(r.buf)*8 {
		return false, errEOF
	}
	b := r.buf[r.pos>>3]>>(7-uint(r.pos&7))&1 == 1
	r.pos++
	return b, nil
}

func (r *bitReader) readBits(n int) (uint64, error) {
	if r.pos+n > len(r.buf)*8 {
		return 0, errEOF
	}
	var v uint64
	for i := 0; i < n; i++ {
		b, _ := r.readBit()
		v <<= 1
		if b {
			v |= 1
		}
	}
	return v, nil
}
