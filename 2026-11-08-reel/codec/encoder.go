package codec

import (
	"errors"
	"fmt"
	"math"
	"math/bits"
)

// EncParams configures the encoder.
type EncParams struct {
	QP       int  // base quantiser (used when Bitrate == 0)
	GOP      int  // I-frame interval in frames (0 = only the first frame is intra)
	BFrames  int  // consecutive B-frames between anchors (0 = none)
	Range    int  // integer-pel search range (<= 40)
	Search   int  // SearchFull or SearchDiamond
	SubPel   int  // 0 integer, 1 half-pel, 2 quarter-pel
	Deblock  bool // in-loop deblocking filter
	DbOffset int  // filter strength offset added to QP
	Effort   int  // 0 fast (16x16 only), 1 full RDO (all partitions, intra in P/B)
	SceneCut bool // insert I-frames at detected scene changes
	Bitrate  int  // target kbit/s; 0 = constant QP
}

// DefaultParams returns the recommended configuration.
func DefaultParams() EncParams {
	return EncParams{QP: 28, GOP: 30, BFrames: 0, Range: 16, Search: SearchDiamond,
		SubPel: 2, Deblock: true, Effort: 1, SceneCut: true}
}

// Validate checks parameter ranges.
func (p EncParams) Validate() error {
	switch {
	case p.QP < MinQP || p.QP > MaxQP:
		return fmt.Errorf("qp %d out of range %d..%d", p.QP, MinQP, MaxQP)
	case p.GOP < 0:
		return errors.New("gop must be >= 0")
	case p.BFrames < 0 || p.BFrames > 4:
		return errors.New("bframes must be 0..4")
	case p.Range < 0 || p.Range > 40:
		return errors.New("range must be 0..40")
	case p.Search != SearchFull && p.Search != SearchDiamond:
		return errors.New("unknown search algorithm")
	case p.SubPel < 0 || p.SubPel > 2:
		return errors.New("subpel must be 0..2")
	case p.Effort < 0 || p.Effort > 1:
		return errors.New("effort must be 0 or 1")
	case p.DbOffset < -12 || p.DbOffset > 12:
		return errors.New("deblock offset must be -12..12")
	case p.Bitrate < 0:
		return errors.New("bitrate must be >= 0")
	}
	return nil
}

// EncResult is everything an encode produces.
type EncResult struct {
	Stream   []byte
	Stats    []FrameStat // coding order
	Recon    []*Frame    // display order: the encoder's own reconstruction
	Bytes    int
	SADEvals int
}

type enc struct {
	p      EncParams
	src    *Frame
	fc     *frameCtx
	evals  int
	prevMV []MV
	lam    float64
	lamSAD float64
}

func lambdaFor(qp int) float64 { return 0.85 * math.Pow(2, float64(qp-12)/3) }

// ---------------------------------------------------------------- residual

type planeRes struct {
	lev  [16][16]int32 // scan-order levels per block slot within the plane
	cbp  int           // bit g set => group g has coded residual
	rec  [256]uint8    // reconstructed samples, stride = block size
	ssd  float64
	bits float64
}

func blockBitsEst(lev *[16]int32) float64 {
	last := -1
	b := 0.0
	for i := 0; i < 16; i++ {
		if lev[i] != 0 {
			last = i
			a := iabs(int(lev[i]))
			b += 2.2 + 2*float64(bits.Len(uint(a))-1) + 0.4*float64(bits.Len(uint(a)))
		}
	}
	if last < 0 {
		return 0.3
	}
	return b + 1.5 + 0.5*float64(last+1)
}

// resid quantises and reconstructs plane pl of the macroblock against pred.
func (e *enc) resid(pl, mx, my int, pred []uint8, pst int, intra bool, out *planeRes) {
	fc := e.fc
	src := e.src.planes()[pl]
	n, px, py, groups := 16, mx*16, my*16, 4
	if pl > 0 {
		n, px, py, groups = 8, mx*8, my*8, 1
	}
	out.ssd, out.bits, out.cbp = 0, 0, 0
	for g := 0; g < groups; g++ {
		var lev [4][16]int32 // scan order
		var recG [4][16]uint8
		var ssdWith, ssdWo, bitsWith float64
		anyNZ := false
		var bxs, bys [4]int
		for k := 0; k < 4; k++ {
			var gx, gy int
			if pl == 0 {
				gx, gy = (g&1)*2+(k&1), (g>>1)*2+(k>>1)
			} else {
				gx, gy = k&1, k>>1
			}
			bxs[k], bys[k] = gx*4, gy*4
			var in, w, lv, dq, res [16]int32
			for j := 0; j < 4; j++ {
				si := src.idx(px+gx*4, py+gy*4+j)
				for i := 0; i < 4; i++ {
					in[j*4+i] = int32(src.Pix[si+i]) - int32(pred[(gy*4+j)*pst+gx*4+i])
				}
			}
			fdct4(&in, &w)
			nz := quant(&w, &lv, fc.qp, intra)
			for i := 0; i < 16; i++ {
				ssdWo += float64(in[i]) * float64(in[i])
			}
			if nz > 0 {
				anyNZ = true
				dequant(&lv, &dq, fc.qp)
				idct4(&dq, &res)
			}
			for i := 0; i < 16; i++ {
				lev[k][i] = lv[zigzag[i]]
				p := int32(pred[(gy*4+i>>2)*pst+gx*4+i&3])
				r := clip255(int(p + res[i]))
				recG[k][i] = r
				d := float64(int32(src.Pix[src.idx(px+gx*4+i&3, py+gy*4+i>>2)]) - int32(r))
				ssdWith += d * d
			}
			bitsWith += blockBitsEst(&lev[k])
		}
		useRes := anyNZ
		if anyNZ && e.p.Effort >= 1 {
			jw := ssdWith + e.lam*(bitsWith+1.5)
			jo := ssdWo + e.lam*0.3
			if jo <= jw {
				useRes = false
			}
		}
		for k := 0; k < 4; k++ {
			slot := g*4 + k
			if useRes {
				out.lev[slot] = lev[k]
			} else {
				out.lev[slot] = [16]int32{}
			}
			for i := 0; i < 16; i++ {
				var v uint8
				if useRes {
					v = recG[k][i]
				} else {
					v = pred[(bys[k]+i>>2)*pst+bxs[k]+i&3]
				}
				out.rec[(bys[k]+i>>2)*n+bxs[k]+i&3] = v
			}
		}
		if useRes {
			out.cbp |= 1 << uint(g)
			out.ssd += ssdWith
			out.bits += bitsWith + 1.5
		} else {
			out.ssd += ssdWo
			out.bits += 0.3
		}
	}
}

// putPlane stores a plane residual into mb (luma: slots by group, chroma: planes 1/2).
func (mb *MB) putPlane(pl int, r *planeRes) {
	if pl == 0 {
		for g := 0; g < 4; g++ {
			for k := 0; k < 4; k++ {
				mb.Lev[lumaBlkIndex(g, k)] = r.lev[g*4+k]
			}
		}
		mb.CBP = mb.CBP&^0xF | r.cbp
		return
	}
	for k := 0; k < 4; k++ {
		mb.Lev[16+(pl-1)*4+k] = r.lev[k]
	}
	mb.CBP = mb.CBP&^(1<<uint(3+pl)) | (r.cbp&1)<<uint(3+pl)
}

// ------------------------------------------------------------ mode decision

func (e *enc) ssdPred(mx, my int, pb *predBuf) float64 {
	var s float64
	for pl := 0; pl < 3; pl++ {
		buf, st := pb.plane(pl)
		src := e.src.planes()[pl]
		n, px, py := 16, mx*16, my*16
		if pl > 0 {
			n, px, py = 8, mx*8, my*8
		}
		for j := 0; j < n; j++ {
			si := src.idx(px, py+j)
			for i := 0; i < n; i++ {
				d := float64(int(src.Pix[si+i]) - int(buf[j*st+i]))
				s += d * d
			}
		}
	}
	return s
}

// evalFull computes the RD cost of an MB whose prediction is in pb.
func (e *enc) evalFull(mb *MB, mx, my int, pb *predBuf, intra bool, side float64) float64 {
	var rs [3]planeRes
	J := 0.0
	mb.CBP = 0
	for pl := 0; pl < 3; pl++ {
		buf, st := pb.plane(pl)
		e.resid(pl, mx, my, buf, st, intra, &rs[pl])
		mb.putPlane(pl, &rs[pl])
		J += rs[pl].ssd + e.lam*rs[pl].bits
	}
	return J + e.lam*side
}

func (e *enc) evalIntra(mx, my int) (MB, float64) {
	fc := e.fc
	var mb MB
	mb.Intra = true
	haveLeft, haveTop := mx > 0, my > 0
	var pred [256]uint8
	var bestL planeRes
	bestLJ, bestCJ := math.Inf(1), math.Inf(1)
	var tr, tu, tv planeRes
	for mode := 0; mode < numIntraModes; mode++ {
		if !intraModeLegal(mode, haveLeft, haveTop) {
			continue
		}
		predictIntra(fc.cur.Y, mx*16, my*16, 16, mode, pred[:])
		e.resid(0, mx, my, pred[:], 16, true, &tr)
		if J := tr.ssd + e.lam*(tr.bits+1.5); J < bestLJ {
			bestLJ, bestL, mb.IMode = J, tr, mode
		}
		predictIntra(fc.cur.U, mx*8, my*8, 8, mode, pred[:])
		e.resid(1, mx, my, pred[:64], 8, true, &tu)
		predictIntra(fc.cur.V, mx*8, my*8, 8, mode, pred[:])
		e.resid(2, mx, my, pred[:64], 8, true, &tv)
		if J := tu.ssd + tv.ssd + e.lam*(tu.bits+tv.bits+1.5); J < bestCJ {
			bestCJ, mb.CMode = J, mode
			mb.putPlane(1, &tu)
			mb.putPlane(2, &tv)
		}
	}
	mb.putPlane(0, &bestL)
	return mb, bestLJ + bestCJ + e.lam*3
}

// candidate vectors for list l around a partition.
func (e *enc) mvCands(l, bx, by, bw int, pred MV, mi int) []MV {
	fc := e.fc
	c := []MV{pred}
	add := func(x, y int) {
		if x < 0 || y < 0 || x >= fc.w4 || y >= fc.h4 {
			return
		}
		b := fc.blk(x, y)
		if b.Done && b.Use&(1<<uint(l)) != 0 {
			c = append(c, b.MV[l])
		}
	}
	add(bx-1, by)
	add(bx, by-1)
	add(bx+bw, by-1)
	if l == 0 && e.prevMV != nil {
		c = append(c, e.prevMV[mi])
	}
	return c
}

// searchPart chooses prediction direction(s) and vectors for one partition.
func (e *enc) searchPart(mx, my int, r [4]int) (Part, float64) {
	fc := e.fc
	px, py, w, h := mx*16+r[0]*4, my*16+r[1]*4, r[2]*4, r[3]*4
	mi := my*fc.mbW + mx
	nl := 1
	if fc.typ == FrameB {
		nl = 2
	}
	var mvs [2]MV
	var cost [2]float64
	var preds [2]MV
	for l := 0; l < nl; l++ {
		preds[l] = fc.mvPred(l, mx*4+r[0], my*4+r[1], r[2])
		s := &searcher{src: e.src.Y, ref: fc.ref[l].Y, px: px, py: py, w: w, h: h,
			pred: preds[l], lam: e.lamSAD, algo: e.p.Search, subpel: e.p.SubPel,
			rng: e.p.Range, evals: &e.evals}
		mvs[l], cost[l] = s.run(e.mvCands(l, mx*4+r[0], my*4+r[1], r[2], preds[l], mi))
	}
	if nl == 1 {
		return Part{Dir: 1, MV: [2]MV{mvs[0]}}, cost[0]
	}
	// bi-prediction candidate
	var a, b [256]uint8
	predLuma(fc.ref[0].Y, px*4+int(mvs[0].X), py*4+int(mvs[0].Y), w, h, a[:])
	predLuma(fc.ref[1].Y, px*4+int(mvs[1].X), py*4+int(mvs[1].Y), w, h, b[:])
	for i := 0; i < w*h; i++ {
		a[i] = uint8((int(a[i]) + int(b[i]) + 1) >> 1)
	}
	e.evals++
	biCost := float64(sadPred(e.src.Y, px, py, a[:w*h], w, h)) +
		e.lamSAD*(mvdBits(int(mvs[0].X)-int(preds[0].X), int(mvs[0].Y)-int(preds[0].Y))+
			mvdBits(int(mvs[1].X)-int(preds[1].X), int(mvs[1].Y)-int(preds[1].Y))) + e.lamSAD*1.0
	best, dir := cost[0], 1
	if cost[1] < best {
		best, dir = cost[1], 2
	}
	if biCost < best {
		best, dir = biCost, 3
	}
	p := Part{Dir: dir}
	if dir&1 != 0 {
		p.MV[0] = mvs[0]
	}
	if dir&2 != 0 {
		p.MV[1] = mvs[1]
	}
	return p, best
}

func (e *enc) evalInter(mx, my, shape int) (MB, float64) {
	fc := e.fc
	var mb MB
	mb.Shape = shape
	// forget tentative state of this macroblock
	for j := 0; j < 4; j++ {
		for i := 0; i < 4; i++ {
			*fc.blk(mx*4+i, my*4+j) = Blk{}
		}
	}
	side := 2.0
	if shape > 0 {
		side += 2
	}
	for pi, r := range partRects[shape] {
		p, _ := e.searchPart(mx, my, r)
		mb.Parts[pi] = p
		fc.setPartGrid(mx, my, r, p, false)
		for l := 0; l < 2; l++ {
			if p.Dir&(1<<uint(l)) != 0 {
				pr := fc.mvPred(l, mx*4+r[0], my*4+r[1], r[2])
				side += mvdBits(int(p.MV[l].X)-int(pr.X), int(p.MV[l].Y)-int(pr.Y))
			}
		}
		if fc.typ == FrameB {
			side += 1.5
		}
	}
	var pb predBuf
	fc.predictInterMB(&mb, mx, my, &pb)
	J := e.evalFull(&mb, mx, my, &pb, false, side)
	return mb, J
}

// chooseMB picks the cheapest coding of the macroblock at (mx,my).
func (e *enc) chooseMB(mx, my int) MB {
	fc := e.fc
	if fc.typ == FrameI {
		mb, _ := e.evalIntra(mx, my)
		return mb
	}
	// skip candidate
	var skip MB
	skip.Skip = true
	skip.Parts[0] = fc.skipParts(mx, my)
	var pb predBuf
	fc.predictInterMB(&skip, mx, my, &pb)
	ssd := e.ssdPred(mx, my, &pb)
	Jskip := ssd + e.lam*0.4
	if ssd < 3*e.lam {
		return skip
	}
	best, bestJ := skip, Jskip
	shapes := []int{0}
	if e.p.Effort >= 1 {
		shapes = []int{0, 1, 2, 3}
	}
	for _, sh := range shapes {
		mb, J := e.evalInter(mx, my, sh)
		if J < bestJ {
			best, bestJ = mb, J
		}
	}
	// intra: always when effort>=1, otherwise only if inter looks poor
	if e.p.Effort >= 1 || bestJ > e.lam*60 {
		mb, J := e.evalIntra(mx, my)
		if J < bestJ {
			best, bestJ = mb, J
		}
	}
	return best
}

// ------------------------------------------------------------ frame coding

func (e *enc) encodeFrame(src *Frame, typ int, refs [2]*Frame, qp, disp int) ([]byte, *Frame, FrameStat) {
	e.src = src
	fc := newFrameCtx(typ, qp, src.Width, src.Height)
	fc.deblock = e.p.Deblock
	fc.dbOffset = e.p.DbOffset
	fc.ref = refs
	fc.cur = NewFrame(src.Width, src.Height)
	fc.cur.Disp = disp
	e.fc = fc
	e.lam = lambdaFor(qp)
	e.lamSAD = math.Sqrt(e.lam)
	startEvals := e.evals
	rc := newRCEnc()
	st := FrameStat{Type: typ, Disp: disp, QP: qp, Deblock: fc.deblock}
	newPrev := make([]MV, fc.mbW*fc.mbH)
	for my := 0; my < fc.mbH; my++ {
		for mx := 0; mx < fc.mbW; mx++ {
			mb := e.chooseMB(mx, my)
			if err := fc.codeMB(rc, &mb, mx, my); err != nil {
				panic("encoder produced invalid syntax: " + err.Error())
			}
			fc.reconMB(&mb, mx, my)
			st.count(&mb)
			if !mb.Intra {
				newPrev[my*fc.mbW+mx] = mb.Parts[0].MV[0]
			}
		}
	}
	if fc.deblock {
		fc.deblockFrame()
	}
	fc.cur.extend()
	if typ != FrameB {
		e.prevMV = newPrev
	}
	payload := rc.finish()
	hdr := putFrameHeader(typ, fc.deblock, qp, fc.dbOffset, disp, payload)
	st.Bytes = len(hdr) + len(payload)
	st.SADEvals = e.evals - startEvals
	st.PSNRY, st.PSNRU, st.PSNRV = PSNR(src, fc.cur)
	return append(hdr, payload...), fc.cur, st
}

// detectCuts flags frames that start a new scene.
func detectCuts(v *Video) []bool {
	n := len(v.Frames)
	cut := make([]bool, n)
	diff := make([]float64, n)
	for i := 1; i < n; i++ {
		a, b := v.Frames[i-1].Y, v.Frames[i].Y
		var s, c float64
		for y := 0; y < v.Height; y += 2 {
			for x := 0; x < v.Width; x += 2 {
				s += math.Abs(float64(a.Pix[a.idx(x, y)]) - float64(b.Pix[b.idx(x, y)]))
				c++
			}
		}
		diff[i] = s / c
		prev := 2.0
		if i > 1 {
			prev = math.Max(diff[i-1], 2)
		}
		if diff[i] > 30 || (diff[i] > 14 && diff[i] > 4*prev) {
			cut[i] = true
		}
	}
	return cut
}

type job struct {
	disp, typ int
}

// planGOP returns the coding order.
func planGOP(n int, p EncParams, cut []bool) []job {
	jobs := []job{{0, FrameI}}
	prev := 0
	for prev < n-1 {
		next := imin(prev+p.BFrames+1, n-1)
		if p.SceneCut {
			for k := prev + 1; k <= next; k++ {
				if cut[k] {
					next = k
					break
				}
			}
		}
		if p.GOP > 0 {
			nextI := (prev/p.GOP + 1) * p.GOP
			if nextI < next {
				next = nextI
			}
		}
		typ := FrameP
		if (p.GOP > 0 && next%p.GOP == 0) || (p.SceneCut && cut[next]) {
			typ = FrameI
		}
		jobs = append(jobs, job{next, typ})
		for d := prev + 1; d < next; d++ {
			jobs = append(jobs, job{d, FrameB})
		}
		prev = next
	}
	return jobs
}

// Encode compresses a video.
func Encode(v *Video, p EncParams) (*EncResult, error) {
	if err := p.Validate(); err != nil {
		return nil, err
	}
	n := len(v.Frames)
	if n == 0 {
		return nil, errors.New("encode: no frames")
	}
	if v.Width < 16 || v.Height < 16 || v.Width > maxDim || v.Height > maxDim {
		return nil, fmt.Errorf("encode: unsupported size %dx%d", v.Width, v.Height)
	}
	var cut []bool
	if p.SceneCut {
		cut = detectCuts(v)
	} else {
		cut = make([]bool, n)
	}
	jobs := planGOP(n, p, cut)
	e := &enc{p: p}
	res := &EncResult{Recon: make([]*Frame, n)}
	out := putHeader(streamHeader{v.Width, v.Height, v.FPSNum, v.FPSDen, n})
	var anchors []*Frame
	rcn := newRateCtl(p, v, jobs)
	for _, j := range jobs {
		var refs [2]*Frame
		switch j.typ {
		case FrameP:
			refs[0] = anchors[len(anchors)-1]
		case FrameB:
			refs[0], refs[1] = anchors[len(anchors)-2], anchors[len(anchors)-1]
		}
		var data []byte
		var rec *Frame
		var st FrameStat
		qp := rcn.qpFor(j.typ)
		for attempt := 0; ; attempt++ {
			data, rec, st = e.encodeFrame(v.Frames[j.disp], j.typ, refs, qp, j.disp)
			if nq, again := rcn.retry(j.typ, qp, len(data)*8, attempt); again {
				qp = nq
				continue
			}
			break
		}
		rcn.update(j.typ, qp, len(data)*8)
		out = append(out, data...)
		res.Stats = append(res.Stats, st)
		res.Recon[j.disp] = rec
		if j.typ != FrameB {
			anchors = append(anchors, rec)
			if len(anchors) > 2 {
				anchors = anchors[1:]
			}
		}
	}
	res.Stream = out
	res.Bytes = len(out)
	res.SADEvals = e.evals
	return res, nil
}
