package codec

// Sub-pel motion compensation.
//
// Luma: quarter-pel. Half-pel samples use the 6-tap filter (1,-5,20,20,-5,1);
// quarter-pel samples are the rounded average of the two nearest integer/half
// samples (the H.264 scheme). Chroma: eighth-pel bilinear.

func tap6(a, b, c, d, e, f int) int { return a - 5*b + 20*c + 20*d - 5*e + f }

func (p *Plane) g(x, y int) int { return int(p.Pix[p.off+y*p.Stride+x]) }

// hraw is the unrounded horizontal half-pel value between (x,y) and (x+1,y).
func (p *Plane) hraw(x, y int) int {
	i := p.off + y*p.Stride + x
	s := p.Pix
	return tap6(int(s[i-2]), int(s[i-1]), int(s[i]), int(s[i+1]), int(s[i+2]), int(s[i+3]))
}

func (p *Plane) vraw(x, y int) int {
	i := p.off + y*p.Stride + x
	s := p.Pix
	st := p.Stride
	return tap6(int(s[i-2*st]), int(s[i-st]), int(s[i]), int(s[i+st]), int(s[i+2*st]), int(s[i+3*st]))
}

func (p *Plane) bH(x, y int) int { return int(clip255((p.hraw(x, y) + 16) >> 5)) }
func (p *Plane) hV(x, y int) int { return int(clip255((p.vraw(x, y) + 16) >> 5)) }
func (p *Plane) jC(x, y int) int {
	v := tap6(p.hraw(x, y-2), p.hraw(x, y-1), p.hraw(x, y), p.hraw(x, y+1), p.hraw(x, y+2), p.hraw(x, y+3))
	return int(clip255((v + 512) >> 10))
}

func avg(a, b int) int { return (a + b + 1) >> 1 }

// sampleQ returns the interpolated luma sample for integer base (x,y) and
// quarter-pel fraction (fx,fy).
func (p *Plane) sampleQ(x, y, fx, fy int) int {
	switch fy*4 + fx {
	case 0:
		return p.g(x, y)
	case 1:
		return avg(p.g(x, y), p.bH(x, y))
	case 2:
		return p.bH(x, y)
	case 3:
		return avg(p.bH(x, y), p.g(x+1, y))
	case 4:
		return avg(p.g(x, y), p.hV(x, y))
	case 5:
		return avg(p.bH(x, y), p.hV(x, y))
	case 6:
		return avg(p.bH(x, y), p.jC(x, y))
	case 7:
		return avg(p.bH(x, y), p.hV(x+1, y))
	case 8:
		return p.hV(x, y)
	case 9:
		return avg(p.hV(x, y), p.jC(x, y))
	case 10:
		return p.jC(x, y)
	case 11:
		return avg(p.jC(x, y), p.hV(x+1, y))
	case 12:
		return avg(p.hV(x, y), p.g(x, y+1))
	case 13:
		return avg(p.hV(x, y), p.bH(x, y+1))
	case 14:
		return avg(p.jC(x, y), p.bH(x, y+1))
	default:
		return avg(p.hV(x+1, y), p.bH(x, y+1))
	}
}

// predLuma writes the w*h prediction for the block whose top-left is at
// quarter-pel position (xq,yq) in ref into dst (stride w).
func predLuma(ref *Plane, xq, yq, w, h int, dst []uint8) {
	x0, y0 := xq>>2, yq>>2
	fx, fy := xq&3, yq&3
	if fx == 0 && fy == 0 {
		for j := 0; j < h; j++ {
			i := ref.idx(x0, y0+j)
			copy(dst[j*w:j*w+w], ref.Pix[i:i+w])
		}
		return
	}
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			dst[j*w+i] = uint8(ref.sampleQ(x0+i, y0+j, fx, fy))
		}
	}
}

// predChroma: block top-left at chroma integer (bx,by), motion vector in
// eighth-pel chroma units (== luma quarter-pel value).
func predChroma(ref *Plane, bx, by int, mv MV, w, h int, dst []uint8) {
	x0 := bx + (int(mv.X) >> 3)
	y0 := by + (int(mv.Y) >> 3)
	fx, fy := int(mv.X)&7, int(mv.Y)&7
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			a := ref.g(x0+i, y0+j)
			b := ref.g(x0+i+1, y0+j)
			c := ref.g(x0+i, y0+j+1)
			d := ref.g(x0+i+1, y0+j+1)
			dst[j*w+i] = uint8(((8-fx)*(8-fy)*a + fx*(8-fy)*b + (8-fx)*fy*c + fx*fy*d + 32) >> 6)
		}
	}
}
