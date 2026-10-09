package ttf

import "sort"

type cmapSub struct {
	plat, enc, format int
	data              []byte // the subtable bytes
}

func (f *Font) parseCmap() {
	c := f.tab("cmap")
	if len(c) < 4 {
		fail("cmap too short")
	}
	n := u16(c, 2)
	for i := 0; i < n; i++ {
		plat, enc, off := u16(c, 4+8*i), u16(c, 6+8*i), int(u32(c, 8+8*i))
		if off+2 > len(c) {
			continue
		}
		format := u16(c, off)
		switch format {
		case 0, 4, 6, 12:
		default:
			continue
		}
		sub := &cmapSub{plat, enc, format, c[off:]}
		if sub.valid() {
			f.cmaps = append(f.cmaps, sub)
		}
	}
	if len(f.cmaps) == 0 {
		fail("cmap has no usable subtable (supported: formats 0, 4, 6, 12; ranges must be sorted and non-overlapping)")
	}
	rank := func(s *cmapSub) int {
		switch {
		case s.plat == 3 && s.enc == 10:
			return 5
		case s.plat == 0 && (s.enc == 4 || s.enc == 6):
			return 4
		case s.plat == 3 && s.enc == 1:
			return 3
		case s.plat == 0:
			return 2
		case s.plat == 1 && s.enc == 0:
			return 1
		}
		return 0
	}
	f.best = f.cmaps[0]
	for _, s := range f.cmaps {
		if rank(s) > rank(f.best) {
			f.best = s
		}
	}
	// Validate the chosen subtable eagerly so lookups can stay panic-free.
	func() {
		var err error
		defer catch(&err)
		f.best.lookup(0x41)
		f.best.lookup(0x10000)
		if err != nil {
			panic(parseError{err.Error()})
		}
	}()
}

// CmapInfo describes the character map in use.
func (f *Font) CmapInfo() (platform, encoding, format int) {
	return f.best.plat, f.best.enc, f.best.format
}

// Index maps a rune to a glyph ID; 0 (.notdef) if unmapped or malformed.
func (f *Font) Index(r rune) (gid uint16) {
	defer func() {
		if recover() != nil {
			gid = 0
		}
	}()
	g := f.best.lookup(r)
	if g >= f.NumGlyphs {
		return 0
	}
	return uint16(g)
}

// Runes returns every mapped rune (ascending) from the chosen cmap subtable
// whose glyph is a valid non-.notdef glyph.
func (f *Font) Runes() []rune {
	var out []rune
	func() {
		defer func() { recover() }()
		for _, r := range f.best.mapped() {
			if g := f.best.lookup(r); g > 0 && g < f.NumGlyphs {
				out = append(out, r)
			}
		}
	}()
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

func (s *cmapSub) lookup(r rune) int {
	d := s.data
	if r < 0 {
		return 0
	}
	switch s.format {
	case 0:
		if r > 255 {
			return 0
		}
		return u8(d, 6+int(r))
	case 6:
		first, cnt := u16(d, 6), u16(d, 8)
		if int(r) < first || int(r) >= first+cnt {
			return 0
		}
		return u16(d, 10+2*(int(r)-first))
	case 4:
		if r > 0xFFFF {
			return 0
		}
		segX2 := u16(d, 6)
		ends, starts := 14, 14+segX2+2
		deltas, ranges := starts+segX2, starts+2*segX2
		seg := sort.Search(segX2/2, func(i int) bool { return u16(d, ends+2*i) >= int(r) })
		if seg >= segX2/2 || int(r) < u16(d, starts+2*seg) {
			return 0
		}
		delta, ro := u16(d, deltas+2*seg), u16(d, ranges+2*seg)
		if ro == 0 {
			return (int(r) + delta) & 0xFFFF
		}
		g := u16(d, ranges+2*seg+ro+2*(int(r)-u16(d, starts+2*seg)))
		if g == 0 {
			return 0
		}
		return (g + delta) & 0xFFFF
	case 12:
		n := int(u32(d, 12))
		i := sort.Search(n, func(i int) bool { return int(u32(d, 16+12*i+4)) >= int(r) })
		if i >= n {
			return 0
		}
		start, startG := int(u32(d, 16+12*i)), int(u32(d, 16+12*i+8))
		if int(r) < start {
			return 0
		}
		return startG + int(r) - start
	}
	return 0
}

// mapped enumerates candidate runes of a subtable (range starts..ends).
func (s *cmapSub) mapped() []rune {
	d := s.data
	var out []rune
	switch s.format {
	case 0:
		for r := 0; r < 256; r++ {
			out = append(out, rune(r))
		}
	case 6:
		first, cnt := u16(d, 6), u16(d, 8)
		for r := first; r < first+cnt; r++ {
			out = append(out, rune(r))
		}
	case 4:
		segX2 := u16(d, 6)
		for i := 0; i < segX2/2; i++ {
			e, st := u16(d, 14+2*i), u16(d, 14+segX2+2+2*i)
			for r := st; r <= e && r != 0xFFFF; r++ {
				out = append(out, rune(r))
			}
		}
	case 12:
		n := int(u32(d, 12))
		for i := 0; i < n; i++ {
			st, en := int(u32(d, 16+12*i)), int(u32(d, 16+12*i+4))
			if en-st > 0x110000 {
				fail("cmap12 group too large")
			}
			for r := st; r <= en; r++ {
				out = append(out, rune(r))
			}
		}
	}
	return out
}

// valid checks the structural invariants lookups rely on: sorted, non-overlapping,
// in-bounds ranges. Beyond preventing misreads, this bounds the work done when
// enumerating mapped runes (a hostile table cannot claim the same range 10^6 times).
func (s *cmapSub) valid() (ok bool) {
	defer func() {
		if recover() != nil {
			ok = false
		}
	}()
	d := s.data
	switch s.format {
	case 0:
		sub(d, 0, 262)
	case 6:
		sub(d, 0, 10+2*u16(d, 8))
	case 4:
		segX2 := u16(d, 6)
		if segX2 == 0 || segX2%2 != 0 {
			return false
		}
		sub(d, 0, 16+4*segX2) // end, pad, start, delta arrays (range offsets checked at lookup)
		sub(d, 14+3*segX2+2, segX2)
		prev := -1
		for i := 0; i < segX2/2; i++ {
			e, st := u16(d, 14+2*i), u16(d, 16+segX2+2*i)
			if st > e || st <= prev {
				return false
			}
			prev = e
		}
	case 12:
		n := int(u32(d, 12))
		if n > (len(d)-16)/12 {
			return false
		}
		prev := -1
		for i := 0; i < n; i++ {
			st, en := int(u32(d, 16+12*i)), int(u32(d, 16+12*i+4))
			if st > en || st <= prev || en > 0x10FFFF {
				return false
			}
			prev = en
		}
	}
	return true
}
