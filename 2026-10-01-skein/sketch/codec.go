package sketch

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"math"
)

// Wire format:  "SKN1" | type(1) | uvarint payloadLen | payload | crc32-IEEE(LE) of all preceding bytes.
const magic = "SKN1"

const (
	tHLL byte = iota + 1
	tCMS
	tSS
	tBloom
	tCuckoo
	tTDigest
	tMinHash
	tBundle
)

var ErrCorrupt = errors.New("skein: corrupt or truncated data")

type wr struct{ bytes.Buffer }

func (w *wr) u(v uint64) { var b [10]byte; w.Write(b[:binary.PutUvarint(b[:], v)]) }
func (w *wr) f(v float64) {
	var b [8]byte
	binary.LittleEndian.PutUint64(b[:], math.Float64bits(v))
	w.Write(b[:])
}
func (w *wr) s(v string) { w.u(uint64(len(v))); w.WriteString(v) }

type rd struct {
	b   []byte
	err error
}

func (r *rd) fail() { r.err = ErrCorrupt; r.b = nil }
func (r *rd) u() uint64 {
	v, n := binary.Uvarint(r.b)
	if n <= 0 {
		r.fail()
		return 0
	}
	r.b = r.b[n:]
	return v
}
func (r *rd) f() float64 {
	if len(r.b) < 8 {
		r.fail()
		return 0
	}
	v := math.Float64frombits(binary.LittleEndian.Uint64(r.b))
	r.b = r.b[8:]
	return v
}
func (r *rd) raw(n uint64) []byte {
	if n > uint64(len(r.b)) {
		r.fail()
		return nil
	}
	v := r.b[:n]
	r.b = r.b[n:]
	return v
}
func (r *rd) s() string { return string(r.raw(r.u())) }

func frame(t byte, payload []byte) []byte {
	var w wr
	w.WriteString(magic)
	w.WriteByte(t)
	w.u(uint64(len(payload)))
	w.Write(payload)
	var c [4]byte
	binary.LittleEndian.PutUint32(c[:], crc32.ChecksumIEEE(w.Bytes()))
	w.Write(c[:])
	return w.Bytes()
}

// Marshal serialises any Skein sketch (*HLL, *CMS, *SpaceSaving, *Bloom,
// *Cuckoo, *TDigest, *MinHash, *Bundle).
func Marshal(v any) ([]byte, error) {
	var w wr
	var t byte
	switch x := v.(type) {
	case *HLL:
		t = tHLL
		w.WriteByte(x.p)
		w.Write(x.regs)
	case *CMS:
		t = tCMS
		w.u(uint64(x.w))
		w.u(uint64(x.d))
		w.u(x.total)
		var b [4]byte
		for _, c := range x.cells {
			binary.LittleEndian.PutUint32(b[:], c)
			w.Write(b[:])
		}
	case *SpaceSaving:
		t = tSS
		w.u(uint64(x.k))
		w.u(x.total)
		w.u(uint64(len(x.heap)))
		for _, e := range x.heap {
			w.s(e.Key)
			w.u(e.Count)
			w.u(e.Err)
		}
	case *Bloom:
		t = tBloom
		w.u(x.m)
		w.u(x.k)
		w.u(x.n)
		var b [8]byte
		for _, c := range x.bits {
			binary.LittleEndian.PutUint64(b[:], c)
			w.Write(b[:])
		}
	case *Cuckoo:
		t = tCuckoo
		w.u(x.nb)
		w.u(x.count)
		w.u(x.rng)
		var b [2]byte
		for _, c := range x.fp {
			binary.LittleEndian.PutUint16(b[:], c)
			w.Write(b[:])
		}
	case *TDigest:
		t = tTDigest
		x.flush()
		w.f(x.delta)
		w.f(x.n)
		w.f(x.min)
		w.f(x.max)
		w.u(uint64(len(x.cs)))
		for _, c := range x.cs {
			w.f(c.mean)
			w.f(c.weight)
		}
	case *MinHash:
		t = tMinHash
		if x.empty {
			w.WriteByte(1)
		} else {
			w.WriteByte(0)
		}
		w.u(uint64(len(x.sig)))
		var b [8]byte
		for _, c := range x.sig {
			binary.LittleEndian.PutUint64(b[:], c)
			w.Write(b[:])
		}
	case *Bundle:
		t = tBundle
		w.u(x.Records)
		for _, p := range []any{x.Distinct, x.Freq, x.Top, x.Dist} {
			b, err := Marshal(p)
			if err != nil {
				return nil, err
			}
			w.u(uint64(len(b)))
			w.Write(b)
		}
	default:
		return nil, fmt.Errorf("skein: cannot marshal %T", v)
	}
	return frame(t, w.Bytes()), nil
}

// Unmarshal decodes data produced by Marshal and returns the concrete sketch.
func Unmarshal(data []byte) (any, error) {
	if len(data) < len(magic)+1+1+4 || string(data[:4]) != magic {
		return nil, fmt.Errorf("skein: not a skein file (bad magic)")
	}
	body, sum := data[:len(data)-4], binary.LittleEndian.Uint32(data[len(data)-4:])
	if crc32.ChecksumIEEE(body) != sum {
		return nil, fmt.Errorf("%w: checksum mismatch", ErrCorrupt)
	}
	t := body[4]
	r := &rd{b: body[5:]}
	n := r.u()
	pl := r.raw(n)
	if r.err != nil || len(r.b) != 0 {
		return nil, ErrCorrupt
	}
	r = &rd{b: pl}
	var out any
	switch t {
	case tHLL:
		if len(pl) < 1 {
			return nil, ErrCorrupt
		}
		h, err := NewHLL(int(pl[0]))
		if err != nil || len(pl)-1 != len(h.regs) {
			return nil, ErrCorrupt
		}
		copy(h.regs, pl[1:])
		maxRank := uint8(64-h.p) + 1
		for _, v := range h.regs {
			if v > maxRank {
				return nil, fmt.Errorf("%w: register out of range", ErrCorrupt)
			}
		}
		out = h
	case tCMS:
		w, d, total := r.u(), r.u(), r.u()
		if r.err != nil || w < 1 || d < 1 || w > 1<<28 || d > 32 || uint64(len(r.b)) != w*d*4 {
			return nil, ErrCorrupt
		}
		c, _ := NewCMSDims(int(w), int(d))
		c.total = total
		for i := range c.cells {
			c.cells[i] = binary.LittleEndian.Uint32(r.b[i*4:])
		}
		out = c
	case tSS:
		k, total, cnt := r.u(), r.u(), r.u()
		if r.err != nil || k < 1 || k > 1<<24 || cnt > k {
			return nil, ErrCorrupt
		}
		s, _ := NewSpaceSaving(int(k))
		s.total = total
		for i := uint64(0); i < cnt; i++ {
			key, c, e := r.s(), r.u(), r.u()
			if r.err != nil {
				return nil, ErrCorrupt
			}
			if _, dup := s.idx[key]; dup || e > c {
				return nil, ErrCorrupt
			}
			s.heap = append(s.heap, &Entry{key, c, e})
			s.idx[key] = len(s.heap) - 1
		}
		if len(r.b) != 0 {
			return nil, ErrCorrupt
		}
		for i := len(s.heap)/2 - 1; i >= 0; i-- {
			s.down(i)
		}
		out = s
	case tBloom:
		m, k, n := r.u(), r.u(), r.u()
		if r.err != nil || m < 8 || m > 1<<36 || k < 1 || k > 64 || uint64(len(r.b)) != (m+63)/64*8 {
			return nil, ErrCorrupt
		}
		b, _ := NewBloomRaw(m, k)
		b.n = n
		for i := range b.bits {
			b.bits[i] = binary.LittleEndian.Uint64(r.b[i*8:])
		}
		out = b
	case tCuckoo:
		nb, cnt, rng := r.u(), r.u(), r.u()
		if r.err != nil || nb < 2 || nb&(nb-1) != 0 || nb > 1<<28 || uint64(len(r.b)) != nb*cuckooSlots*2 || rng == 0 {
			return nil, ErrCorrupt
		}
		c := &Cuckoo{nb: nb, count: cnt, rng: rng, fp: make([]uint16, nb*cuckooSlots)}
		var occ uint64
		for i := range c.fp {
			c.fp[i] = binary.LittleEndian.Uint16(r.b[i*2:])
			if c.fp[i] != 0 {
				occ++
			}
		}
		if occ != cnt {
			return nil, fmt.Errorf("%w: item count mismatch", ErrCorrupt)
		}
		out = c
	case tTDigest:
		delta, n, mn, mx := r.f(), r.f(), r.f(), r.f()
		cnt := r.u()
		if r.err != nil || cnt > 1<<24 || uint64(len(r.b)) != cnt*16 {
			return nil, ErrCorrupt
		}
		td, err := NewTDigest(delta)
		if err != nil {
			return nil, ErrCorrupt
		}
		td.n, td.min, td.max = n, mn, mx
		sum, prev := 0.0, math.Inf(-1)
		for i := uint64(0); i < cnt; i++ {
			c := centroid{r.f(), r.f()}
			if !(c.weight > 0) || math.IsNaN(c.mean) || c.mean < prev {
				return nil, ErrCorrupt
			}
			prev = c.mean
			sum += c.weight
			td.cs = append(td.cs, c)
		}
		if math.Abs(sum-n) > 1e-6*math.Max(1, n) || (cnt == 0 && n != 0) {
			return nil, fmt.Errorf("%w: weight mismatch", ErrCorrupt)
		}
		out = td
	case tMinHash:
		fl := r.raw(1)
		k := r.u()
		if r.err != nil || k < 1 || k > 4096 || uint64(len(r.b)) != k*8 {
			return nil, ErrCorrupt
		}
		m, _ := NewMinHash(int(k))
		m.empty = fl[0] == 1
		for i := range m.sig {
			m.sig[i] = binary.LittleEndian.Uint64(r.b[i*8:])
		}
		out = m
	case tBundle:
		b := &Bundle{Records: r.u()}
		var parts [4]any
		for i := range parts {
			sub := r.raw(r.u())
			if r.err != nil {
				return nil, ErrCorrupt
			}
			p, err := Unmarshal(sub)
			if err != nil {
				return nil, err
			}
			parts[i] = p
		}
		var ok [4]bool
		b.Distinct, ok[0] = parts[0].(*HLL)
		b.Freq, ok[1] = parts[1].(*CMS)
		b.Top, ok[2] = parts[2].(*SpaceSaving)
		b.Dist, ok[3] = parts[3].(*TDigest)
		if !(ok[0] && ok[1] && ok[2] && ok[3]) || len(r.b) != 0 {
			return nil, ErrCorrupt
		}
		out = b
	default:
		return nil, fmt.Errorf("skein: unknown sketch type %d", t)
	}
	if r.err != nil {
		return nil, r.err
	}
	return out, nil
}

// Kind names the sketch type for display.
func Kind(v any) string {
	switch v.(type) {
	case *HLL:
		return "hyperloglog"
	case *CMS:
		return "count-min"
	case *SpaceSaving:
		return "space-saving"
	case *Bloom:
		return "bloom"
	case *Cuckoo:
		return "cuckoo"
	case *TDigest:
		return "t-digest"
	case *MinHash:
		return "minhash"
	case *Bundle:
		return "bundle"
	}
	return "unknown"
}
