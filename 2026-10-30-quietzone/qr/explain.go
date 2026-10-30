package qr

import "fmt"

// BlockInfo describes one Reed-Solomon block.
type BlockInfo struct {
	DataLen, ECCLen int
	Correctable     int // errors the block can repair: ECCLen/2
}

// SegInfo describes one segment of the bit stream.
type SegInfo struct {
	Mode  string
	Chars int
	Bits  int
}

// ModuleInfo describes the role of a single module.
type ModuleInfo struct {
	Kind Kind
	CW   int // interleaved codeword index, -1 for function modules/remainder
	Bit  int // bit within the codeword, 0 = MSB
}

// Explanation is a full anatomy of an encoded symbol.
type Explanation struct {
	Version, Size  int
	ECC            ECC
	Mask           int
	Blocks         []BlockInfo
	CWBlock        []int  // block index of every interleaved codeword
	CWIsECC        []bool // whether each interleaved codeword is parity
	Modules        []ModuleInfo
	Penalties      [8][4]int // N1..N4 for every mask
	Segments       []SegInfo
	DataBits       int // bits actually used by segments
	CapacityBits   int
	PadBits        int
	RemainderBits  int
	TotalCodewords int
}

// Explain computes the anatomy of c.
func (c *Code) Explain() *Explanation {
	v := c.Version
	l := NewLayout(v)
	lens, eccLen := blockLayout(v, c.ECC)
	ex := &Explanation{Version: v, Size: l.N, ECC: c.ECC, Mask: c.Mask, TotalCodewords: RawCodewords(v)}
	for _, d := range lens {
		ex.Blocks = append(ex.Blocks, BlockInfo{DataLen: d, ECCLen: eccLen, Correctable: eccLen / 2})
	}
	nb := len(lens)
	maxData := lens[nb-1]
	for i := 0; i < maxData; i++ {
		for b := 0; b < nb; b++ {
			if i < lens[b] {
				ex.CWBlock = append(ex.CWBlock, b)
				ex.CWIsECC = append(ex.CWIsECC, false)
			}
		}
	}
	for i := 0; i < eccLen; i++ {
		for b := 0; b < nb; b++ {
			ex.CWBlock = append(ex.CWBlock, b)
			ex.CWIsECC = append(ex.CWIsECC, true)
		}
	}
	ex.Modules = make([]ModuleInfo, l.N*l.N)
	for y := 0; y < l.N; y++ {
		for x := 0; x < l.N; x++ {
			ex.Modules[y*l.N+x] = ModuleInfo{Kind: l.KindAt(x, y), CW: -1}
		}
	}
	for i, p := range l.DataOrder() {
		if i < ex.TotalCodewords*8 {
			ex.Modules[p[1]*l.N+p[0]] = ModuleInfo{Kind: KData, CW: i / 8, Bit: i % 8}
		}
	}
	ex.RemainderBits = rawModules(v) - ex.TotalCodewords*8
	for mk := 0; mk < 8; mk++ {
		o, err := EncodeSegments(c.Segments, v, Options{ECC: c.ECC, Mask: ForceMask(mk)})
		if err == nil {
			ex.Penalties[mk] = PenaltyParts(o.Matrix)
		}
	}
	for _, s := range c.Segments {
		ex.Segments = append(ex.Segments, SegInfo{Mode: s.Mode.String(), Chars: s.Chars, Bits: segBits(s, v)})
		ex.DataBits += segBits(s, v)
	}
	ex.CapacityBits = DataCodewords(v, c.ECC) * 8
	ex.PadBits = ex.CapacityBits - ex.DataBits
	return ex
}

// KindName names a module kind.
func KindName(k Kind) string {
	return [...]string{"data", "finder", "separator", "timing", "alignment", "format", "version", "dark module"}[k]
}

// CodewordModules returns the module coordinates of interleaved codeword cw.
func (c *Code) CodewordModules(cw int) [][2]int {
	order := NewLayout(c.Version).DataOrder()
	if cw < 0 || cw*8+8 > len(order) {
		return nil
	}
	return order[cw*8 : cw*8+8]
}

// Verdict predicts, from the codeword damage alone, whether Reed-Solomon can
// repair a set of damaged codewords: every block must have at most
// floor(ecc/2) of them (no erasure hints). It is the exact condition under
// which decoding is *guaranteed*; beyond it decoding fails or, very rarely,
// miscorrects.
func (ex *Explanation) Verdict(damagedCW []int) (ok bool, perBlock []int) {
	perBlock = make([]int, len(ex.Blocks))
	seen := map[int]bool{}
	for _, cw := range damagedCW {
		if cw < 0 || cw >= len(ex.CWBlock) || seen[cw] {
			continue
		}
		seen[cw] = true
		perBlock[ex.CWBlock[cw]]++
	}
	ok = true
	for b, n := range perBlock {
		if n > ex.Blocks[b].Correctable {
			ok = false
		}
	}
	return
}

func (e *Explanation) String() string {
	return fmt.Sprintf("v%d-%v mask %d, %d blocks", e.Version, e.ECC, e.Mask, len(e.Blocks))
}
