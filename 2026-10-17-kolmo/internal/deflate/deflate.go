// Package deflate implements RFC 1951 DEFLATE (compressor and decompressor) and
// the RFC 1952 gzip wrapper from scratch.
package deflate

import (
	"kolmo/internal/bitio"
	"kolmo/internal/huff"
)

const (
	windowSize = 32768
	minMatch   = 3
	maxMatch   = 258
	hashBits   = 15
	blockToks  = 1 << 15
)

// level parameters, after zlib's configuration table.
type params struct {
	good, lazy, nice, chain int
	greedy                  bool // levels 1-3 use greedy parsing; lazy is then unused
}

var levels = [10]params{
	{},
	{4, 4, 8, 4, true}, {4, 5, 16, 8, true}, {4, 6, 32, 32, true},
	{4, 4, 16, 16, false}, {8, 16, 32, 32, false}, {8, 16, 128, 128, false},
	{8, 32, 128, 256, false}, {32, 128, 258, 1024, false}, {32, 258, 258, 4096, false},
}

type tok struct {
	l uint16 // literal byte, or match length
	d uint16 // 0 for a literal, else match distance
}

type matcher struct {
	src  []byte
	head []int32 // hash -> position+1
	prev []int32 // position -> previous position+1 with same hash
	p    params
}

func hash3(b []byte) uint32 {
	return (uint32(b[0])<<16 | uint32(b[1])<<8 | uint32(b[2])) * 0x9E3779B1 >> (32 - hashBits)
}

func (m *matcher) insert(i int) {
	if i+minMatch > len(m.src) {
		return
	}
	h := hash3(m.src[i:])
	m.prev[i] = m.head[h]
	m.head[h] = int32(i) + 1
}

// find returns the best match at i (length 0 if none better than minLen-1).
func (m *matcher) find(i, prevLen int) (int, int) {
	src := m.src
	n := len(src)
	if i+minMatch > n {
		return 0, 0
	}
	maxLen := maxMatch
	if n-i < maxLen {
		maxLen = n - i
	}
	chain := m.p.chain
	if prevLen >= m.p.good {
		chain >>= 2
	}
	bestLen, bestDist := minMatch-1, 0
	if prevLen > bestLen {
		bestLen = prevLen
	}
	cand := m.head[hash3(src[i:])]
	limit := i - windowSize
	for cand != 0 && chain > 0 {
		c := int(cand) - 1
		if c < limit || c >= i {
			break
		}
		if bestLen < maxLen && src[c+bestLen] == src[i+bestLen] && src[c] == src[i] {
			l := 0
			for l < maxLen && src[c+l] == src[i+l] {
				l++
			}
			if l > bestLen {
				bestLen, bestDist = l, i-c
				if l >= m.p.nice || l == maxLen {
					break
				}
			}
		}
		cand = m.prev[c]
		chain--
	}
	if bestDist == 0 {
		return 0, 0
	}
	if bestLen == minMatch && bestDist > 4096 {
		return 0, 0
	}
	return bestLen, bestDist
}

// Compress returns a raw DEFLATE stream for src at the given level (1-9; 0 = stored only).
func Compress(src []byte, level int) []byte {
	if level < 0 {
		level = 0
	}
	if level > 9 {
		level = 9
	}
	w := &bitio.Writer{}
	if len(src) == 0 || level == 0 {
		writeStoredBlocks(w, src, true)
		return w.Bytes()
	}
	m := &matcher{src: src, head: make([]int32, 1<<hashBits), prev: make([]int32, len(src)), p: levels[level]}
	toks := make([]tok, 0, blockToks)
	blockStart, pos := 0, 0
	flush := func(final bool) {
		writeBlock(w, toks, src[blockStart:pos], final)
		toks = toks[:0]
		blockStart = pos
	}
	i := 0
	haveNext := false
	var nl, nd int
	for i < len(src) {
		var l, d int
		if haveNext {
			l, d, haveNext = nl, nd, false
		} else {
			l, d = m.find(i, 0)
		}
		m.insert(i)
		if l >= minMatch && !m.p.greedy && l < m.p.lazy && i+1 < len(src) {
			nl, nd = m.find(i+1, l)
			haveNext = true
			if nl > l {
				toks = append(toks, tok{uint16(src[i]), 0})
				i++
				pos = i
				if len(toks) >= blockToks {
					flush(false)
				}
				continue
			}
			haveNext = false // the deferred search is stale once we commit to this match
		}
		if l >= minMatch {
			toks = append(toks, tok{uint16(l), uint16(d)})
			for k := 1; k < l; k++ {
				m.insert(i + k)
			}
			i += l
		} else {
			toks = append(toks, tok{uint16(src[i]), 0})
			i++
		}
		pos = i
		if len(toks) >= blockToks {
			flush(false)
		}
	}
	flush(true)
	return w.Bytes()
}

func writeStoredBlocks(w *bitio.Writer, raw []byte, final bool) {
	if len(raw) == 0 {
		w.WriteBits(b2u(final), 1)
		w.WriteBits(0, 2)
		w.Align()
		w.WriteBits(0, 16)
		w.WriteBits(0xffff, 16)
		return
	}
	for len(raw) > 0 {
		n := len(raw)
		if n > 65535 {
			n = 65535
		}
		last := final && n == len(raw)
		w.WriteBits(b2u(last), 1)
		w.WriteBits(0, 2)
		w.Align()
		w.WriteBits(uint32(n), 16)
		w.WriteBits(uint32(^n)&0xffff, 16)
		w.WriteBytes(raw[:n])
		raw = raw[n:]
	}
}

func b2u(b bool) uint32 {
	if b {
		return 1
	}
	return 0
}

// run-length encoding of code lengths (symbols 16, 17, 18)
type clTok struct {
	sym   uint8
	extra uint8
}

func rleLens(lens []uint8) []clTok {
	var out []clTok
	for i := 0; i < len(lens); {
		v := lens[i]
		run := 1
		for i+run < len(lens) && lens[i+run] == v {
			run++
		}
		i += run
		if v == 0 {
			for run >= 11 {
				n := run
				if n > 138 {
					n = 138
				}
				out = append(out, clTok{18, uint8(n - 11)})
				run -= n
			}
			if run >= 3 {
				out = append(out, clTok{17, uint8(run - 3)})
				run = 0
			}
			for ; run > 0; run-- {
				out = append(out, clTok{0, 0})
			}
			continue
		}
		out = append(out, clTok{v, 0})
		run--
		for run >= 3 {
			n := run
			if n > 6 {
				n = 6
			}
			out = append(out, clTok{16, uint8(n - 3)})
			run -= n
		}
		for ; run > 0; run-- {
			out = append(out, clTok{v, 0})
		}
	}
	return out
}

// writeBlock emits toks as whichever of stored / fixed / dynamic is smallest.
func writeBlock(w *bitio.Writer, toks []tok, raw []byte, final bool) {
	litFreq := make([]int, 286)
	distFreq := make([]int, 30)
	litFreq[256] = 1
	for _, t := range toks {
		if t.d == 0 {
			litFreq[t.l]++
		} else {
			litFreq[257+int(lenCode[t.l])]++
			distFreq[distCode[t.d]]++
		}
	}
	litLens := huff.Lengths(litFreq, 15)
	distLens := huff.Lengths(distFreq, 15)
	anyDist := false
	for _, l := range distLens {
		if l > 0 {
			anyDist = true
		}
	}
	if !anyDist {
		distLens[0] = 1
	}
	// dynamic header
	hlit := 286
	for hlit > 257 && litLens[hlit-1] == 0 {
		hlit--
	}
	hdist := 30
	for hdist > 1 && distLens[hdist-1] == 0 {
		hdist--
	}
	allLens := append(append([]uint8(nil), litLens[:hlit]...), distLens[:hdist]...)
	clToks := rleLens(allLens)
	clFreq := make([]int, 19)
	for _, t := range clToks {
		clFreq[t.sym]++
	}
	used := 0
	for _, f := range clFreq {
		if f > 0 {
			used++
		}
	}
	for s := 0; used < 2; s++ { // the code-length code must be a complete prefix code
		if clFreq[s] == 0 {
			clFreq[s] = 1
			used++
		}
	}
	clLens := huff.Lengths(clFreq, 7)
	hclen := 19
	for hclen > 4 && clLens[clOrder[hclen-1]] == 0 {
		hclen--
	}
	// sizes in bits
	dynBits := 3 + 14 + 3*hclen
	for _, t := range clToks {
		dynBits += int(clLens[t.sym])
		switch t.sym {
		case 16:
			dynBits += 2
		case 17:
			dynBits += 3
		case 18:
			dynBits += 7
		}
	}
	fixL, fixD := fixedLitLens(), fixedDistLens()
	dynBits += bodyBits(litFreq, distFreq, litLens, distLens)
	fixBits := 3 + bodyBits(litFreq, distFreq, fixL, fixD)
	blocks := (len(raw) + 65534) / 65535
	if blocks == 0 {
		blocks = 1
	}
	storedBits := len(raw)*8 + blocks*(3+7+32) // header + worst-case alignment pad per block
	switch {
	case storedBits < dynBits && storedBits < fixBits:
		writeStoredBlocks(w, raw, final)
	case fixBits <= dynBits:
		w.WriteBits(b2u(final), 1)
		w.WriteBits(1, 2)
		writeBody(w, toks, fixL, fixD)
	default:
		w.WriteBits(b2u(final), 1)
		w.WriteBits(2, 2)
		w.WriteBits(uint32(hlit-257), 5)
		w.WriteBits(uint32(hdist-1), 5)
		w.WriteBits(uint32(hclen-4), 4)
		for i := 0; i < hclen; i++ {
			w.WriteBits(uint32(clLens[clOrder[i]]), 3)
		}
		clCodes := huff.Codes(clLens)
		for _, t := range clToks {
			w.WriteBitsRev(clCodes[t.sym], uint(clLens[t.sym]))
			switch t.sym {
			case 16:
				w.WriteBits(uint32(t.extra), 2)
			case 17:
				w.WriteBits(uint32(t.extra), 3)
			case 18:
				w.WriteBits(uint32(t.extra), 7)
			}
		}
		writeBody(w, toks, litLens, distLens)
	}
}

func bodyBits(litFreq, distFreq []int, litLens, distLens []uint8) int {
	bits := 0
	for s, f := range litFreq {
		if f == 0 {
			continue
		}
		bits += f * int(litLens[s])
		if s >= 257 {
			bits += f * int(lenExtra[s-257])
		}
	}
	for s, f := range distFreq {
		bits += f * (int(distLens[s]) + int(distExtra[s]))
	}
	return bits
}

func writeBody(w *bitio.Writer, toks []tok, litLens, distLens []uint8) {
	litCodes, distCodes := huff.Codes(litLens), huff.Codes(distLens)
	for _, t := range toks {
		if t.d == 0 {
			w.WriteBitsRev(litCodes[t.l], uint(litLens[t.l]))
			continue
		}
		lc := int(lenCode[t.l])
		w.WriteBitsRev(litCodes[257+lc], uint(litLens[257+lc]))
		w.WriteBits(uint32(t.l-lenBase[lc]), uint(lenExtra[lc]))
		dc := int(distCode[t.d])
		w.WriteBitsRev(distCodes[dc], uint(distLens[dc]))
		w.WriteBits(uint32(t.d-distBase[dc]), uint(distExtra[dc]))
	}
	w.WriteBitsRev(litCodes[256], uint(litLens[256]))
}
