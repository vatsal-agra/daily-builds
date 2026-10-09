package ttf

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func cat(parts ...[]byte) []byte {
	var o []byte
	for _, p := range parts {
		o = append(o, p...)
	}
	return o
}

// REVIEW R1: hostile cmap format-12 tables (overlapping / huge / unsorted groups)
// must be rejected so Runes() can never be tricked into enumerating billions of runes.
func TestCmap12RejectsOverlappingGroups(t *testing.T) {
	group := func(s, e, g int) []byte { return cat(be32(s), be32(e), be32(g)) }
	mk := func(groups ...[]byte) *cmapSub {
		body := cat(groups...)
		hdr := cat(be16(12), be16(0), be32(16+len(body)), be32(0), be32(len(groups)))
		return &cmapSub{3, 10, 12, cat(hdr, body)}
	}
	if !mk(group(0x41, 0x5A, 1), group(0x61, 0x7A, 27)).valid() {
		t.Error("well-formed cmap rejected")
	}
	bad := map[string]*cmapSub{
		"overlap":    mk(group(0, 0x10FFFF, 1), group(0x41, 0x5A, 1)),
		"repeat":     mk(group(0x41, 0x5A, 1), group(0x41, 0x5A, 1)),
		"unsorted":   mk(group(0x61, 0x7A, 1), group(0x41, 0x5A, 1)),
		"inverted":   mk(group(0x5A, 0x41, 1)),
		"beyond":     mk(group(0x41, 0x110000, 1)),
		"count>data": {3, 10, 12, cat(be16(12), be16(0), be32(16), be32(0), be32(99999))},
	}
	for name, s := range bad {
		if s.valid() {
			t.Errorf("%s: hostile cmap accepted", name)
		}
	}
}

func TestCmap4RejectsUnsortedSegments(t *testing.T) {
	seg := func(starts, ends []int) *cmapSub {
		n := len(starts)
		var b []byte
		b = cat(be16(4), be16(0), be16(0), be16(2*n), be16(0), be16(0), be16(0))
		for _, e := range ends {
			b = cat(b, be16(e))
		}
		b = cat(b, be16(0))
		for _, s := range starts {
			b = cat(b, be16(s))
		}
		for range starts {
			b = cat(b, be16(0))
		}
		for range starts {
			b = cat(b, be16(0))
		}
		return &cmapSub{3, 1, 4, b}
	}
	if !seg([]int{0x41, 0xFFFF}, []int{0x5A, 0xFFFF}).valid() {
		t.Error("good format 4 rejected")
	}
	if seg([]int{0x61, 0x41}, []int{0x7A, 0x5A}).valid() {
		t.Error("unsorted format 4 accepted")
	}
}

// REVIEW R15: cross-stream and minimum kern subtables are not horizontal advances.
func TestKernSkipsCrossStream(t *testing.T) {
	sub := func(cov, val int) []byte {
		return cat(be16(0), be16(14+6), be16(cov), be16(1), be16(0), be16(0), be16(0), be16(1), be16(2), be16(val))
	}
	mk := func(s []byte) *Font {
		data := cat(be16(0), be16(1), s)
		return &Font{data: data, tables: map[string]table{"kern": {tag: "kern", off: 0, len: len(data)}}}
	}
	f := mk(sub(1, -50))
	f.parseKern()
	if got := f.kernPairs[pairKey(1, 2)]; got != -50 {
		t.Errorf("horizontal kern = %d, want -50", got)
	}
	for name, cov := range map[string]int{"cross-stream": 1 | 4, "minimum": 1 | 2, "vertical": 0} {
		f := mk(sub(cov, -50))
		f.parseKern()
		if len(f.kernPairs) != 0 {
			t.Errorf("%s subtable was applied as a horizontal kern", name)
		}
	}
}

// REVIEW R5: Glyph() shares a cache; concurrent use must be race-free (run with -race).
func TestGlyphConcurrent(t *testing.T) {
	m, _ := filepath.Glob("../testdata/fonts/Lora-Regular.ttf")
	if len(m) == 0 {
		t.Skip()
	}
	b, _ := os.ReadFile(m[0])
	f, _ := Parse(b)
	var wg sync.WaitGroup
	for w := 0; w < 8; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for g := 0; g < 300; g++ {
				f.Glyph(uint16(g))
				f.Index(rune(32 + g%90))
			}
		}()
	}
	wg.Wait()
}

// Invariant restored by the lsb shift: every glyph's xMin equals its hmtx lsb.
func TestOutlineXMinEqualsLSB(t *testing.T) {
	files, _ := filepath.Glob("../testdata/fonts/*.ttf")
	if len(files) == 0 {
		t.Skip()
	}
	for _, p := range files {
		b, _ := os.ReadFile(p)
		f, _ := Parse(b)
		for g := 0; g < f.NumGlyphs; g++ {
			o, _ := f.Glyph(uint16(g))
			if x0, _, _, _, ok := o.Bounds(); ok && int(x0) != f.LSB(uint16(g)) {
				t.Fatalf("%s glyph %d: xMin %v != lsb %d", filepath.Base(p), g, x0, f.LSB(uint16(g)))
			}
		}
	}
}

// A font whose hmtx lsb disagrees with glyf xMin must have its outline shifted.
func TestLSBShiftApplied(t *testing.T) {
	m, _ := filepath.Glob("../testdata/fonts/Lora-Regular.ttf")
	if len(m) == 0 {
		t.Skip()
	}
	b, _ := os.ReadFile(m[0])
	f, _ := Parse(b)
	gid := f.Index('H')
	before, _ := f.Glyph(gid)
	bx, _, _, _, _ := before.Bounds()
	// patch lsb of 'H' by +37 in a copy of the file (checksums become stale; not verified here)
	cp := append([]byte(nil), b...)
	hm := f.tables["hmtx"]
	binary.BigEndian.PutUint16(cp[hm.off+4*int(gid)+2:], uint16(int(bx)+37))
	g, err := Parse(cp)
	if err != nil {
		t.Fatal(err)
	}
	after, _ := g.Glyph(gid)
	ax, _, _, _, _ := after.Bounds()
	if ax != bx+37 {
		t.Errorf("xMin after lsb edit = %v, want %v", ax, bx+37)
	}
}
