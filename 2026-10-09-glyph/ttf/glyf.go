package ttf

const maxCompositeDepth = 6
const maxComponents = 256

// Glyph returns the outline of a glyph with composites fully resolved.
// An empty glyph (e.g. space) yields an Outline with no contours.
func (f *Font) Glyph(gid uint16) (o Outline, err error) {
	defer catch(&err)
	if int(gid) >= f.NumGlyphs {
		fail("glyph %d out of range (font has %d)", gid, f.NumGlyphs)
	}
	budget := maxComponents
	return f.glyph(gid, 0, &budget), nil
}

func (f *Font) glyph(gid uint16, depth int, budget *int) Outline {
	if depth > maxCompositeDepth {
		fail("composite glyph nesting deeper than %d", maxCompositeDepth)
	}
	if depth == 0 {
		if o, ok := f.cache[gid]; ok {
			return o
		}
	}
	start, end := int(f.loca[gid]), int(f.loca[int(gid)+1])
	if start == end {
		return Outline{}
	}
	g := sub(f.tab("glyf"), start, end-start)
	nc := i16(g, 0)
	var out Outline
	if nc >= 0 {
		out = simpleGlyph(g, nc)
	} else {
		out = f.compositeGlyph(g, depth, budget)
	}
	if depth == 0 {
		f.cache[gid] = out
	}
	return out
}

func simpleGlyph(g []byte, nc int) Outline {
	p := 10
	ends := make([]int, nc)
	prev := -1
	for i := range ends {
		ends[i] = u16(g, p)
		p += 2
		if ends[i] <= prev {
			fail("contour end points not increasing")
		}
		prev = ends[i]
	}
	if nc == 0 {
		return Outline{}
	}
	npts := ends[nc-1] + 1
	p += 2 + u16(g, p) // skip hinting instructions
	flags := make([]byte, npts)
	for i := 0; i < npts; {
		fl := byte(u8(g, p))
		p++
		flags[i] = fl
		i++
		if fl&8 != 0 { // repeat
			for r := u8(g, p); r > 0; r-- {
				if i >= npts {
					fail("flag repeat overruns point count")
				}
				flags[i] = fl
				i++
			}
			p++
		}
	}
	xs := make([]float64, npts)
	ys := make([]float64, npts)
	read := func(dst []float64, shortBit, sameBit byte) {
		v := 0
		for i, fl := range flags {
			switch {
			case fl&shortBit != 0:
				d := u8(g, p)
				p++
				if fl&sameBit == 0 {
					d = -d
				}
				v += d
			case fl&sameBit != 0: // unchanged
			default:
				v += i16(g, p)
				p += 2
			}
			dst[i] = float64(v)
		}
	}
	read(xs, 2, 16)
	read(ys, 4, 32)
	var out Outline
	s := 0
	for _, e := range ends {
		c := make(Contour, 0, e-s+1)
		for i := s; i <= e; i++ {
			c = append(c, Point{xs[i], ys[i], flags[i]&1 != 0})
		}
		out.Contours = append(out.Contours, c)
		s = e + 1
	}
	return out
}

func (f *Font) compositeGlyph(g []byte, depth int, budget *int) Outline {
	const (
		argsAreWords = 0x0001
		argsAreXY    = 0x0002
		haveScale    = 0x0008
		more         = 0x0020
		haveXYScale  = 0x0040
		have2x2      = 0x0080
		scaledOffset = 0x0800
	)
	var out Outline
	p := 10
	for {
		if *budget--; *budget < 0 {
			fail("composite glyph has too many components")
		}
		fl, comp := u16(g, p), uint16(u16(g, p+2))
		p += 4
		var a1, a2 int
		if fl&argsAreWords != 0 {
			if fl&argsAreXY != 0 {
				a1, a2 = i16(g, p), i16(g, p+2)
			} else {
				a1, a2 = u16(g, p), u16(g, p+2)
			}
			p += 4
		} else {
			if fl&argsAreXY != 0 {
				a1, a2 = int(int8(u8(g, p))), int(int8(u8(g, p+1)))
			} else {
				a1, a2 = u8(g, p), u8(g, p+1)
			}
			p += 2
		}
		a, b, c, d := 1.0, 0.0, 0.0, 1.0 // x' = a*x + c*y, y' = b*x + d*y
		f2 := func(off int) float64 { return float64(i16(g, off)) / 16384 }
		switch {
		case fl&haveScale != 0:
			a = f2(p)
			d = a
			p += 2
		case fl&haveXYScale != 0:
			a, d = f2(p), f2(p+2)
			p += 4
		case fl&have2x2 != 0:
			a, b, c, d = f2(p), f2(p+2), f2(p+4), f2(p+6)
			p += 8
		}
		if int(comp) >= f.NumGlyphs {
			fail("composite references glyph %d of %d", comp, f.NumGlyphs)
		}
		child := f.glyph(comp, depth+1, budget)
		var dx, dy float64
		if fl&argsAreXY != 0 {
			dx, dy = float64(a1), float64(a2)
			if fl&scaledOffset != 0 { // offset is in the component's scaled space
				dx, dy = a*dx+c*dy, b*dx+d*dy
			}
			child = child.Transform(a, b, c, d, 0, 0)
		} else {
			// point matching: align child point a2 with already-assembled parent point a1
			child = child.Transform(a, b, c, d, 0, 0)
			pp, cp := pointAt(out, a1), pointAt(child, a2)
			dx, dy = pp.X-cp.X, pp.Y-cp.Y
		}
		child = child.Transform(1, 0, 0, 1, dx, dy)
		out.Contours = append(out.Contours, child.Contours...)
		if fl&more == 0 {
			break
		}
	}
	return out
}

func pointAt(o Outline, idx int) Point {
	for _, c := range o.Contours {
		if idx < len(c) {
			return c[idx]
		}
		idx -= len(c)
	}
	fail("point-matching index out of range")
	return Point{}
}
