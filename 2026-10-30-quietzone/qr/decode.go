package qr

import (
	"errors"
	"fmt"
	"sort"
	"unicode/utf8"
)

// Result is a successful decode.
type Result struct {
	Version int
	ECC     ECC
	Mask    int
	Text    string
	Bytes   []byte // raw data bytes of all byte-mode segments, text modes as ASCII
	// Segments as parsed from the stream.
	Segments []Segment
	ECI      int // last ECI designator seen, 0 if none
	// Error-correction accounting.
	ByteErrors        int   // codewords repaired by Reed-Solomon
	CorrectedCW       []int // indices into the interleaved codeword stream
	ErasuresUsed      int
	FormatDistance    int  // Hamming distance of the read format word to the nearest valid one
	FormatBruteForced bool // format info was unusable; (level,mask) found by trying all 32
	Transposed        bool // the matrix was mirrored (a scanner artefact) and fixed
	// Structured Append header, if present.
	SA *StructuredAppend
	// FNC1 first/second position flag.
	FNC1 bool
	// Capacity gives the ECC budget: max correctable codeword errors in the worst block.
	Budget int
}

// StructuredAppend is the header of one symbol in a multi-symbol sequence.
type StructuredAppend struct {
	Index, Total int
	Parity       byte
}

// DecodeOptions tunes decoding.
type DecodeOptions struct {
	// Erased marks modules known to be unreadable (e.g. covered by a logo);
	// codewords touching them are treated as erasures, doubling the correction power.
	Erased *Matrix
	// NoTranspose disables the mirrored-matrix retry.
	NoTranspose bool
}

// ErrFormat is returned when no valid format information can be found.
var ErrFormat = errors.New("format information unreadable")

// Decode reads a module matrix.
func Decode(m *Matrix) (*Result, error) { return DecodeWith(m, DecodeOptions{}) }

// DecodeWith reads a module matrix with options.
func DecodeWith(m *Matrix, opt DecodeOptions) (*Result, error) {
	if opt.Erased != nil && opt.Erased.N != m.N {
		return nil, fmt.Errorf("erasure map is %dx%d but the symbol is %dx%d", opt.Erased.N, opt.Erased.N, m.N, m.N)
	}
	r, err := decodeOnce(m, opt)
	if err == nil || opt.NoTranspose {
		return r, err
	}
	t := NewMatrix(m.N)
	for y := 0; y < m.N; y++ {
		for x := 0; x < m.N; x++ {
			t.Set(x, y, m.Get(y, x))
		}
	}
	var te *Matrix
	if opt.Erased != nil {
		te = NewMatrix(m.N)
		for y := 0; y < m.N; y++ {
			for x := 0; x < m.N; x++ {
				te.Set(x, y, opt.Erased.Get(y, x))
			}
		}
	}
	if r2, err2 := decodeOnce(t, DecodeOptions{Erased: te, NoTranspose: true}); err2 == nil {
		r2.Transposed = true
		return r2, nil
	}
	return nil, err
}

func decodeOnce(m *Matrix, opt DecodeOptions) (*Result, error) {
	if opt.Erased != nil && opt.Erased.N != m.N {
		return nil, fmt.Errorf("erasure map is %dx%d but the symbol is %dx%d", opt.Erased.N, opt.Erased.N, m.N, m.N)
	}
	if m.N < 21 || m.N > 177 || (m.N-17)%4 != 0 {
		return nil, fmt.Errorf("%dx%d is not a QR symbol size", m.N, m.N)
	}
	version := (m.N - 17) / 4
	l := NewLayout(version)
	cands := formatCandidates(m)
	var bestErr error
	for i, c := range cands {
		res, err := decodeWithFormat(m, l, opt, c.ecc, c.mask)
		if err == nil {
			res.FormatDistance = c.dist
			res.FormatBruteForced = c.dist > 3
			return res, nil
		}
		if i == 0 {
			bestErr = err // the most plausible (level, mask): its failure is the informative one
		}
		// Within the BCH-correctable radius only the nearest candidates are credible,
		// but a wrong guess is harmless: RS verification rejects it.
		if i >= 40 {
			break
		}
	}
	if cands[0].dist <= 3 && bestErr != nil {
		return nil, bestErr // format info was fine; the data area is what is beyond repair
	}
	return nil, ErrFormat
}

type fmtCand struct {
	ecc  ECC
	mask int
	dist int
}

// formatCandidates ranks all 32 (level, mask) pairs by Hamming distance to the
// two format copies; the distance used is the smaller of the two copies.
func formatCandidates(m *Matrix) []fmtCand {
	n := m.N
	var w1, w2 int
	for i := 0; i < 15; i++ {
		x, y := formatPos1(i)
		if m.Get(x, y) {
			w1 |= 1 << uint(i)
		}
		x, y = formatPos2(i, n)
		if m.Get(x, y) {
			w2 |= 1 << uint(i)
		}
	}
	var out []fmtCand
	for e := L; e <= H; e++ {
		for mk := 0; mk < 8; mk++ {
			c := formatCode(e, mk)
			d := min(popcount(c^w1), popcount(c^w2))
			out = append(out, fmtCand{e, mk, d})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].dist < out[j].dist })
	return out
}

func decodeWithFormat(m *Matrix, l *Layout, opt DecodeOptions, ecc ECC, mask int) (*Result, error) {
	work := m.Clone()
	applyMask(work, l, mask)
	order := l.DataOrder()
	total := RawCodewords(l.Version)
	cw := make([]byte, total)
	erasedCW := map[int]bool{}
	for i := 0; i < total*8; i++ {
		p := order[i]
		if work.Get(p[0], p[1]) {
			cw[i/8] |= 1 << (7 - uint(i%8))
		}
		if opt.Erased != nil && opt.Erased.Get(p[0], p[1]) {
			erasedCW[i/8] = true
		}
	}
	lens, eccLen := blockLayout(l.Version, ecc)
	nb := len(lens)
	// de-interleave
	blocks := make([][]byte, nb)
	idxMap := make([][]int, nb) // stream index of every byte of each block
	maxData := lens[nb-1]
	pos := 0
	for i := 0; i < maxData; i++ {
		for b := 0; b < nb; b++ {
			if i < lens[b] {
				blocks[b] = append(blocks[b], cw[pos])
				idxMap[b] = append(idxMap[b], pos)
				pos++
			}
		}
	}
	for i := 0; i < eccLen; i++ {
		for b := 0; b < nb; b++ {
			blocks[b] = append(blocks[b], cw[pos])
			idxMap[b] = append(idxMap[b], pos)
			pos++
		}
	}
	res := &Result{Version: l.Version, ECC: ecc, Mask: mask, Budget: eccLen / 2}
	var data []byte
	for b := 0; b < nb; b++ {
		var er []int
		for k, si := range idxMap[b] {
			if erasedCW[si] {
				er = append(er, k)
			}
		}
		// Too many erasures to be useful: treat the surplus as ordinary errors
		// by dropping erasure hints (the block may still decode).
		if len(er) > eccLen {
			er = nil
		}
		blk := append([]byte(nil), blocks[b]...)
		rr, err := RSDecode(blk, eccLen, er)
		if err != nil && len(er) > 0 {
			blk = append([]byte(nil), blocks[b]...)
			rr, err = RSDecode(blk, eccLen, nil)
			er = nil
		}
		if err != nil {
			return nil, fmt.Errorf("block %d: %w", b, err)
		}
		res.ErasuresUsed += len(er)
		for _, p := range rr.Positions {
			res.CorrectedCW = append(res.CorrectedCW, idxMap[b][p])
		}
		data = append(data, blk[:lens[b]]...)
	}
	sort.Ints(res.CorrectedCW)
	res.ByteErrors = len(res.CorrectedCW)
	if err := parseStream(data, l.Version, res); err != nil {
		return nil, err
	}
	return res, nil
}

type bitReader struct {
	b   []byte
	pos int
}

func (r *bitReader) left() int { return len(r.b)*8 - r.pos }
func (r *bitReader) get(n int) int {
	v := 0
	for i := 0; i < n; i++ {
		v = v<<1 | int(r.b[r.pos/8]>>(7-uint(r.pos%8))&1)
		r.pos++
	}
	return v
}

// parseStream decodes the segment stream (ISO 18004 §7.4).
func parseStream(data []byte, version int, res *Result) error {
	r := &bitReader{b: data}
	var raw []byte
	eci := 0
	for r.left() >= 4 {
		ind := r.get(4)
		switch ind {
		case 0: // terminator
			goto done
		case 1, 2, 4:
			mode := map[int]Mode{1: ModeNumeric, 2: ModeAlnum, 4: ModeByte}[ind]
			cb := ccBits(mode, version)
			if r.left() < cb {
				return errors.New("truncated count field")
			}
			cnt := r.get(cb)
			seg := Segment{Mode: mode, Chars: cnt}
			switch mode {
			case ModeNumeric:
				for cnt > 0 {
					k := min(cnt, 3)
					nb := [4]int{0, 4, 7, 10}[k]
					if r.left() < nb {
						return errors.New("truncated numeric data")
					}
					v := r.get(nb)
					if v >= [4]int{0, 10, 100, 1000}[k] {
						return errors.New("numeric group out of range")
					}
					s := fmt.Sprintf("%0*d", k, v)
					seg.Data = append(seg.Data, s...)
					cnt -= k
				}
			case ModeAlnum:
				for cnt > 0 {
					if cnt >= 2 {
						if r.left() < 11 {
							return errors.New("truncated alphanumeric data")
						}
						v := r.get(11)
						if v >= 45*45 {
							return errors.New("alphanumeric pair out of range")
						}
						seg.Data = append(seg.Data, alnumChars[v/45], alnumChars[v%45])
						cnt -= 2
					} else {
						if r.left() < 6 {
							return errors.New("truncated alphanumeric data")
						}
						v := r.get(6)
						if v >= 45 {
							return errors.New("alphanumeric char out of range")
						}
						seg.Data = append(seg.Data, alnumChars[v])
						cnt--
					}
				}
			case ModeByte:
				if r.left() < 8*cnt {
					return errors.New("truncated byte data")
				}
				for i := 0; i < cnt; i++ {
					seg.Data = append(seg.Data, byte(r.get(8)))
				}
			}
			raw = append(raw, seg.Data...)
			res.Segments = append(res.Segments, seg)
		case 7: // ECI
			if r.left() < 8 {
				return errors.New("truncated ECI")
			}
			b := r.get(8)
			switch {
			case b&0x80 == 0:
				eci = b
			case b&0xC0 == 0x80:
				if r.left() < 8 {
					return errors.New("truncated ECI")
				}
				eci = (b&0x3F)<<8 | r.get(8)
			default:
				if r.left() < 16 {
					return errors.New("truncated ECI")
				}
				eci = (b&0x1F)<<16 | r.get(16)
			}
			res.ECI = eci
			res.Segments = append(res.Segments, Segment{Mode: ModeECI, ECI: eci})
		case 3: // structured append
			if r.left() < 16 {
				return errors.New("truncated structured-append header")
			}
			idx, tot, par := r.get(4), r.get(4)+1, r.get(8)
			res.SA = &StructuredAppend{Index: idx, Total: tot, Parity: byte(par)}
			res.Segments = append(res.Segments, Segment{Mode: ModeStructured, Index: idx, Total: tot, Parity: byte(par)})
		case 5, 9: // FNC1
			res.FNC1 = true
			if ind == 9 {
				if r.left() < 8 {
					return errors.New("truncated FNC1")
				}
				r.get(8)
			}
		case 8:
			return errors.New("Kanji mode is not supported by this decoder")
		default:
			return fmt.Errorf("unknown mode indicator %04b", ind)
		}
	}
done:
	res.Bytes = raw
	res.Text = bytesToText(raw, eci)
	return nil
}

// bytesToText interprets raw bytes under the ECI in effect. ECI 3 and the
// no-ECI default are ISO-8859-1 per the standard, but real-world producers
// emit UTF-8 without a header; valid multi-byte UTF-8 is therefore accepted.
func bytesToText(raw []byte, eci int) string {
	if eci == 26 || (eci == 0 && utf8.Valid(raw)) {
		return string(raw)
	}
	if eci == 0 || eci == 1 || eci == 3 {
		rs := make([]rune, len(raw))
		for i, b := range raw {
			rs[i] = rune(b)
		}
		return string(rs)
	}
	return string(raw)
}
