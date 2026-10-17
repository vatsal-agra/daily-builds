package bwt

import (
	"encoding/binary"
	"errors"
	"fmt"

	"kolmo/internal/bitio"
	"kolmo/internal/huff"
)

const (
	// BlockSize is the maximum number of input bytes per BWT block.
	BlockSize = 1 << 20
	symRunA   = 0
	symRunB   = 1
	symEOB    = 257
	alphabet  = 258
	maxLen    = 15
)

// ErrCorrupt reports a malformed block-sorting stream.
var ErrCorrupt = errors.New("bwt: corrupt stream")

func mtfEncode(in []byte) []byte {
	var table [256]byte
	for i := range table {
		table[i] = byte(i)
	}
	out := make([]byte, len(in))
	for i, b := range in {
		j := 0
		for table[j] != b {
			j++
		}
		out[i] = byte(j)
		copy(table[1:j+1], table[:j])
		table[0] = b
	}
	return out
}

func mtfDecode(in []byte) []byte {
	var table [256]byte
	for i := range table {
		table[i] = byte(i)
	}
	out := make([]byte, len(in))
	for i, j := range in {
		b := table[j]
		out[i] = b
		copy(table[1:int(j)+1], table[:j])
		table[0] = b
	}
	return out
}

// rle0Encode turns MTF output into symbols: runs of zeros become RUNA/RUNB digits
// (bijective base 2, least significant first), other values v become v+1.
func rle0Encode(in []byte) []uint16 {
	out := make([]uint16, 0, len(in)/2+2)
	run := 0
	flush := func() {
		for run > 0 {
			if run&1 == 1 {
				out = append(out, symRunA)
				run = (run - 1) / 2
			} else {
				out = append(out, symRunB)
				run = (run - 2) / 2
			}
		}
	}
	for _, v := range in {
		if v == 0 {
			run++
			continue
		}
		flush()
		out = append(out, uint16(v)+1)
	}
	flush()
	return append(out, symEOB)
}

// Encode compresses src block by block.
func Encode(src []byte) []byte {
	var out []byte
	for off := 0; off < len(src); off += BlockSize {
		end := off + BlockSize
		if end > len(src) {
			end = len(src)
		}
		out = appendBlock(out, src[off:end])
	}
	return out
}

// groupSize is the number of symbols coded with one Huffman table before the encoder may switch.
const groupSize = 50

func tableCount(nsyms int) int {
	switch {
	case nsyms < 200:
		return 1
	case nsyms < 600:
		return 2
	case nsyms < 1200:
		return 3
	case nsyms < 2400:
		return 4
	case nsyms < 6000:
		return 5
	}
	return 6
}

// chooseTables clusters symbol groups onto T Huffman tables by iterative refinement
// (assign each group to its cheapest table, rebuild tables from their groups, repeat).
// It returns the final per-group selector and exact code lengths for each table.
func chooseTables(syms []uint16, T int) ([]uint8, [][]uint8) {
	ng := (len(syms) + groupSize - 1) / groupSize
	sel := make([]uint8, ng)
	lens := make([][]uint8, T)
	if T == 1 {
		freq := make([]int, alphabet)
		for _, s := range syms {
			freq[s]++
		}
		return sel, [][]uint8{huff.Lengths(freq, maxLen)}
	}
	// initial tables: split the alphabet into T ranges of equal total frequency; in-range symbols are cheap
	total := make([]int, alphabet)
	sum := 0
	for _, s := range syms {
		total[s]++
		sum++
	}
	lo, acc := 0, 0
	for t := 0; t < T; t++ {
		target := sum * (t + 1) / T
		hi := lo
		for hi < alphabet && (acc < target || t == T-1) {
			acc += total[hi]
			hi++
		}
		lens[t] = make([]uint8, alphabet)
		for v := range lens[t] {
			if v >= lo && v < hi {
				lens[t][v] = 2
			} else {
				lens[t][v] = 15
			}
		}
		lo = hi
	}
	freqs := make([][]int, T)
	for iter := 0; iter < 5; iter++ {
		for t := range freqs {
			freqs[t] = make([]int, alphabet)
		}
		for g := 0; g < ng; g++ {
			end := min((g+1)*groupSize, len(syms))
			best, bestCost := 0, int(^uint(0)>>1)
			for t := 0; t < T; t++ {
				c := 0
				for _, s := range syms[g*groupSize : end] {
					c += int(lens[t][s])
				}
				if c < bestCost {
					best, bestCost = t, c
				}
			}
			sel[g] = uint8(best)
			for _, s := range syms[g*groupSize : end] {
				freqs[best][s]++
			}
		}
		last := iter == 4
		for t := 0; t < T; t++ {
			f := freqs[t]
			if !last { // smooth so every symbol stays reachable while clustering
				f = append([]int(nil), f...)
				for v := range f {
					f[v]++
				}
			}
			lens[t] = huff.Lengths(f, maxLen)
		}
	}
	return sel, lens
}

func appendBlock(out []byte, blk []byte) []byte {
	last, primary := Transform(blk)
	syms := rle0Encode(mtfEncode(last))
	T := tableCount(len(syms))
	sel, lens := chooseTables(syms, T)
	// A table no group chose has no symbols; drop it by remapping selectors densely.
	used := make([]int, T)
	for i := range used {
		used[i] = -1
	}
	var keep [][]uint8
	for _, t := range sel {
		if used[t] < 0 {
			used[t] = len(keep)
			keep = append(keep, lens[t])
		}
	}
	for g, t := range sel {
		sel[g] = uint8(used[t])
	}
	T = len(keep)

	w := &bitio.Writer{}
	w.WriteBits(uint32(T), 4)
	w.WriteBits(uint32(len(sel)), 32)
	selFreq := make([]int, T)
	for _, t := range sel {
		selFreq[t]++
	}
	selLens := huff.Lengths(selFreq, maxLen)
	selCodes := huff.Codes(selLens)
	for _, l := range selLens {
		w.WriteBits(uint32(l), 4)
	}
	for _, t := range sel {
		w.WriteBitsRev(selCodes[t], uint(selLens[t]))
	}
	codes := make([][]uint32, T)
	for t, l := range keep {
		for _, v := range l {
			w.WriteBits(uint32(v), 4)
		}
		codes[t] = huff.Codes(l)
	}
	for i, s := range syms {
		t := sel[i/groupSize]
		w.WriteBitsRev(codes[t][s], uint(keep[t][s]))
	}
	payload := w.Bytes()
	out = binary.LittleEndian.AppendUint32(out, uint32(len(blk)))
	out = binary.LittleEndian.AppendUint32(out, uint32(primary))
	out = binary.LittleEndian.AppendUint32(out, uint32(len(payload)))
	return append(out, payload...)
}

// Decode reverses Encode; total is the expected decompressed size.
func Decode(data []byte, total int) ([]byte, error) {
	out := make([]byte, 0, total)
	for len(out) < total {
		if len(data) < 12 {
			return nil, fmt.Errorf("%w: truncated block header", ErrCorrupt)
		}
		n := int(binary.LittleEndian.Uint32(data))
		primary := int(binary.LittleEndian.Uint32(data[4:]))
		plen := int(binary.LittleEndian.Uint32(data[8:]))
		data = data[12:]
		if n <= 0 || n > BlockSize || n > total-len(out) || plen > len(data) {
			return nil, fmt.Errorf("%w: bad block sizes", ErrCorrupt)
		}
		blk, err := decodeBlock(data[:plen], n, primary)
		if err != nil {
			return nil, err
		}
		out = append(out, blk...)
		data = data[plen:]
	}
	if len(data) != 0 {
		return nil, fmt.Errorf("%w: trailing data", ErrCorrupt)
	}
	return out, nil
}

func readLens(r *bitio.Reader, n int) ([]uint8, error) {
	lens := make([]uint8, n)
	for i := range lens {
		v, err := r.ReadBits(4)
		if err != nil {
			return nil, fmt.Errorf("%w: truncated code table", ErrCorrupt)
		}
		lens[i] = uint8(v)
	}
	return lens, nil
}

func decodeBlock(payload []byte, n, primary int) ([]byte, error) {
	r := bitio.NewReader(payload)
	hdr, err := r.ReadBits(4)
	if err != nil || hdr < 1 || hdr > 6 {
		return nil, fmt.Errorf("%w: bad table count", ErrCorrupt)
	}
	T := int(hdr)
	nsel, err := r.ReadBits(32)
	if err != nil || nsel == 0 || int(nsel) > n/1+2 {
		return nil, fmt.Errorf("%w: bad selector count", ErrCorrupt)
	}
	selLens, err := readLens(r, T)
	if err != nil {
		return nil, err
	}
	selDec, err := huff.NewDecoder(selLens)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrCorrupt, err)
	}
	sel := make([]uint8, nsel)
	for i := range sel {
		t, err := selDec.Decode(r)
		if err != nil {
			return nil, fmt.Errorf("%w: bad selector", ErrCorrupt)
		}
		sel[i] = uint8(t)
	}
	decs := make([]*huff.Decoder, T)
	for t := range decs {
		lens, err := readLens(r, alphabet)
		if err != nil {
			return nil, err
		}
		if decs[t], err = huff.NewDecoder(lens); err != nil {
			return nil, fmt.Errorf("%w: %v", ErrCorrupt, err)
		}
	}
	mtf := make([]byte, 0, n)
	run, weight := 0, 1
	flush := func() error {
		if run > n-len(mtf) {
			return fmt.Errorf("%w: zero run overflows block", ErrCorrupt)
		}
		mtf = append(mtf, make([]byte, run)...)
		run, weight = 0, 1
		return nil
	}
	for count := 0; ; count++ {
		if count/groupSize >= len(sel) {
			return nil, fmt.Errorf("%w: ran out of selectors", ErrCorrupt)
		}
		s, err := decs[sel[count/groupSize]].Decode(r)
		if err != nil {
			return nil, fmt.Errorf("%w: %v", ErrCorrupt, err)
		}
		switch {
		case s == symRunA || s == symRunB:
			run += weight * (s + 1)
			weight <<= 1
			if run > n { // also stops weight from overflowing
				return nil, fmt.Errorf("%w: zero run overflows block", ErrCorrupt)
			}
		case s == symEOB:
			if err := flush(); err != nil {
				return nil, err
			}
			if len(mtf) != n {
				return nil, fmt.Errorf("%w: block length mismatch", ErrCorrupt)
			}
			return Inverse(mtfDecode(mtf), primary)
		default:
			if err := flush(); err != nil {
				return nil, err
			}
			if len(mtf) >= n {
				return nil, fmt.Errorf("%w: block overflow", ErrCorrupt)
			}
			mtf = append(mtf, byte(s-1))
		}
	}
}
