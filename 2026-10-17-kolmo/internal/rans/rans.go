// Package rans implements static order-0 and order-1 range-ANS entropy coding
// (Duda 2013; byte-wise renormalisation as in Giesen's ryg_rans) with 12-bit frequencies.
package rans

import (
	"encoding/binary"
	"errors"
	"fmt"
)

const (
	scaleBits = 12
	scale     = 1 << scaleBits
	lowerL    = 1 << 23
)

// ErrCorrupt reports a malformed rANS stream.
var ErrCorrupt = errors.New("rans: corrupt stream")

type table struct {
	freq [256]uint32
	cum  [256]uint32
}

// normalize scales counts so they sum to exactly `scale`, keeping every present symbol >= 1.
func normalize(cnt *[256]int) (t table) {
	total := 0
	for _, c := range cnt {
		total += c
	}
	if total == 0 {
		return
	}
	sum := 0
	for s, c := range cnt {
		if c > 0 {
			f := uint32(int64(c) * scale / int64(total))
			if f == 0 {
				f = 1
			}
			t.freq[s] = f
			sum += int(f)
		}
	}
	for sum != scale {
		best := -1
		for s := range t.freq {
			if sum > scale && t.freq[s] <= 1 {
				continue
			}
			if best < 0 || t.freq[s] > t.freq[best] {
				best = s
			}
		}
		if sum < scale {
			t.freq[best]++
			sum++
		} else {
			t.freq[best]--
			sum--
		}
	}
	c := uint32(0)
	for s := range t.freq {
		t.cum[s] = c
		c += t.freq[s]
	}
	return
}

func appendTable(out []byte, t *table) []byte {
	n := 0
	for _, f := range t.freq {
		if f > 0 {
			n++
		}
	}
	out = binary.AppendUvarint(out, uint64(n))
	prev := 0
	for s, f := range t.freq {
		if f > 0 {
			out = binary.AppendUvarint(out, uint64(s-prev))
			out = binary.AppendUvarint(out, uint64(f-1))
			prev = s
		}
	}
	return out
}

func readTable(data []byte) (t table, rest []byte, err error) {
	n, k := binary.Uvarint(data)
	if k <= 0 || n > 256 {
		return t, nil, fmt.Errorf("%w: bad table", ErrCorrupt)
	}
	data = data[k:]
	prev, sum := 0, uint32(0)
	for i := uint64(0); i < n; i++ {
		d, k1 := binary.Uvarint(data)
		if k1 <= 0 {
			return t, nil, fmt.Errorf("%w: bad table", ErrCorrupt)
		}
		f, k2 := binary.Uvarint(data[k1:])
		if k2 <= 0 || f >= scale {
			return t, nil, fmt.Errorf("%w: bad table", ErrCorrupt)
		}
		data = data[k1+k2:]
		s := prev + int(d)
		if s > 255 || (i > 0 && d == 0) {
			return t, nil, fmt.Errorf("%w: bad symbol", ErrCorrupt)
		}
		t.freq[s] = uint32(f) + 1
		prev = s
	}
	for s := range t.freq {
		t.cum[s] = sum
		sum += t.freq[s]
	}
	if n > 0 && sum != scale {
		return t, nil, fmt.Errorf("%w: frequencies do not sum to %d", ErrCorrupt, scale)
	}
	return t, data, nil
}

// Encode compresses src with an order-0 (order=0) or order-1 (order=1) model.
func Encode(src []byte, order int) []byte {
	nctx := 1
	if order == 1 {
		nctx = 256
	}
	ctxOf := func(i int) int {
		if order == 0 || i == 0 {
			return 0
		}
		return int(src[i-1])
	}
	counts := make([][256]int, nctx)
	for i, b := range src {
		counts[ctxOf(i)][b]++
	}
	tabs := make([]table, nctx)
	var out []byte
	if len(src) == 0 {
		return out
	}
	for c := range tabs {
		tabs[c] = normalize(&counts[c])
	}
	if order == 0 {
		out = appendTable(out, &tabs[0])
	} else {
		present := 0
		for c := range counts {
			for _, v := range counts[c] {
				if v > 0 {
					present++
					break
				}
			}
		}
		out = binary.AppendUvarint(out, uint64(present))
		for c := range counts {
			has := false
			for _, v := range counts[c] {
				if v > 0 {
					has = true
					break
				}
			}
			if has {
				out = append(out, byte(c))
				out = appendTable(out, &tabs[c])
			}
		}
	}
	// encode backwards; collect bytes in reverse
	x := uint32(lowerL)
	var rev []byte
	for i := len(src) - 1; i >= 0; i-- {
		t := &tabs[ctxOf(i)]
		f, c := t.freq[src[i]], t.cum[src[i]]
		xmax := ((lowerL >> scaleBits) << 8) * f
		for x >= xmax {
			rev = append(rev, byte(x))
			x >>= 8
		}
		x = (x/f)<<scaleBits + x%f + c
	}
	rev = append(rev, byte(x), byte(x>>8), byte(x>>16), byte(x>>24))
	for i := len(rev) - 1; i >= 0; i-- {
		out = append(out, rev[i])
	}
	return out
}

// Decode reverses Encode; n is the original length.
func Decode(data []byte, n, order int) ([]byte, error) {
	if n == 0 {
		return nil, nil
	}
	nctx := 1
	tabs := make([]table, 256)
	have := make([]bool, 256)
	var err error
	if order == 0 {
		if tabs[0], data, err = readTable(data); err != nil {
			return nil, err
		}
		have[0] = true
	} else {
		cnt, k := binary.Uvarint(data)
		if k <= 0 || cnt > 256 {
			return nil, fmt.Errorf("%w: bad context count", ErrCorrupt)
		}
		data = data[k:]
		for i := uint64(0); i < cnt; i++ {
			if len(data) < 1 {
				return nil, fmt.Errorf("%w: truncated", ErrCorrupt)
			}
			c := data[0]
			if tabs[c], data, err = readTable(data[1:]); err != nil {
				return nil, err
			}
			have[c] = true
		}
		nctx = 256
	}
	_ = nctx
	if len(data) < 4 {
		return nil, fmt.Errorf("%w: truncated state", ErrCorrupt)
	}
	x := binary.BigEndian.Uint32(data)
	data = data[4:]
	// slot -> symbol lookup, built lazily per context
	lookup := make([][]byte, 256)
	out := make([]byte, n)
	ctx := 0
	for i := 0; i < n; i++ {
		if order == 0 {
			ctx = 0
		}
		if !have[ctx] {
			return nil, fmt.Errorf("%w: symbol in unmodelled context", ErrCorrupt)
		}
		if lookup[ctx] == nil {
			l := make([]byte, scale)
			for s := 0; s < 256; s++ {
				for k := tabs[ctx].cum[s]; k < tabs[ctx].cum[s]+tabs[ctx].freq[s]; k++ {
					l[k] = byte(s)
				}
			}
			lookup[ctx] = l
		}
		slot := x & (scale - 1)
		s := lookup[ctx][slot]
		t := &tabs[ctx]
		x = t.freq[s]*(x>>scaleBits) + slot - t.cum[s]
		for x < lowerL {
			if len(data) == 0 {
				return nil, fmt.Errorf("%w: truncated payload", ErrCorrupt)
			}
			x = x<<8 | uint32(data[0])
			data = data[1:]
		}
		out[i] = s
		ctx = int(s)
	}
	if len(data) != 0 || x != lowerL {
		return nil, fmt.Errorf("%w: trailing data or bad final state", ErrCorrupt)
	}
	return out, nil
}
