// Package ttf parses (and writes) TrueType fonts from scratch.
package ttf

import (
	"fmt"
	"sort"
	"unicode/utf16"
)

type table struct {
	tag      string
	checksum uint32
	off, len int
}

// Font is a parsed TrueType font with glyph outlines (glyf flavour).
type Font struct {
	data   []byte
	tables map[string]table
	order  []string

	UnitsPerEm             int
	NumGlyphs              int
	Ascent                 int // hhea
	Descent                int // hhea (negative below baseline)
	LineGap                int
	XMin, YMin, XMax, YMax int
	WeightClass            int // OS/2, 0 if absent

	longLoca  bool
	loca      []uint32
	numHM     int
	cmaps     []*cmapSub
	best      *cmapSub
	kernPairs map[uint32]int
	gpos      *gposKern
	names     map[int]string
	cache     map[uint16]Outline
}

const magicHead = 0x5F0F3CF5

// Parse reads a TrueType font. Any structural problem yields an error wrapping
// ErrMalformed; it never panics on bad input.
func Parse(data []byte) (f *Font, err error) {
	defer catch(&err)
	if len(data) < 12 {
		fail("file too short (%d bytes)", len(data))
	}
	switch tag := string(data[:4]); {
	case tag == "OTTO":
		return nil, fmt.Errorf("%w: CFF-flavoured OpenType (OTTO) is not supported; need glyf outlines", ErrMalformed)
	case tag == "ttcf":
		return nil, fmt.Errorf("%w: TrueType collections (.ttc) are not supported", ErrMalformed)
	case u32(data, 0) != 0x00010000 && tag != "true":
		fail("bad sfnt version %#08x", u32(data, 0))
	}
	f = &Font{data: data, tables: map[string]table{}, cache: map[uint16]Outline{}}
	n := u16(data, 4)
	if n == 0 || n > 64 {
		fail("implausible table count %d", n)
	}
	for i := 0; i < n; i++ {
		r := 12 + 16*i
		t := table{string(sub(data, r, 4)), u32(data, r+4), int(u32(data, r+8)), int(u32(data, r+12))}
		if t.off < 0 || t.len < 0 || t.off+t.len > len(data) {
			fail("table %q (offset %d, length %d) exceeds file of %d bytes", t.tag, t.off, t.len, len(data))
		}
		if _, dup := f.tables[t.tag]; dup {
			fail("duplicate table %q", t.tag)
		}
		f.tables[t.tag] = t
		f.order = append(f.order, t.tag)
	}
	for _, need := range []string{"head", "maxp", "hhea", "hmtx", "loca", "glyf", "cmap"} {
		if _, ok := f.tables[need]; !ok {
			fail("required table %q missing", need)
		}
	}
	f.parseHead()
	f.parseMaxp()
	f.parseHhea()
	f.parseLoca()
	f.parseCmap()
	f.parseOS2()
	f.parseName()
	f.parseKern()
	f.parseGPOS()
	return f, nil
}

func (f *Font) tab(tag string) []byte {
	t, ok := f.tables[tag]
	if !ok {
		return nil
	}
	return f.data[t.off : t.off+t.len]
}

// HasTable reports whether the font contains the named table.
func (f *Font) HasTable(tag string) bool { _, ok := f.tables[tag]; return ok }

// Tables lists table tags in file order.
func (f *Font) Tables() []string { return append([]string(nil), f.order...) }

func (f *Font) parseHead() {
	h := f.tab("head")
	if len(h) < 54 {
		fail("head table too short (%d)", len(h))
	}
	if u32(h, 12) != magicHead {
		fail("head magic %#x != %#x", u32(h, 12), magicHead)
	}
	f.UnitsPerEm = u16(h, 18)
	if f.UnitsPerEm < 16 || f.UnitsPerEm > 16384 {
		fail("unitsPerEm %d out of range 16..16384", f.UnitsPerEm)
	}
	f.XMin, f.YMin, f.XMax, f.YMax = i16(h, 36), i16(h, 38), i16(h, 40), i16(h, 42)
	switch lf := i16(h, 50); lf {
	case 0:
	case 1:
		f.longLoca = true
	default:
		fail("indexToLocFormat %d", lf)
	}
}

func (f *Font) parseMaxp() {
	m := f.tab("maxp")
	if len(m) < 6 {
		fail("maxp too short")
	}
	f.NumGlyphs = u16(m, 4)
	if f.NumGlyphs == 0 {
		fail("font has zero glyphs")
	}
}

func (f *Font) parseHhea() {
	h := f.tab("hhea")
	if len(h) < 36 {
		fail("hhea too short")
	}
	f.Ascent, f.Descent, f.LineGap = i16(h, 4), i16(h, 6), i16(h, 8)
	f.numHM = u16(h, 34)
	if f.numHM == 0 || f.numHM > f.NumGlyphs {
		fail("numberOfHMetrics %d invalid for %d glyphs", f.numHM, f.NumGlyphs)
	}
	hm := f.tab("hmtx")
	if want := f.numHM*4 + (f.NumGlyphs-f.numHM)*2; len(hm) < want {
		fail("hmtx has %d bytes, need %d", len(hm), want)
	}
}

func (f *Font) parseLoca() {
	l := f.tab("loca")
	n := f.NumGlyphs + 1
	f.loca = make([]uint32, n)
	glyf := len(f.tab("glyf"))
	if f.longLoca {
		if len(l) < 4*n {
			fail("loca has %d bytes, need %d", len(l), 4*n)
		}
		for i := range f.loca {
			f.loca[i] = u32(l, 4*i)
		}
	} else {
		if len(l) < 2*n {
			fail("loca has %d bytes, need %d", len(l), 2*n)
		}
		for i := range f.loca {
			f.loca[i] = uint32(u16(l, 2*i)) * 2
		}
	}
	for i := 1; i < n; i++ {
		if f.loca[i] < f.loca[i-1] {
			fail("loca not monotonic at glyph %d", i)
		}
	}
	if int(f.loca[n-1]) > glyf {
		fail("loca end %d beyond glyf length %d", f.loca[n-1], glyf)
	}
}

func (f *Font) parseOS2() {
	if o := f.tab("OS/2"); len(o) >= 6 {
		f.WeightClass = u16(o, 4)
	}
}

func (f *Font) parseName() {
	f.names = map[int]string{}
	nm := f.tab("name")
	if len(nm) < 6 {
		return
	}
	cnt, strOff := u16(nm, 2), u16(nm, 4)
	type cand struct {
		prio int
		s    string
	}
	best := map[int]cand{}
	for i := 0; i < cnt && 6+12*i+12 <= len(nm); i++ {
		r := 6 + 12*i
		plat, enc, lang, id, ln, off := u16(nm, r), u16(nm, r+2), u16(nm, r+4), u16(nm, r+6), u16(nm, r+8), u16(nm, r+10)
		if strOff+off+ln > len(nm) {
			continue
		}
		raw := nm[strOff+off : strOff+off+ln]
		var s string
		prio := 0
		switch {
		case plat == 3 && (enc == 1 || enc == 10) && ln%2 == 0:
			u := make([]uint16, ln/2)
			for k := range u {
				u[k] = uint16(raw[2*k])<<8 | uint16(raw[2*k+1])
			}
			s, prio = string(utf16.Decode(u)), 3
			if lang == 0x409 {
				prio = 4
			}
		case plat == 0 && ln%2 == 0:
			u := make([]uint16, ln/2)
			for k := range u {
				u[k] = uint16(raw[2*k])<<8 | uint16(raw[2*k+1])
			}
			s, prio = string(utf16.Decode(u)), 2
		case plat == 1 && enc == 0:
			s, prio = string(raw), 1 // MacRoman: ASCII range is identical
		default:
			continue
		}
		if c, ok := best[id]; !ok || prio > c.prio {
			best[id] = cand{prio, s}
		}
	}
	for id, c := range best {
		f.names[id] = c.s
	}
}

// Name returns a name-table string (1 family, 2 subfamily, 4 full, 6 PostScript), or "".
func (f *Font) Name(id int) string { return f.names[id] }

// advanceLSB returns hmtx data for a glyph.
func (f *Font) hmtx(gid int) (adv, lsb int) {
	hm := f.tab("hmtx")
	if gid < 0 || gid >= f.NumGlyphs {
		gid = 0
	}
	if gid < f.numHM {
		return u16(hm, 4*gid), i16(hm, 4*gid+2)
	}
	adv = u16(hm, 4*(f.numHM-1))
	return adv, i16(hm, 4*f.numHM+2*(gid-f.numHM))
}

// Advance returns the horizontal advance of a glyph in font units.
func (f *Font) Advance(gid uint16) (adv int) {
	defer func() { recover() }()
	adv, _ = f.hmtx(int(gid))
	return
}

// Verify checks table checksums and the head checksumAdjustment, returning one
// message per problem (empty slice = file is internally consistent).
func (f *Font) Verify() []string {
	var bad []string
	for _, tag := range f.order {
		t := f.tables[tag]
		raw := f.data[t.off : t.off+t.len]
		if tag == "head" && len(raw) >= 12 {
			raw = append([]byte(nil), raw...)
			raw[8], raw[9], raw[10], raw[11] = 0, 0, 0, 0
		}
		if got := Checksum(raw); got != t.checksum {
			bad = append(bad, fmt.Sprintf("table %q checksum %#08x, directory says %#08x", tag, got, t.checksum))
		}
	}
	if h := f.tab("head"); len(h) >= 12 {
		if Checksum(f.data) != 0xB1B0AFBA {
			// whole-file sum (adjustment included) must equal the magic constant
			bad = append(bad, "head.checksumAdjustment does not make the file sum to 0xB1B0AFBA")
		}
	}
	sort.Strings(bad)
	return bad
}

// Checksum is the sfnt table checksum: sum of big-endian uint32 words, zero padded.
func Checksum(b []byte) uint32 {
	var s uint32
	for i := 0; i < len(b); i += 4 {
		var w [4]byte
		copy(w[:], b[i:min(i+4, len(b))])
		s += uint32(w[0])<<24 | uint32(w[1])<<16 | uint32(w[2])<<8 | uint32(w[3])
	}
	return s
}
