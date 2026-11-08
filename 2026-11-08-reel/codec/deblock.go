package codec

import "math"

// In-loop deblocking filter. Boundary strength bS is derived from the coding
// state of the two 4x4 blocks that meet at an edge:
//   3 — either side intra;  2 — either side has coded residual;
//   1 — motion differs by >= 1 pel (or different prediction lists);  0 — no filtering.
// alpha/beta thresholds grow with QP (flat for QP < 16, where blocking is invisible).

var alphaTab = [52]int{}
var betaTab = [52]int{}
var tc0Tab = [4][52]int{}

func init() {
	alpha := []int{4, 4, 5, 6, 7, 8, 9, 10, 12, 13, 15, 17, 20, 22, 25, 28, 32, 36, 40, 45, 50, 56, 63, 71, 80, 90, 101, 113, 127, 144, 162, 182, 203, 226, 255, 255}
	beta := []int{2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18}
	if len(alpha) != 36 || len(beta) != 36 {
		panic("deblock tables")
	}
	mult := [4]float64{0, 1.0, 1.5, 2.2}
	for i := 16; i < 52; i++ {
		alphaTab[i] = alpha[i-16]
		betaTab[i] = beta[i-16]
	}
	for bs := 1; bs <= 3; bs++ {
		for i := 0; i < 52; i++ {
			base := 0.55 * math.Pow(2, float64(i-24)/6)
			if i < 17 {
				base = 0
			}
			tc0Tab[bs][i] = int(base*mult[bs] + 0.5)
		}
	}
}

func (fc *frameCtx) boundaryStrength(p, q *Blk) int {
	if p.Intra || q.Intra {
		return 3
	}
	if p.NZ || q.NZ {
		return 2
	}
	if p.Use != q.Use {
		return 1
	}
	for l := 0; l < 2; l++ {
		if p.Use&(1<<uint(l)) == 0 {
			continue
		}
		if iabs(int(p.MV[l].X)-int(q.MV[l].X)) >= 4 || iabs(int(p.MV[l].Y)-int(q.MV[l].Y)) >= 4 {
			return 1
		}
	}
	return 0
}

func clip3(lo, hi, v int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// filterLine filters one line of samples across an edge. s is the pixel slice,
// i the index of q0, st the step across the edge (1 for a vertical edge).
func filterLine(s []uint8, i, st, alpha, beta, tc0 int, luma bool) {
	p0, p1, q0, q1 := int(s[i-st]), int(s[i-2*st]), int(s[i]), int(s[i+st])
	if iabs(p0-q0) >= alpha || iabs(p1-p0) >= beta || iabs(q1-q0) >= beta {
		return
	}
	tc := tc0 + 1
	var ap, aq int
	var p2, q2 int
	if luma {
		p2, q2 = int(s[i-3*st]), int(s[i+2*st])
		ap, aq = iabs(p2-p0), iabs(q2-q0)
		tc = tc0
		if ap < beta {
			tc++
		}
		if aq < beta {
			tc++
		}
	}
	delta := clip3(-tc, tc, (((q0-p0)<<2)+(p1-q1)+4)>>3)
	s[i-st] = clip255(p0 + delta)
	s[i] = clip255(q0 - delta)
	if luma {
		if ap < beta {
			s[i-2*st] = uint8(p1 + clip3(-tc0, tc0, (p2+((p0+q0+1)>>1)-(p1<<1))>>1))
		}
		if aq < beta {
			s[i+st] = uint8(q1 + clip3(-tc0, tc0, (q2+((p0+q0+1)>>1)-(q1<<1))>>1))
		}
	}
}

// deblockFrame applies the loop filter to fc.cur.
func (fc *frameCtx) deblockFrame() {
	idxA := clampi(fc.qp+fc.dbOffset, 0, 51)
	alpha, beta := alphaTab[idxA], betaTab[idxA]
	if alpha == 0 || beta == 0 {
		return
	}
	Y, U, V := fc.cur.Y, fc.cur.U, fc.cur.V
	// vertical edges first (filtering across x), then horizontal.
	for dir := 0; dir < 2; dir++ {
		for by := 0; by < fc.h4; by++ {
			for bx := 0; bx < fc.w4; bx++ {
				var p, q *Blk
				if dir == 0 {
					if bx == 0 {
						continue
					}
					p, q = fc.blk(bx-1, by), fc.blk(bx, by)
				} else {
					if by == 0 {
						continue
					}
					p, q = fc.blk(bx, by-1), fc.blk(bx, by)
				}
				bs := fc.boundaryStrength(p, q)
				if bs == 0 {
					continue
				}
				tc0 := tc0Tab[bs][idxA]
				for k := 0; k < 4; k++ {
					if dir == 0 {
						filterLine(Y.Pix, Y.idx(bx*4, by*4+k), 1, alpha, beta, tc0, true)
					} else {
						filterLine(Y.Pix, Y.idx(bx*4+k, by*4), Y.Stride, alpha, beta, tc0, true)
					}
				}
				// chroma edges sit on every 8th luma sample.
				if (dir == 0 && bx%2 == 0) || (dir == 1 && by%2 == 0) {
					for k := 0; k < 2; k++ {
						for _, pl := range []*Plane{U, V} {
							if dir == 0 {
								filterLine(pl.Pix, pl.idx(bx*2, by*2+k), 1, alpha, beta, tc0, false)
							} else {
								filterLine(pl.Pix, pl.idx(bx*2+k, by*2), pl.Stride, alpha, beta, tc0, false)
							}
						}
					}
				}
			}
		}
	}
}
