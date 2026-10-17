// Package bitio provides LSB-first bit streams (the DEFLATE bit order).
package bitio

import "errors"

// ErrEOF is returned when a reader runs out of input.
var ErrEOF = errors.New("bitio: unexpected end of data")

// Writer packs bits least-significant first.
type Writer struct {
	buf  []byte
	acc  uint64
	nacc uint
}

// WriteBits writes the low n bits (n <= 32) of v.
func (w *Writer) WriteBits(v uint32, n uint) {
	w.acc |= uint64(v) << w.nacc
	w.nacc += n
	for w.nacc >= 8 {
		w.buf = append(w.buf, byte(w.acc))
		w.acc >>= 8
		w.nacc -= 8
	}
}

// WriteBitsRev writes the low n bits of v with the most significant of them first
// (how Huffman codes are packed in DEFLATE).
func (w *Writer) WriteBitsRev(v uint32, n uint) {
	var r uint32
	for i := uint(0); i < n; i++ {
		r = r<<1 | v>>i&1
	}
	w.WriteBits(r, n)
}

// Align pads with zero bits to a byte boundary.
func (w *Writer) Align() {
	if w.nacc > 0 {
		w.WriteBits(0, 8-w.nacc)
	}
}

// WriteBytes appends raw bytes; the writer must be byte aligned.
func (w *Writer) WriteBytes(p []byte) {
	if w.nacc != 0 {
		panic("bitio: WriteBytes on unaligned writer")
	}
	w.buf = append(w.buf, p...)
}

// Bytes aligns and returns everything written.
func (w *Writer) Bytes() []byte { w.Align(); return w.buf }

// Len is the number of whole bytes written so far plus pending bits rounded up.
func (w *Writer) Len() int { return len(w.buf) + int((w.nacc+7)/8) }

// Reader unpacks bits least-significant first.
type Reader struct {
	data []byte
	pos  int
	acc  uint64
	nacc uint
}

// NewReader reads from data.
func NewReader(data []byte) *Reader { return &Reader{data: data} }

func (r *Reader) fill(n uint) {
	for r.nacc < n && r.pos < len(r.data) {
		r.acc |= uint64(r.data[r.pos]) << r.nacc
		r.pos++
		r.nacc += 8
	}
}

// ReadBits reads n bits (n <= 32).
func (r *Reader) ReadBits(n uint) (uint32, error) {
	if n == 0 {
		return 0, nil
	}
	r.fill(n)
	if r.nacc < n {
		return 0, ErrEOF
	}
	v := uint32(r.acc & (1<<n - 1))
	r.acc >>= n
	r.nacc -= n
	return v, nil
}

// PeekBits returns up to n bits without consuming; missing bits read as zero.
// The second result is how many real bits were available (<= n).
func (r *Reader) PeekBits(n uint) (uint32, uint) {
	r.fill(n)
	avail := r.nacc
	if avail > n {
		avail = n
	}
	return uint32(r.acc & (1<<n - 1)), avail
}

// Skip discards n bits previously peeked.
func (r *Reader) Skip(n uint) { r.acc >>= n; r.nacc -= n }

// Align discards bits up to the next byte boundary.
func (r *Reader) Align() {
	drop := r.nacc % 8
	r.acc >>= drop
	r.nacc -= drop
}

// ReadBytes reads n raw bytes from an aligned reader.
func (r *Reader) ReadBytes(n int) ([]byte, error) {
	r.Align()
	out := make([]byte, 0, n)
	for r.nacc > 0 && len(out) < n {
		out = append(out, byte(r.acc))
		r.acc >>= 8
		r.nacc -= 8
	}
	need := n - len(out)
	if need > len(r.data)-r.pos {
		return nil, ErrEOF
	}
	out = append(out, r.data[r.pos:r.pos+need]...)
	r.pos += need
	return out, nil
}

// BytePos is the index of the next unread whole byte (after Align, accounting for buffered bytes).
func (r *Reader) BytePos() int { return r.pos - int(r.nacc/8) }
