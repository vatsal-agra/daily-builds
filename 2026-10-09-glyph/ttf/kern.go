package ttf

func pairKey(l, r uint16) uint32 { return uint32(l)<<16 | uint32(r) }

// parseKern reads the legacy 'kern' table (version 0, horizontal format-0 subtables).
func (f *Font) parseKern() {
	k := f.tab("kern")
	if len(k) < 4 || u16(k, 0) != 0 {
		return
	}
	f.kernPairs = map[uint32]int{}
	n, p := u16(k, 2), 4
	for i := 0; i < n && p+6 <= len(k); i++ {
		length, cov := u16(k, p+2), u16(k, p+4)
		if length < 6 || p+length > len(k) {
			break
		}
		format, horizontal, minimum, cross, override := cov>>8, cov&1 != 0, cov&2 != 0, cov&4 != 0, cov&8 != 0
		if format == 0 && horizontal && !minimum && !cross && p+14 <= len(k) {
			np := u16(k, p+6)
			for j := 0; j < np && p+14+6*j+6 <= p+length; j++ {
				o := p + 14 + 6*j
				key := pairKey(uint16(u16(k, o)), uint16(u16(k, o+2)))
				if override {
					f.kernPairs[key] = i16(k, o+4)
				} else {
					f.kernPairs[key] += i16(k, o+4)
				}
			}
		}
		p += length
	}
}

// gposKern holds the PairPos subtables of lookups referenced by the 'kern' feature.
type gposKern struct {
	lookups [][]pairSub
}

type pairSub struct {
	format   int
	cov      coverage
	valFmt1  int
	valFmt2  int
	pairSets []int // format 1: offsets (absolute within gpos table)
	class1   classDef
	class2   classDef
	c1n, c2n int
	recBase  int // format 2 record array
	d        []byte
}

type coverage struct {
	glyphs []uint16 // format 1 (sorted)
	ranges [][3]int // format 2: start, end, startCoverageIndex
}

func parseCoverage(d []byte, off int) coverage {
	var c coverage
	switch fm := u16(d, off); fm {
	case 1:
		n := u16(d, off+2)
		for i := 0; i < n; i++ {
			c.glyphs = append(c.glyphs, uint16(u16(d, off+4+2*i)))
		}
	case 2:
		n := u16(d, off+2)
		for i := 0; i < n; i++ {
			o := off + 4 + 6*i
			c.ranges = append(c.ranges, [3]int{u16(d, o), u16(d, o+2), u16(d, o+4)})
		}
	default:
		fail("coverage format %d", fm)
	}
	return c
}

func (c coverage) index(g uint16) int {
	if c.glyphs != nil {
		lo, hi := 0, len(c.glyphs)
		for lo < hi {
			m := (lo + hi) / 2
			if c.glyphs[m] < g {
				lo = m + 1
			} else {
				hi = m
			}
		}
		if lo < len(c.glyphs) && c.glyphs[lo] == g {
			return lo
		}
		return -1
	}
	for _, r := range c.ranges {
		if int(g) >= r[0] && int(g) <= r[1] {
			return r[2] + int(g) - r[0]
		}
	}
	return -1
}

type classDef struct {
	start   int
	classes []int    // format 1
	ranges  [][3]int // format 2: start, end, class
}

func parseClassDef(d []byte, off int) classDef {
	var c classDef
	switch fm := u16(d, off); fm {
	case 1:
		c.start = u16(d, off+2)
		n := u16(d, off+4)
		c.classes = make([]int, n)
		for i := range c.classes {
			c.classes[i] = u16(d, off+6+2*i)
		}
	case 2:
		n := u16(d, off+2)
		for i := 0; i < n; i++ {
			o := off + 4 + 6*i
			c.ranges = append(c.ranges, [3]int{u16(d, o), u16(d, o+2), u16(d, o+4)})
		}
	default:
		fail("classdef format %d", fm)
	}
	return c
}

func (c classDef) class(g uint16) int {
	if c.ranges != nil {
		for _, r := range c.ranges {
			if int(g) >= r[0] && int(g) <= r[1] {
				return r[2]
			}
		}
		return 0
	}
	if i := int(g) - c.start; i >= 0 && i < len(c.classes) {
		return c.classes[i]
	}
	return 0
}

func valueSize(fmtBits int) int {
	n := 0
	for b := fmtBits & 0xFF; b != 0; b &= b - 1 {
		n += 2
	}
	return n
}

// xAdvanceOf extracts the XAdvance field (bit 0x4) from a value record at off.
func xAdvanceOf(d []byte, off, fmtBits int) int {
	if fmtBits&4 == 0 {
		return 0
	}
	skip := 0
	if fmtBits&1 != 0 {
		skip += 2
	}
	if fmtBits&2 != 0 {
		skip += 2
	}
	return i16(d, off+skip)
}

func (f *Font) parseGPOS() {
	g := f.tab("GPOS")
	if len(g) < 10 || u16(g, 0) != 1 {
		return
	}
	var err error
	func() {
		defer catch(&err)
		featList, lookList := u16(g, 6), u16(g, 8)
		wanted := map[int]bool{}
		nf := u16(g, featList)
		for i := 0; i < nf; i++ {
			tag := string(sub(g, featList+2+6*i, 4))
			if tag != "kern" {
				continue
			}
			fo := featList + u16(g, featList+2+6*i+4)
			for j, nl := 0, u16(g, fo+2); j < nl; j++ {
				wanted[u16(g, fo+4+2*j)] = true
			}
		}
		gk := &gposKern{}
		nl := u16(g, lookList)
		for li := 0; li < nl; li++ {
			if !wanted[li] {
				continue
			}
			lo := lookList + u16(g, lookList+2+2*li)
			typ, ns := u16(g, lo), u16(g, lo+4)
			var subs []pairSub
			for si := 0; si < ns; si++ {
				so := lo + u16(g, lo+6+2*si)
				t := typ
				if typ == 9 { // extension
					t = u16(g, so+2)
					so += int(u32(g, so+4))
				}
				if t != 2 {
					continue
				}
				subs = append(subs, parsePairPos(g, so))
			}
			if len(subs) > 0 {
				gk.lookups = append(gk.lookups, subs)
			}
		}
		if len(gk.lookups) > 0 {
			f.gpos = gk
		}
	}()
	// A malformed GPOS only loses kerning; it must not make the font unusable.
}

func parsePairPos(g []byte, so int) pairSub {
	ps := pairSub{d: g, format: u16(g, so)}
	ps.cov = parseCoverage(g, so+u16(g, so+2))
	ps.valFmt1, ps.valFmt2 = u16(g, so+4), u16(g, so+6)
	switch ps.format {
	case 1:
		n := u16(g, so+8)
		for i := 0; i < n; i++ {
			ps.pairSets = append(ps.pairSets, so+u16(g, so+10+2*i))
		}
	case 2:
		ps.class1 = parseClassDef(g, so+u16(g, so+8))
		ps.class2 = parseClassDef(g, so+u16(g, so+10))
		ps.c1n, ps.c2n = u16(g, so+12), u16(g, so+14)
		ps.recBase = so + 16
	default:
		fail("PairPos format %d", ps.format)
	}
	return ps
}

func (ps pairSub) adjust(l, r uint16) (int, bool) {
	ci := ps.cov.index(l)
	if ci < 0 {
		return 0, false
	}
	d := ps.d
	rec := valueSize(ps.valFmt1) + valueSize(ps.valFmt2)
	switch ps.format {
	case 1:
		if ci >= len(ps.pairSets) {
			return 0, false
		}
		o := ps.pairSets[ci]
		n := u16(d, o)
		for i := 0; i < n; i++ {
			ro := o + 2 + (2+rec)*i
			if u16(d, ro) == int(r) {
				return xAdvanceOf(d, ro+2, ps.valFmt1), true
			}
		}
	case 2:
		c1, c2 := ps.class1.class(l), ps.class2.class(r)
		if c1 >= ps.c1n || c2 >= ps.c2n {
			return 0, false
		}
		return xAdvanceOf(d, ps.recBase+rec*(c1*ps.c2n+c2), ps.valFmt1), true
	}
	return 0, false
}

// Kerning returns the horizontal adjustment (font units) to add to the advance
// of glyph l when followed by glyph r. GPOS 'kern' lookups take precedence;
// the legacy kern table is used when the font has no GPOS kerning.
func (f *Font) Kerning(l, r uint16) (k int) {
	defer func() {
		if recover() != nil {
			k = 0
		}
	}()
	if f.gpos != nil {
		for _, subs := range f.gpos.lookups {
			for _, s := range subs {
				if v, ok := s.adjust(l, r); ok {
					k += v
					break
				}
			}
		}
		return k
	}
	return f.kernPairs[pairKey(l, r)]
}

// HasKerning reports whether any kerning source was found.
func (f *Font) HasKerning() bool { return f.gpos != nil || len(f.kernPairs) > 0 }

// KernPairs returns the legacy kern-table pairs (nil if none).
func (f *Font) KernPairs() map[uint32]int { return f.kernPairs }
