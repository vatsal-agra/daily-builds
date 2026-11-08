package codec

// predBuf holds the prediction of one macroblock.
type predBuf struct {
	Y [256]uint8
	U [64]uint8
	V [64]uint8
}

func (pb *predBuf) plane(i int) ([]uint8, int) {
	switch i {
	case 0:
		return pb.Y[:], 16
	case 1:
		return pb.U[:], 8
	}
	return pb.V[:], 8
}

// predictIntraMB fills pb with the intra prediction for mb at (mx,my).
func (fc *frameCtx) predictIntraMB(mb *MB, mx, my int, pb *predBuf) {
	predictIntra(fc.cur.Y, mx*16, my*16, 16, mb.IMode, pb.Y[:])
	predictIntra(fc.cur.U, mx*8, my*8, 8, mb.CMode, pb.U[:])
	predictIntra(fc.cur.V, mx*8, my*8, 8, mb.CMode, pb.V[:])
}

// predictPart writes the inter prediction of one partition into pb.
func (fc *frameCtx) predictPart(p Part, mx, my int, r [4]int, pb *predBuf) {
	lx, ly, lw, lh := mx*16+r[0]*4, my*16+r[1]*4, r[2]*4, r[3]*4
	cx, cy, cw, ch := mx*8+r[0]*2, my*8+r[1]*2, r[2]*2, r[3]*2
	var tl [2][256]uint8
	var tu, tv [2][64]uint8
	n := 0
	for l := 0; l < 2; l++ {
		if p.Dir&(1<<uint(l)) == 0 {
			continue
		}
		ref := fc.ref[l]
		mv := p.MV[l]
		predLuma(ref.Y, lx*4+int(mv.X), ly*4+int(mv.Y), lw, lh, tl[n][:])
		predChroma(ref.U, cx, cy, mv, cw, ch, tu[n][:])
		predChroma(ref.V, cx, cy, mv, cw, ch, tv[n][:])
		n++
	}
	put := func(dst []uint8, ds, ox, oy, w, h int, a, b []uint8) {
		for j := 0; j < h; j++ {
			for i := 0; i < w; i++ {
				v := int(a[j*w+i])
				if n == 2 {
					v = (v + int(b[j*w+i]) + 1) >> 1
				}
				dst[(oy+j)*ds+ox+i] = uint8(v)
			}
		}
	}
	put(pb.Y[:], 16, r[0]*4, r[1]*4, lw, lh, tl[0][:], tl[1][:])
	put(pb.U[:], 8, r[0]*2, r[1]*2, cw, ch, tu[0][:], tu[1][:])
	put(pb.V[:], 8, r[0]*2, r[1]*2, cw, ch, tv[0][:], tv[1][:])
}

// predictInterMB fills pb with the inter prediction for mb.
func (fc *frameCtx) predictInterMB(mb *MB, mx, my int, pb *predBuf) {
	for pi, r := range partRects[mb.Shape] {
		fc.predictPart(mb.Parts[pi], mx, my, r, pb)
	}
}

// predictMB dispatches on the macroblock kind.
func (fc *frameCtx) predictMB(mb *MB, mx, my int, pb *predBuf) {
	if mb.Intra {
		fc.predictIntraMB(mb, mx, my, pb)
	} else {
		fc.predictInterMB(mb, mx, my, pb)
	}
}

// residualBlock turns one block of scan-order levels into residual samples.
func residualBlock(lev *[16]int32, qp int, res *[16]int32) bool {
	any := false
	var raster, dq [16]int32
	for i := 0; i < 16; i++ {
		if lev[i] != 0 {
			any = true
		}
		raster[zigzag[i]] = lev[i]
	}
	if !any {
		*res = [16]int32{}
		return false
	}
	dequant(&raster, &dq, qp)
	idct4(&dq, res)
	return true
}

// blockOrigin returns, for residual block index bi, the plane index and the
// pixel offset inside the macroblock's prediction buffer.
func blockOrigin(bi int) (plane, ox, oy int) {
	if bi < 16 {
		return 0, (bi & 3) * 4, (bi >> 2) * 4
	}
	c := (bi - 16) / 4
	k := (bi - 16) % 4
	return 1 + c, (k & 1) * 4, (k >> 1) * 4
}

// reconMB reconstructs the macroblock into fc.cur from prediction + residual.
// Encoder and decoder both call this, which guarantees identical output.
func (fc *frameCtx) reconMB(mb *MB, mx, my int) {
	var pb predBuf
	fc.predictMB(mb, mx, my, &pb)
	planes := fc.cur.planes()
	// write prediction
	for i := 0; i < 3; i++ {
		buf, st := pb.plane(i)
		n, px, py := 16, mx*16, my*16
		if i > 0 {
			n, px, py = 8, mx*8, my*8
		}
		for j := 0; j < n; j++ {
			o := planes[i].idx(px, py+j)
			copy(planes[i].Pix[o:o+n], buf[j*st:j*st+n])
		}
	}
	// add residual
	var res [16]int32
	for bi := 0; bi < 24; bi++ {
		if !residualBlock(&mb.Lev[bi], fc.qp, &res) {
			continue
		}
		pl, ox, oy := blockOrigin(bi)
		px, py := mx*16+ox, my*16+oy
		if pl > 0 {
			px, py = mx*8+ox, my*8+oy
		}
		p := planes[pl]
		for j := 0; j < 4; j++ {
			o := p.idx(px, py+j)
			for i := 0; i < 4; i++ {
				p.Pix[o+i] = clip255(int(p.Pix[o+i]) + int(res[j*4+i]))
			}
		}
	}
}
