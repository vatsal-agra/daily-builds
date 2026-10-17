// Package huff builds length-limited canonical Huffman codes (package-merge)
// and provides fast table-driven decoding.
package huff

import (
	"errors"
	"sort"
)

type item struct {
	w           int
	left, right *item
	sym         int
}

// Lengths returns optimal length-limited code lengths for the given frequencies.
// Symbols with zero frequency get length 0. If exactly one symbol is used it gets length 1.
func Lengths(freq []int, limit int) []uint8 {
	lens := make([]uint8, len(freq))
	var leaves []*item
	for s, f := range freq {
		if f > 0 {
			leaves = append(leaves, &item{w: f, sym: s})
		}
	}
	n := len(leaves)
	if n == 0 {
		return lens
	}
	if n == 1 {
		lens[leaves[0].sym] = 1
		return lens
	}
	if n > 1<<uint(limit) {
		panic("huff: too many symbols for length limit")
	}
	sort.SliceStable(leaves, func(i, j int) bool { return leaves[i].w < leaves[j].w })
	cur := append([]*item(nil), leaves...)
	for lvl := 1; lvl < limit; lvl++ {
		var pk []*item
		for i := 0; i+1 < len(cur); i += 2 {
			pk = append(pk, &item{w: cur[i].w + cur[i+1].w, left: cur[i], right: cur[i+1], sym: -1})
		}
		merged := make([]*item, 0, len(leaves)+len(pk))
		i, j := 0, 0
		for i < len(leaves) || j < len(pk) {
			if j >= len(pk) || (i < len(leaves) && leaves[i].w <= pk[j].w) {
				merged = append(merged, leaves[i])
				i++
			} else {
				merged = append(merged, pk[j])
				j++
			}
		}
		cur = merged
	}
	var count func(it *item)
	count = func(it *item) {
		if it.sym >= 0 {
			lens[it.sym]++
			return
		}
		count(it.left)
		count(it.right)
	}
	for _, it := range cur[:2*n-2] {
		count(it)
	}
	return lens
}

// Codes assigns canonical codes (MSB-first values) from lengths, as in RFC 1951 §3.2.2.
func Codes(lens []uint8) []uint32 {
	var blCount [33]int
	maxLen := 0
	for _, l := range lens {
		blCount[l]++
		if int(l) > maxLen {
			maxLen = int(l)
		}
	}
	blCount[0] = 0
	var next [34]uint32
	code := uint32(0)
	for b := 1; b <= maxLen; b++ {
		code = (code + uint32(blCount[b-1])) << 1
		next[b] = code
	}
	codes := make([]uint32, len(lens))
	for s, l := range lens {
		if l != 0 {
			codes[s] = next[l]
			next[l]++
		}
	}
	return codes
}

// ErrBadCode reports an over-subscribed or incomplete prefix code.
var ErrBadCode = errors.New("huff: invalid code lengths")

// Decoder decodes LSB-first bit streams with a canonical code.
type Decoder struct {
	maxLen  uint
	table   []uint32 // index: next maxLen bits (LSB first); value: sym<<4 | len, 0 = invalid
	single  bool
	singleS int
}

// NewDecoder validates lens (allowing a single used symbol, or none) and builds a lookup table.
func NewDecoder(lens []uint8) (*Decoder, error) {
	used, maxLen := 0, uint(0)
	kraft := 0
	for _, l := range lens {
		if l > 0 {
			used++
			if uint(l) > maxLen {
				maxLen = uint(l)
			}
		}
	}
	d := &Decoder{maxLen: maxLen}
	if used == 0 {
		return d, nil
	}
	for _, l := range lens {
		if l > 0 {
			kraft += 1 << (maxLen - uint(l))
		}
	}
	if kraft > 1<<maxLen {
		return nil, ErrBadCode
	}
	if kraft < 1<<maxLen && used != 1 {
		return nil, ErrBadCode
	}
	codes := Codes(lens)
	d.table = make([]uint32, 1<<maxLen)
	for s, l := range lens {
		if l == 0 {
			continue
		}
		var rev uint32
		for i := uint8(0); i < l; i++ {
			rev = rev<<1 | codes[s]>>i&1
		}
		for idx := rev; idx < uint32(len(d.table)); idx += 1 << l {
			d.table[idx] = uint32(s)<<4 | uint32(l)
		}
	}
	return d, nil
}

// BitSource is what the decoder needs from a bit reader.
type BitSource interface {
	PeekBits(n uint) (uint32, uint)
	Skip(n uint)
}

// ErrSymbol is returned when no code matches the input bits.
var ErrSymbol = errors.New("huff: invalid symbol")

// Decode reads one symbol.
func (d *Decoder) Decode(r BitSource) (int, error) {
	if d.maxLen == 0 {
		return 0, ErrSymbol
	}
	bits, avail := r.PeekBits(d.maxLen)
	e := d.table[bits]
	l := uint(e & 15)
	if e == 0 || l > avail {
		return 0, ErrSymbol
	}
	r.Skip(l)
	return int(e >> 4), nil
}
