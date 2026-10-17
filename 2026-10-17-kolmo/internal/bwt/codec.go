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

func appendBlock(out []byte, blk []byte) []byte {
	last, primary := Transform(blk)
	syms := rle0Encode(mtfEncode(last))
	freq := make([]int, alphabet)
	for _, s := range syms {
		freq[s]++
	}
	lens := huff.Lengths(freq, maxLen)
	codes := huff.Codes(lens)
	w := &bitio.Writer{}
	for _, l := range lens {
		w.WriteBits(uint32(l), 4)
	}
	for _, s := range syms {
		w.WriteBitsRev(codes[s], uint(lens[s]))
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

func decodeBlock(payload []byte, n, primary int) ([]byte, error) {
	r := bitio.NewReader(payload)
	lens := make([]uint8, alphabet)
	for i := range lens {
		v, err := r.ReadBits(4)
		if err != nil {
			return nil, fmt.Errorf("%w: truncated code table", ErrCorrupt)
		}
		lens[i] = uint8(v)
	}
	dec, err := huff.NewDecoder(lens)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrCorrupt, err)
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
	for {
		s, err := dec.Decode(r)
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
