package codec

import (
	"errors"
	"fmt"
)

// MV is a motion vector in quarter-pel luma units.
type MV struct{ X, Y int16 }

const (
	maxMV = 160 // quarter-pel (= 40 px): keeps every tap inside the frame border
)

// Frame types.
const (
	FrameI = 0
	FrameP = 1
	FrameB = 2
)

// Part is one motion partition. Dir bit0 = uses list 0, bit1 = list 1.
type Part struct {
	Dir int
	MV  [2]MV
}

// MB is the complete syntax of one macroblock.
type MB struct {
	Skip, Intra  bool
	IMode, CMode int
	Shape        int // 0 16x16, 1 16x8, 2 8x16, 3 8x8
	Parts        [4]Part
	CBP          int           // bits 0..3 luma 8x8 groups, bit 4 U, bit 5 V
	Lev          [24][16]int32 // levels in scan order; 0..15 luma raster 4x4, 16..19 U, 20..23 V
}

// partRects[shape] lists partitions as (x,y,w,h) in 4x4-block units.
var partRects = [4][][4]int{
	{{0, 0, 4, 4}},
	{{0, 0, 4, 2}, {0, 2, 4, 2}},
	{{0, 0, 2, 4}, {2, 0, 2, 4}},
	{{0, 0, 2, 2}, {2, 0, 2, 2}, {0, 2, 2, 2}, {2, 2, 2, 2}},
}

// Blk is the per-4x4 motion/coding state used for prediction and deblocking.
type Blk struct {
	MV    [2]MV
	Use   uint8 // bit per list
	Intra bool
	Done  bool
	NZ    bool // luma block has non-zero levels
}

// models holds every adaptive context of a frame.
type models struct {
	skip      [3]Ctx
	intra     [3]Ctx
	imode     [3]Ctx
	cmode     [3]Ctx
	shape     [3]Ctx
	dir       [2]Ctx
	mvdZero   [2]Ctx
	mvdMag    [2][6]Ctx
	cbpLuma   [3]Ctx
	cbpChroma [3]Ctx
	cbf       [4][3]Ctx
	sig       [4][15]Ctx
	last      [4][15]Ctx
	lv1       [4][5]Ctx
	lvN       [4][6]Ctx
}

func newModels() *models {
	m := &models{}
	init1 := func(cs []Ctx) {
		for i := range cs {
			cs[i] = NewCtx()
		}
	}
	init1(m.skip[:])
	init1(m.intra[:])
	init1(m.imode[:])
	init1(m.cmode[:])
	init1(m.shape[:])
	init1(m.dir[:])
	init1(m.mvdZero[:])
	init1(m.cbpLuma[:])
	init1(m.cbpChroma[:])
	for i := 0; i < 2; i++ {
		init1(m.mvdMag[i][:])
	}
	for s := 0; s < 4; s++ {
		init1(m.cbf[s][:])
		init1(m.sig[s][:])
		init1(m.last[s][:])
		init1(m.lv1[s][:])
		init1(m.lvN[s][:])
	}
	return m
}

// frameCtx is the per-frame state shared by encoder and decoder.
type frameCtx struct {
	typ      int
	qp       int
	deblock  bool
	dbOffset int
	mbW, mbH int
	w4, h4   int
	cur      *Frame
	ref      [2]*Frame // list0, list1
	grid     []Blk
	skipMB   []bool
	intraMB  []bool
	cbp8     []uint8 // luma 8x8 coded flags, (mbW*2)x(mbH*2)
	cbpC     [2][]bool
	nzC      [2][]bool // chroma 4x4 nz, (w4/2)x(h4/2)
	m        *models
}

func newFrameCtx(typ, qp, w, h int) *frameCtx {
	pw, ph := padTo16(w), padTo16(h)
	fc := &frameCtx{typ: typ, qp: qp, mbW: pw / 16, mbH: ph / 16}
	fc.w4, fc.h4 = pw/4, ph/4
	fc.grid = make([]Blk, fc.w4*fc.h4)
	fc.skipMB = make([]bool, fc.mbW*fc.mbH)
	fc.intraMB = make([]bool, fc.mbW*fc.mbH)
	fc.cbp8 = make([]uint8, fc.mbW*2*fc.mbH*2)
	for i := 0; i < 2; i++ {
		fc.cbpC[i] = make([]bool, fc.mbW*fc.mbH)
		fc.nzC[i] = make([]bool, (fc.w4/2)*(fc.h4/2))
	}
	fc.m = newModels()
	return fc
}

func (fc *frameCtx) blk(bx, by int) *Blk { return &fc.grid[by*fc.w4+bx] }

func b2i(b bool) int {
	if b {
		return 1
	}
	return 0
}

func median3(a, b, c int) int {
	if a > b {
		a, b = b, a
	}
	if b > c {
		b = c
	}
	if a > b {
		return a
	}
	return b
}

// mvPred is the median motion-vector predictor for list l of the partition
// whose top-left is the 4x4 block (bx,by) and which is bw blocks wide.
func (fc *frameCtx) mvPred(l, bx, by, bw int) MV {
	get := func(x, y int) (MV, bool) {
		if x < 0 || y < 0 || x >= fc.w4 || y >= fc.h4 {
			return MV{}, false
		}
		b := fc.blk(x, y)
		if !b.Done {
			return MV{}, false
		}
		if b.Use&(1<<uint(l)) == 0 {
			return MV{}, true
		}
		return b.MV[l], true
	}
	a, aok := get(bx-1, by)
	b, bok := get(bx, by-1)
	c, cok := get(bx+bw, by-1)
	if !cok {
		c, cok = get(bx-1, by-1)
	}
	if !bok && !cok && aok {
		return a
	}
	return MV{
		int16(median3(int(a.X), int(b.X), int(c.X))),
		int16(median3(int(a.Y), int(b.Y), int(c.Y))),
	}
}

var errSyntax = errors.New("reel: invalid macroblock syntax")

// ------------------------------------------------------------ syntax coding

// codeMVDComp codes one motion-vector-difference component.
func codeMVDComp(io bitIO, m *models, comp, v int) int {
	z := io.bit(&m.mvdZero[comp], b2i(v == 0))
	if z == 1 {
		return 0
	}
	sign := io.bypass(b2i(v < 0))
	a := iabs(v) - 1
	k := 0
	for ; k < 8; k++ {
		c := &m.mvdMag[comp][imin(k, 5)]
		if io.bit(c, b2i(a > k)) == 0 {
			break
		}
	}
	mag := k
	if k == 8 {
		mag = 8 + codeEG(io, a-8, 1)
	}
	mag++
	if sign == 1 {
		return -mag
	}
	return mag
}

// codeBlock codes one 4x4 block of levels (scan order). set selects the
// context family. lev is read when encoding and written when decoding.
// Returns whether the block has any non-zero level.
func codeBlock(io bitIO, m *models, set, cbfCtx int, lev *[16]int32) bool {
	last := -1
	for i := 15; i >= 0; i-- {
		if lev[i] != 0 {
			last = i
			break
		}
	}
	if io.bit(&m.cbf[set][cbfCtx], b2i(last >= 0)) == 0 {
		*lev = [16]int32{}
		return false
	}
	var out [16]int32
	var pos [16]int
	n := 0
	for i := 0; i < 16; i++ {
		if i < 15 {
			if io.bit(&m.sig[set][i], b2i(lev[i] != 0)) == 0 {
				continue
			}
		}
		pos[n] = i
		n++
		if i < 15 {
			if io.bit(&m.last[set][i], b2i(i == last)) == 1 {
				break
			}
		}
	}
	eq1, gt1 := 0, 0
	for k := n - 1; k >= 0; k-- {
		i := pos[k]
		v := int(lev[i])
		a := iabs(v)
		var c1 int
		if gt1 > 0 {
			c1 = 0
		} else {
			c1 = imin(4, 1+eq1)
		}
		if io.bit(&m.lv1[set][c1], b2i(a > 1)) == 0 {
			a = 1
			eq1++
		} else {
			r := a - 2
			j := 0
			for ; j < 12; j++ {
				if io.bit(&m.lvN[set][imin(j, 5)], b2i(r > j)) == 0 {
					break
				}
			}
			if j == 12 {
				j = 12 + codeEG(io, r-12, 0)
			}
			a = j + 2
			gt1++
		}
		s := io.bypass(b2i(v < 0))
		if s == 1 {
			out[i] = int32(-a)
		} else {
			out[i] = int32(a)
		}
	}
	*lev = out
	return true
}

// resetMBState clears the per-MB residual flags before (re)coding an MB.
func (fc *frameCtx) clearNZ(mx, my int) {
	for j := 0; j < 4; j++ {
		for i := 0; i < 4; i++ {
			fc.blk(mx*4+i, my*4+j).NZ = false
		}
	}
	for c := 0; c < 2; c++ {
		for j := 0; j < 2; j++ {
			for i := 0; i < 2; i++ {
				fc.nzC[c][(my*2+j)*(fc.w4/2)+mx*2+i] = false
			}
		}
		fc.cbpC[c][my*fc.mbW+mx] = false
	}
	for j := 0; j < 2; j++ {
		for i := 0; i < 2; i++ {
			fc.cbp8[(my*2+j)*fc.mbW*2+mx*2+i] = 0
		}
	}
}

// setPartGrid records a partition's motion in the 4x4 grid.
func (fc *frameCtx) setPartGrid(mx, my int, r [4]int, p Part, intra bool) {
	for j := 0; j < r[3]; j++ {
		for i := 0; i < r[2]; i++ {
			b := fc.blk(mx*4+r[0]+i, my*4+r[1]+j)
			b.Done = true
			b.Intra = intra
			b.Use = uint8(p.Dir)
			b.MV = p.MV
			if intra {
				b.Use = 0
				b.MV = [2]MV{}
			}
		}
	}
}

func (fc *frameCtx) skipParts(mx, my int) Part {
	var p Part
	if fc.typ == FrameB {
		p.Dir = 3
		p.MV[0] = fc.mvPred(0, mx*4, my*4, 4)
		p.MV[1] = fc.mvPred(1, mx*4, my*4, 4)
	} else {
		p.Dir = 1
		p.MV[0] = fc.mvPred(0, mx*4, my*4, 4)
	}
	return p
}

func mvOK(v MV) bool {
	return int(v.X) >= -maxMV && int(v.X) <= maxMV && int(v.Y) >= -maxMV && int(v.Y) <= maxMV
}

// codeMB codes (encoder) or parses (decoder) one macroblock. The grid, skip,
// cbp and nz state for the macroblock is updated identically on both sides.
func (fc *frameCtx) codeMB(io bitIO, mb *MB, mx, my int) error {
	m := fc.m
	mi := my*fc.mbW + mx
	fc.clearNZ(mx, my)
	leftSkip := mx > 0 && fc.skipMB[mi-1]
	topSkip := my > 0 && fc.skipMB[mi-fc.mbW]
	leftIntra := mx > 0 && fc.intraMB[mi-1]
	topIntra := my > 0 && fc.intraMB[mi-fc.mbW]

	if fc.typ != FrameI {
		mb.Skip = io.bit(&m.skip[b2i(leftSkip)+b2i(topSkip)], b2i(mb.Skip)) == 1
		if mb.Skip {
			p := fc.skipParts(mx, my)
			mb.Intra, mb.Shape = false, 0
			mb.Parts = [4]Part{p}
			mb.CBP = 0
			mb.Lev = [24][16]int32{}
			fc.skipMB[mi] = true
			fc.intraMB[mi] = false
			fc.setPartGrid(mx, my, partRects[0][0], p, false)
			return io.err()
		}
		mb.Intra = io.bit(&m.intra[b2i(leftIntra)+b2i(topIntra)], b2i(mb.Intra)) == 1
	} else {
		mb.Intra = true
	}
	fc.skipMB[mi] = false
	fc.intraMB[mi] = mb.Intra

	if mb.Intra {
		haveLeft, haveTop := mx > 0, my > 0
		hi := io.bit(&m.imode[0], mb.IMode>>1)
		lo := io.bit(&m.imode[1+hi], mb.IMode&1)
		mb.IMode = hi<<1 | lo
		hi = io.bit(&m.cmode[0], mb.CMode>>1)
		lo = io.bit(&m.cmode[1+hi], mb.CMode&1)
		mb.CMode = hi<<1 | lo
		if !intraModeLegal(mb.IMode, haveLeft, haveTop) || !intraModeLegal(mb.CMode, haveLeft, haveTop) {
			return fmt.Errorf("%w: illegal intra mode %d/%d at MB (%d,%d)", errSyntax, mb.IMode, mb.CMode, mx, my)
		}
		fc.setPartGrid(mx, my, [4]int{0, 0, 4, 4}, Part{}, true)
	} else {
		// partition shape
		sh := 0
		if io.bit(&m.shape[0], b2i(mb.Shape != 0)) == 1 {
			sh = 1
			if io.bit(&m.shape[1], b2i(mb.Shape != 1)) == 1 {
				sh = 2 + io.bit(&m.shape[2], b2i(mb.Shape == 3))
			}
		}
		mb.Shape = sh
		for pi, r := range partRects[sh] {
			p := &mb.Parts[pi]
			// prediction direction
			if fc.typ == FrameB {
				sym := 0
				if p.Dir == 3 {
					sym = 2
				} else if p.Dir == 2 {
					sym = 1
				}
				if io.bit(&m.dir[0], b2i(sym == 2)) == 1 {
					sym = 2
				} else {
					sym = io.bit(&m.dir[1], b2i(sym == 1))
				}
				p.Dir = [3]int{1, 2, 3}[sym]
			} else {
				p.Dir = 1
			}
			for l := 0; l < 2; l++ {
				if p.Dir&(1<<uint(l)) == 0 {
					p.MV[l] = MV{}
					continue
				}
				if fc.ref[l] == nil {
					return fmt.Errorf("%w: list %d referenced but unavailable", errSyntax, l)
				}
				pred := fc.mvPred(l, mx*4+r[0], my*4+r[1], r[2])
				dx := codeMVDComp(io, m, 0, int(p.MV[l].X)-int(pred.X))
				dy := codeMVDComp(io, m, 1, int(p.MV[l].Y)-int(pred.Y))
				mv := MV{int16(int(pred.X) + dx), int16(int(pred.Y) + dy)}
				if !mvOK(mv) {
					return fmt.Errorf("%w: motion vector (%d,%d) out of range", errSyntax, mv.X, mv.Y)
				}
				p.MV[l] = mv
			}
			fc.setPartGrid(mx, my, r, *p, false)
		}
	}
	if err := io.err(); err != nil {
		return err
	}

	// ---- coded block pattern
	w8 := fc.mbW * 2
	cbp := 0
	for g := 0; g < 4; g++ {
		gx, gy := mx*2+g&1, my*2+g>>1
		var a, b uint8
		if gx > 0 {
			a = fc.cbp8[gy*w8+gx-1]
		}
		if gy > 0 {
			b = fc.cbp8[(gy-1)*w8+gx]
		}
		bit := io.bit(&m.cbpLuma[int(a+b)], (mb.CBP>>uint(g))&1)
		fc.cbp8[gy*w8+gx] = uint8(bit)
		cbp |= bit << uint(g)
	}
	for c := 0; c < 2; c++ {
		ctx := 0
		if mx > 0 && fc.cbpC[c][mi-1] {
			ctx++
		}
		if my > 0 && fc.cbpC[c][mi-fc.mbW] {
			ctx++
		}
		bit := io.bit(&m.cbpChroma[ctx], (mb.CBP>>uint(4+c))&1)
		fc.cbpC[c][mi] = bit == 1
		cbp |= bit << uint(4+c)
	}
	mb.CBP = cbp

	// ---- residual
	lset, cset := 1, 3
	if mb.Intra {
		lset, cset = 0, 2
	}
	for g := 0; g < 4; g++ {
		if cbp>>uint(g)&1 == 0 {
			for k := 0; k < 4; k++ {
				mb.Lev[lumaBlkIndex(g, k)] = [16]int32{}
			}
			continue
		}
		for k := 0; k < 4; k++ {
			bi := lumaBlkIndex(g, k)
			bx, by := mx*4+bi&3, my*4+bi>>2
			ctx := 0
			if bx > 0 && fc.blk(bx-1, by).NZ {
				ctx++
			}
			if by > 0 && fc.blk(bx, by-1).NZ {
				ctx++
			}
			fc.blk(bx, by).NZ = codeBlock(io, m, lset, ctx, &mb.Lev[bi])
		}
	}
	cw4 := fc.w4 / 2
	for c := 0; c < 2; c++ {
		for k := 0; k < 4; k++ {
			bi := 16 + c*4 + k
			if cbp>>uint(4+c)&1 == 0 {
				mb.Lev[bi] = [16]int32{}
				continue
			}
			cx, cy := mx*2+k&1, my*2+k>>1
			ctx := 0
			if cx > 0 && fc.nzC[c][cy*cw4+cx-1] {
				ctx++
			}
			if cy > 0 && fc.nzC[c][(cy-1)*cw4+cx] {
				ctx++
			}
			fc.nzC[c][cy*cw4+cx] = codeBlock(io, m, cset, ctx, &mb.Lev[bi])
		}
	}
	return io.err()
}

// lumaBlkIndex maps (8x8 group g, sub-block k) to the raster 4x4 index 0..15.
func lumaBlkIndex(g, k int) int {
	gx, gy := (g&1)*2, (g>>1)*2
	return (gy+k>>1)*4 + gx + k&1
}
