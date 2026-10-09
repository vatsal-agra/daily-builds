package ttf

import (
	"math"
	"os"
	"path/filepath"
	"testing"
)

// ---- cmap formats 0 and 6 (not produced by Build, so crafted by hand) ----

func TestCmapFormat0And6(t *testing.T) {
	f0 := make([]byte, 262)
	copy(f0, cat(be16(0), be16(262), be16(0)))
	f0[6+int('A')] = 7
	f0[6+255] = 9
	s0 := &cmapSub{1, 0, 0, f0}
	if !s0.valid() || s0.lookup('A') != 7 || s0.lookup(255) != 9 || s0.lookup('B') != 0 || s0.lookup(256) != 0 {
		t.Error("format 0 lookup wrong")
	}
	s6 := &cmapSub{0, 3, 6, cat(be16(6), be16(16), be16(0), be16(0x30), be16(3), be16(11), be16(12), be16(13))}
	if !s6.valid() {
		t.Fatal("format 6 rejected")
	}
	for r, want := range map[rune]int{0x2F: 0, 0x30: 11, 0x31: 12, 0x32: 13, 0x33: 0} {
		if got := s6.lookup(r); got != want {
			t.Errorf("format 6 U+%04X = %d, want %d", r, got, want)
		}
	}
}

// Format 4 with idRangeOffset (glyph-index-array) segments.
func TestCmapFormat4RangeOffset(t *testing.T) {
	// segments: [0x41..0x43] via glyphIdArray {5,0,8} with delta 1 ; terminator 0xFFFF
	segX2 := 4
	b := cat(be16(4), be16(0), be16(0), be16(segX2), be16(4), be16(1), be16(0))
	b = cat(b, be16(0x43), be16(0xFFFF), be16(0)) // endCode, pad
	b = cat(b, be16(0x41), be16(0xFFFF))          // startCode
	b = cat(b, be16(1), be16(1))                  // idDelta
	// idRangeOffset[0] points from its own position to glyphIdArray start: 2 entries * 2 bytes = 4
	b = cat(b, be16(4), be16(0))
	b = cat(b, be16(5), be16(0), be16(8)) // glyphIdArray
	s := &cmapSub{3, 1, 4, b}
	if !s.valid() {
		t.Fatal("rejected")
	}
	for r, want := range map[rune]int{0x41: 6, 0x42: 0, 0x43: 9, 0x44: 0, 0x40: 0} {
		if got := s.lookup(r); got != want {
			t.Errorf("U+%04X → %d, want %d", r, got, want)
		}
	}
}

// ---- composite glyphs, assembled by hand ----

func testFontWithGlyphs(t *testing.T, glyphs [][]byte, lsbs []int) *Font {
	var glyf []byte
	offs := []int{0}
	for _, g := range glyphs {
		glyf = append(glyf, g...)
		for len(glyf)%4 != 0 {
			glyf = append(glyf, 0)
		}
		offs = append(offs, len(glyf))
	}
	var hm []byte
	for i := range glyphs {
		hm = append(hm, cat(be16(500), be16(lsbs[i]&0xFFFF))...)
	}
	f := &Font{data: append(append([]byte{}, glyf...), hm...), NumGlyphs: len(glyphs), numHM: len(glyphs),
		cache: map[uint16]Outline{}, tables: map[string]table{}}
	f.tables["glyf"] = table{tag: "glyf", off: 0, len: len(glyf)}
	f.tables["hmtx"] = table{tag: "hmtx", off: len(glyf), len: len(hm)}
	for _, o := range offs {
		f.loca = append(f.loca, uint32(o))
	}
	return f
}

func TestCompositeTransforms(t *testing.T) {
	sq := Outline{Contours: []Contour{{{0, 0, true}, {0, 100, true}, {100, 100, true}, {100, 0, true}}}}
	enc, _, _, err := encodeGlyph(sq)
	if err != nil {
		t.Fatal(err)
	}
	// glyph 2: two components of glyph 1.
	//  a) XY offset (200, 50), uniform scale 0.5  (flags: words|xy|scale|more)
	//  b) XY offset (10, 10) with SCALED_COMPONENT_OFFSET and scale 2 → offset becomes (20,20)
	comp := cat(be16(0xFFFF), be16(0), be16(0), be16(100), be16(100))  // numberOfContours = -1 + bbox (bbox unused by the parser)
	comp = cat(comp,
		be16(0x0001|0x0002|0x0008|0x0020), be16(1), be16(200), be16(50), be16(0x2000), // 0.5 in F2Dot14
		be16(0x0001|0x0002|0x0008|0x0800), be16(1), be16(10), be16(10), be16(0x7FFF), // ≈2? 0x7FFF is 1.99994
	)
	f := testFontWithGlyphs(t, [][]byte{nil, enc, comp}, []int{0, 0, 0})
	o, err := f.Glyph(2)
	if err != nil {
		t.Fatal(err)
	}
	if len(o.Contours) != 2 {
		t.Fatalf("want 2 contours, got %d", len(o.Contours))
	}
	a := o.Contours[0]
	if a[2].X != 250 || a[2].Y != 100 || a[0].X != 200 || a[0].Y != 50 {
		t.Errorf("component a wrong: %v", a)
	}
	s := 0x7FFF / 16384.0
	bb := o.Contours[1]
	if math.Abs(bb[2].X-(100*s+10*s)) > 1e-9 || math.Abs(bb[0].Y-10*s) > 1e-9 {
		t.Errorf("component b (scaled offset) wrong: %v", bb)
	}
}

func TestCompositePointMatchingAnd2x2(t *testing.T) {
	sq := Outline{Contours: []Contour{{{0, 0, true}, {0, 100, true}, {100, 100, true}, {100, 0, true}}}}
	enc, _, _, _ := encodeGlyph(sq)
	// component 1: plain. component 2: point matching, child point 0 on parent point 2 (100,100),
	// words flag clear (byte args), 2x2 matrix rotating 90° (x'=-y, y'=x).
	hdr := cat(be16(0xFFFF), be16(0), be16(0), be16(100), be16(100))
	c1 := cat(be16(0x0001|0x0002|0x0020), be16(1), be16(0), be16(0))
	c2 := cat(be16(0x0080), be16(1), []byte{2, 0}, be16(0), be16(0x4000), be16(0xC000), be16(0)) // a=0,b=1(0x4000),c=-1(0xC000),d=0
	f := testFontWithGlyphs(t, [][]byte{nil, enc, cat(hdr, c1, c2)}, []int{0, 0, 0})
	o, err := f.Glyph(2)
	if err != nil {
		t.Fatal(err)
	}
	// rotated square has x' = -y, y' = x → child point0 (0,0) → (0,0); matched to (100,100) so translate +(100,100)
	r := o.Contours[1]
	if r[0].X != 100 || r[0].Y != 100 {
		t.Errorf("point 0 should land on parent point 2 (100,100), got %v", r[0])
	}
	if r[1].X != 0 || r[1].Y != 100 { // child (0,100) → (-100,0) → +(100,100) = (0,100)
		t.Errorf("rotation wrong: point 1 = %v", r[1])
	}
}

func TestCompositeLimits(t *testing.T) {
	sq := Outline{Contours: []Contour{{{0, 0, true}, {0, 100, true}, {100, 100, true}, {100, 0, true}}}}
	enc, _, _, _ := encodeGlyph(sq)
	hdr := cat(be16(0xFFFF), be16(0), be16(0), be16(0), be16(0))
	self := cat(hdr, be16(0x0001|0x0002), be16(2), be16(0), be16(0)) // glyph 2 includes glyph 2
	f := testFontWithGlyphs(t, [][]byte{nil, enc, self}, []int{0, 0, 0})
	if _, err := f.Glyph(2); err == nil {
		t.Error("self-referencing composite accepted")
	}
	// out-of-range component and bad point-matching index
	bad := cat(hdr, be16(0x0001|0x0002), be16(77), be16(0), be16(0))
	f = testFontWithGlyphs(t, [][]byte{nil, enc, bad}, []int{0, 0, 0})
	if _, err := f.Glyph(2); err == nil {
		t.Error("component glyph 77 accepted")
	}
	pm := cat(hdr, be16(0x0001|0x0020|0x0000), be16(1), be16(0), be16(0), be16(0x0001), be16(1), be16(99), be16(0))
	f = testFontWithGlyphs(t, [][]byte{nil, enc, pm}, []int{0, 0, 0})
	if _, err := f.Glyph(2); err == nil {
		t.Error("point-matching out of range accepted")
	}
	// exponential blowup: 40 components each referencing a 40-component glyph
	many := hdr
	for i := 0; i < 40; i++ {
		fl := 0x0001 | 0x0002
		if i < 39 {
			fl |= 0x0020
		}
		many = cat(many, be16(fl), be16(2), be16(0), be16(0))
	}
	f = testFontWithGlyphs(t, [][]byte{nil, enc, many, cat(hdr, be16(0x0003), be16(2), be16(0), be16(0))}, []int{0, 0, 0, 0})
	if _, err := f.Glyph(3); err == nil {
		t.Error("component budget not enforced")
	}
}

func TestMalformedSimpleGlyph(t *testing.T) {
	for name, g := range map[string][]byte{
		"truncated header":    {0, 1, 0},
		"ends not increasing": cat(be16(2), be16(0), be16(0), be16(0), be16(0), be16(5), be16(5), be16(0)),
		"flags overrun":       cat(be16(1), be16(0), be16(0), be16(0), be16(0), be16(1), be16(0), []byte{0x09, 200}),
		"coords truncated":    cat(be16(1), be16(0), be16(0), be16(0), be16(0), be16(2), be16(0), []byte{1, 1, 0, 1}),
	} {
		f := testFontWithGlyphs(t, [][]byte{g}, []int{0})
		if _, err := f.Glyph(0); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

// ---- GPOS pair kerning, hand-assembled (format 1, format 2, extension) ----

func buildGPOS(lookups [][]byte, featureLookups []int, tag string) []byte {
	// header: version, scriptList, featureList, lookupList
	script := be16(0) // empty ScriptList
	feat := cat(be16(1), []byte(tag), be16(8), be16(0), be16(len(featureLookups)))
	for _, l := range featureLookups {
		feat = cat(feat, be16(l))
	}
	ll := cat(be16(len(lookups)))
	off := 2 + 2*len(lookups)
	var bodies []byte
	for _, l := range lookups {
		ll = cat(ll, be16(off+len(bodies)))
		bodies = cat(bodies, l)
	}
	ll = cat(ll, bodies)
	hdr := 10
	return cat(be32(0x00010000), be16(hdr), be16(hdr+len(script)), be16(hdr+len(script)+len(feat)), script, feat, ll)
}

// lookup with one subtable at offset 8: type, flag, count, [off], subtable
func lookupOf(typ int, subtables ...[]byte) []byte {
	b := cat(be16(typ), be16(0), be16(len(subtables)))
	off := 6 + 2*len(subtables)
	var body []byte
	for _, s := range subtables {
		b = cat(b, be16(off+len(body)))
		body = cat(body, s)
	}
	return cat(b, body)
}

func pairPos1() []byte { // glyph 5 followed by 6 → -30, by 7 → +10 ; glyph 9 followed by 6 → -5
	cov := cat(be16(1), be16(2), be16(5), be16(9))
	ps1 := cat(be16(2), be16(6), be16(-30&0xFFFF), be16(7), be16(10))
	ps2 := cat(be16(1), be16(6), be16(-5&0xFFFF))
	hdr := 10 + 4
	covOff := hdr
	p1 := covOff + len(cov)
	p2 := p1 + len(ps1)
	return cat(be16(1), be16(covOff), be16(4), be16(0), be16(2), be16(p1), be16(p2), cov, ps1, ps2)
}

func pairPos2() []byte { // glyphs 20..21 are class 1 ; 30 is class 1 of the second classdef; value -77
	cov := cat(be16(2), be16(1), be16(20), be16(21), be16(0))
	cd1 := cat(be16(2), be16(1), be16(20), be16(21), be16(1))
	cd2 := cat(be16(1), be16(30), be16(2), be16(0), be16(1)) // glyph 30→0, 31→1
	// class1Count 2, class2Count 2; records with XAdvance only
	recs := cat(be16(0), be16(0), be16(0), be16(-77&0xFFFF)) // rows: class1=0 → [0,0]; class1=1 → [0,-77]
	hdr := 16 + len(recs)
	covOff := hdr
	cd1Off := covOff + len(cov)
	cd2Off := cd1Off + len(cd1)
	return cat(be16(2), be16(covOff), be16(4), be16(0), be16(cd1Off), be16(cd2Off), be16(2), be16(2), recs, cov, cd1, cd2)
}

func TestGPOSPairKerning(t *testing.T) {
	// class1=0 row: [c2=0:0, c2=1:0]; class1=1 row: [c2=0:0, c2=1:-77]
	p2 := pairPos2()
	ext := cat(be16(1), be16(2), be32(8), pairPos1()) // extension subtable wrapping a PairPos format 1
	g := buildGPOS([][]byte{lookupOf(2, p2), lookupOf(9, ext), lookupOf(2, pairPos1())}, []int{0, 1}, "kern")
	f := &Font{data: g, tables: map[string]table{"GPOS": {tag: "GPOS", len: len(g)}}}
	f.parseGPOS()
	if f.gpos == nil {
		t.Fatal("GPOS kern feature not parsed")
	}
	cases := []struct {
		l, r uint16
		want int
	}{
		{5, 6, -30}, {5, 7, 10}, {9, 6, -5}, {5, 8, 0}, {9, 7, 0}, {1, 2, 0},
		{20, 31, -77}, {21, 31, -77}, {20, 30, 0}, {22, 31, 0},
	}
	for _, c := range cases {
		if got := f.Kerning(c.l, c.r); got != c.want {
			t.Errorf("kern(%d,%d) = %d, want %d", c.l, c.r, got, c.want)
		}
	}
	if !f.HasKerning() {
		t.Error("HasKerning false")
	}
	// a lookup that is not referenced by the 'kern' feature must be ignored
	g2 := buildGPOS([][]byte{lookupOf(2, pairPos1())}, []int{0}, "liga")
	f2 := &Font{data: g2, tables: map[string]table{"GPOS": {tag: "GPOS", len: len(g2)}}}
	f2.parseGPOS()
	if f2.Kerning(5, 6) != 0 || f2.HasKerning() {
		t.Error("non-kern feature lookups must not kern")
	}
}

func TestGPOSMalformedLosesOnlyKerning(t *testing.T) {
	g := buildGPOS([][]byte{lookupOf(2, pairPos1())}, []int{0}, "kern")
	for cut := 12; cut < len(g); cut += 7 {
		f := &Font{data: g[:cut], tables: map[string]table{"GPOS": {tag: "GPOS", len: cut}}}
		f.parseGPOS() // must not panic
		f.Kerning(5, 6)
	}
}

// ---- real-font spot checks ----

func TestRealFontFacts(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("..", "testdata", "fonts", "Lora-Regular.ttf"))
	if err != nil {
		t.Skip()
	}
	f, err := Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	if f.Name(1) != "Lora" || f.UnitsPerEm != 1000 || f.WeightClass != 400 {
		t.Errorf("metadata: %q %d %d", f.Name(1), f.UnitsPerEm, f.WeightClass)
	}
	for r := rune(' '); r <= '~'; r++ {
		if f.Index(r) == 0 {
			t.Errorf("ASCII %q unmapped", r)
		}
	}
	if f.Index(0x4E2D) != 0 {
		t.Error("CJK char should be unmapped in Lora")
	}
	if f.Kerning(f.Index('A'), f.Index('V')) >= 0 || f.Kerning(f.Index('T'), f.Index('o')) >= 0 {
		t.Error("expected negative kerning for AV and To")
	}
	if f.Kerning(f.Index('i'), f.Index('i')) < -20 {
		t.Error("ii should not be strongly kerned")
	}
	// 'é' is a composite of e + acute in this font: it must contain both parts' contours
	e, _ := f.Glyph(f.Index('e'))
	ea, _ := f.Glyph(f.Index('é'))
	if len(ea.Contours) <= len(e.Contours) {
		t.Errorf("é (%d contours) should be e (%d) plus an accent", len(ea.Contours), len(e.Contours))
	}
	_, _, _, ymaxE, _ := e.Bounds()
	_, _, _, ymaxEa, _ := ea.Bounds()
	if ymaxEa <= ymaxE+50 {
		t.Errorf("accent should rise above the e: %v vs %v", ymaxEa, ymaxE)
	}
	if _, err := f.Glyph(uint16(f.NumGlyphs)); err == nil {
		t.Error("out-of-range glyph accepted")
	}
	if len(f.Runes()) < 700 {
		t.Errorf("Runes() found only %d", len(f.Runes()))
	}
	if f.Advance(f.Index('i')) >= f.Advance(f.Index('W')) {
		t.Error("i should be narrower than W")
	}
}

func TestParseRejectsJunk(t *testing.T) {
	for name, b := range map[string][]byte{
		"empty":     nil,
		"short":     {0, 1, 0, 0},
		"text":      []byte("this is not a font file at all, just text"),
		"otto":      cat([]byte("OTTO"), make([]byte, 64)),
		"ttc":       cat([]byte("ttcf"), make([]byte, 64)),
		"no tables": cat(be32(0x00010000), be16(0), make([]byte, 20)),
	} {
		if f, err := Parse(b); err == nil || f != nil {
			t.Errorf("%s: parsed junk", name)
		}
	}
}
