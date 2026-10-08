// Package gorilla implements the Facebook "Gorilla" time-series compression
// scheme (VLDB 2015): timestamps as delta-of-delta with variable-width
// buckets, float64 values as XOR against the previous value storing only the
// meaningful bits.
//
// Chunk layout: [2-byte big-endian sample count][bitstream].
package gorilla

import (
	"encoding/binary"
	"errors"
	"math"
	"math/bits"
)

// MaxSamples is the conventional chunk size used by the store.
const MaxSamples = 120

// Encoder incrementally compresses (timestamp ms, value) pairs.
// Timestamps must be strictly increasing.
type Encoder struct {
	w        bitWriter
	n        uint16
	t        int64
	tDelta   int64
	v        uint64
	leading  uint8
	trailing uint8
}

func NewEncoder() *Encoder { return &Encoder{leading: 0xff} }

// Len returns the number of samples appended.
func (e *Encoder) Len() int { return int(e.n) }

// LastT returns the last appended timestamp.
func (e *Encoder) LastT() int64 { return e.t }

var ErrOutOfOrder = errors.New("gorilla: timestamp not after previous sample")
var ErrFull = errors.New("gorilla: chunk full")

func (e *Encoder) Append(t int64, v float64) error {
	if e.n == math.MaxUint16 {
		return ErrFull
	}
	vb := math.Float64bits(v)
	switch e.n {
	case 0:
		e.w.writeBits(uint64(t), 64)
		e.w.writeBits(vb, 64)
	case 1:
		if t <= e.t {
			return ErrOutOfOrder
		}
		d := t - e.t
		for u := uint64(d); ; u >>= 7 { // uvarint, bytewise
			if u < 0x80 {
				e.w.writeBits(u, 8)
				break
			}
			e.w.writeBits(u&0x7f|0x80, 8)
		}
		e.tDelta = d
		e.writeValue(vb)
	default:
		if t <= e.t {
			return ErrOutOfOrder
		}
		d := t - e.t
		e.writeDoD(d - e.tDelta)
		e.tDelta = d
		e.writeValue(vb)
	}
	e.t, e.v = t, vb
	e.n++
	return nil
}

func (e *Encoder) writeDoD(dod int64) {
	switch {
	case dod == 0:
		e.w.writeBit(false)
	case dod >= -63 && dod <= 64:
		e.w.writeBits(0b10, 2)
		e.w.writeBits(uint64(dod), 7)
	case dod >= -255 && dod <= 256:
		e.w.writeBits(0b110, 3)
		e.w.writeBits(uint64(dod), 9)
	case dod >= -2047 && dod <= 2048:
		e.w.writeBits(0b1110, 4)
		e.w.writeBits(uint64(dod), 12)
	default:
		e.w.writeBits(0b1111, 4)
		e.w.writeBits(uint64(dod), 64)
	}
}

func (e *Encoder) writeValue(vb uint64) {
	x := vb ^ e.v
	if x == 0 {
		e.w.writeBit(false)
		return
	}
	e.w.writeBit(true)
	lead := uint8(bits.LeadingZeros64(x))
	trail := uint8(bits.TrailingZeros64(x))
	if lead >= 32 {
		lead = 31 // 5 bits available
	}
	if e.leading != 0xff && lead >= e.leading && trail >= e.trailing {
		e.w.writeBit(false)
		e.w.writeBits(x>>e.trailing, 64-int(e.leading)-int(e.trailing))
		return
	}
	e.leading, e.trailing = lead, trail
	e.w.writeBit(true)
	e.w.writeBits(uint64(lead), 5)
	sig := 64 - int(lead) - int(trail)
	e.w.writeBits(uint64(sig), 6) // 64 wraps to 0, decoded back as 64
	e.w.writeBits(x>>trail, sig)
}

// Bytes returns a snapshot of the chunk (header + bitstream). Safe to call
// while the encoder is still being appended to.
func (e *Encoder) Bytes() []byte {
	out := make([]byte, 2+len(e.w.buf))
	binary.BigEndian.PutUint16(out, e.n)
	copy(out[2:], e.w.buf)
	return out
}

// Iterator decodes a chunk.
type Iterator struct {
	r        bitReader
	total    uint16
	read     uint16
	t        int64
	tDelta   int64
	v        uint64
	leading  uint8
	trailing uint8
	err      error
}

// NewIterator decodes the chunk produced by Encoder.Bytes.
func NewIterator(chunk []byte) *Iterator {
	it := &Iterator{}
	if len(chunk) < 2 {
		it.err = errEOF
		return it
	}
	it.total = binary.BigEndian.Uint16(chunk)
	it.r = bitReader{buf: chunk[2:]}
	return it
}

// Count returns the number of samples declared in the chunk header.
func ChunkCount(chunk []byte) int {
	if len(chunk) < 2 {
		return 0
	}
	return int(binary.BigEndian.Uint16(chunk))
}

func (it *Iterator) Next() bool {
	if it.err != nil || it.read >= it.total {
		return false
	}
	switch it.read {
	case 0:
		t, err := it.r.readBits(64)
		if err != nil {
			return it.fail(err)
		}
		v, err := it.r.readBits(64)
		if err != nil {
			return it.fail(err)
		}
		it.t, it.v = int64(t), v
	case 1:
		var d uint64
		for shift := uint(0); ; shift += 7 {
			b, err := it.r.readBits(8)
			if err != nil || shift > 63 {
				return it.fail(errEOF)
			}
			d |= (b & 0x7f) << shift
			if b < 0x80 {
				break
			}
		}
		it.tDelta = int64(d)
		it.t += it.tDelta
		if !it.readValue() {
			return false
		}
	default:
		dod, err := it.readDoD()
		if err != nil {
			return it.fail(err)
		}
		it.tDelta += dod
		it.t += it.tDelta
		if !it.readValue() {
			return false
		}
	}
	it.read++
	return true
}

func (it *Iterator) fail(err error) bool { it.err = err; return false }

func (it *Iterator) readDoD() (int64, error) {
	var width int
	for i := 0; i < 4; i++ {
		b, err := it.r.readBit()
		if err != nil {
			return 0, err
		}
		if !b {
			break
		}
		width = i + 1
	}
	var n int
	switch width {
	case 0:
		return 0, nil
	case 1:
		n = 7
	case 2:
		n = 9
	case 3:
		n = 12
	default:
		n = 64
	}
	u, err := it.r.readBits(n)
	if err != nil {
		return 0, err
	}
	if n == 64 {
		return int64(u), nil
	}
	// Encoded range is [-(2^(n-1))+1, 2^(n-1)], so 2^(n-1) itself is positive.
	if u > 1<<uint(n-1) {
		return int64(u) - 1<<uint(n), nil
	}
	return int64(u), nil
}

func (it *Iterator) readValue() bool {
	b, err := it.r.readBit()
	if err != nil {
		return it.fail(err)
	}
	if !b {
		return true // same value
	}
	ctl, err := it.r.readBit()
	if err != nil {
		return it.fail(err)
	}
	if ctl {
		l, err := it.r.readBits(5)
		if err != nil {
			return it.fail(err)
		}
		s, err := it.r.readBits(6)
		if err != nil {
			return it.fail(err)
		}
		if s == 0 {
			s = 64
		}
		it.leading = uint8(l)
		it.trailing = uint8(64 - l - s)
		if int(l)+int(s) > 64 {
			return it.fail(errors.New("gorilla: corrupt value header"))
		}
	}
	sig := 64 - int(it.leading) - int(it.trailing)
	x, err := it.r.readBits(sig)
	if err != nil {
		return it.fail(err)
	}
	it.v ^= x << it.trailing
	return true
}

func (it *Iterator) At() (int64, float64) { return it.t, math.Float64frombits(it.v) }
func (it *Iterator) Err() error           { return it.err }
