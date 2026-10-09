package ttf_test

import (
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"glyph/ttf"
)

func sq(x0, y0, x1, y1 float64, cw bool) ttf.Contour {
	c := ttf.Contour{{x0, y0, true}, {x0, y1, true}, {x1, y1, true}, {x1, y0, true}}
	if !cw {
		c = ttf.Contour{c[0], c[3], c[2], c[1]}
	}
	return c
}

func syntheticSpec() ttf.Spec {
	circle := ttf.Contour{{500, 0, false}, {1000, 0, false}, {1000, 500, true}, {1000, 1000, false}, {500, 1000, false}, {0, 1000, false}, {0, 500, true}, {0, 0, false}}
	return ttf.Spec{
		Family: "Synthetic", Style: "Test", UnitsPerEm: 1000, Ascent: 800, Descent: -200,
		Glyphs: []ttf.GlyphSpec{
			{Outline: ttf.Outline{Contours: []ttf.Contour{sq(50, 0, 550, 700, true)}}, Advance: 600},                               // 0 .notdef
			{Outline: ttf.Outline{}, Advance: 300},                                                                                 // 1 space
			{Outline: ttf.Outline{Contours: []ttf.Contour{sq(0, 0, 600, 700, true), sq(150, 150, 450, 550, false)}}, Advance: 700}, // 2 box with hole
			{Outline: ttf.Outline{Contours: []ttf.Contour{circle}}, Advance: 1100},                                                 // 3 round
			{Outline: ttf.Outline{Contours: []ttf.Contour{sq(-80, -16000, 300, 16000, true)}}, Advance: 400},                       // 4 tall, negative lsb
		},
		Cmap: map[rune]uint16{' ': 1, 'A': 2, 'B': 3, 'C': 4, 'é': 2, 0x1F600: 3, 'D': 3},
		Kern: map[[2]uint16]int{{2, 3}: -90, {3, 2}: 40},
	}
}

func TestBuildParseRoundTrip(t *testing.T) {
	spec := syntheticSpec()
	b, err := ttf.Build(spec)
	if err != nil {
		t.Fatal(err)
	}
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	if bad := f.Verify(); len(bad) != 0 {
		t.Fatalf("built font fails verification: %v", bad)
	}
	if f.Name(1) != "Synthetic" || f.Name(2) != "Test" || f.Name(4) != "Synthetic Test" {
		t.Errorf("names: %q %q %q", f.Name(1), f.Name(2), f.Name(4))
	}
	if f.UnitsPerEm != 1000 || f.NumGlyphs != 5 || f.Ascent != 800 || f.Descent != -200 {
		t.Errorf("metrics wrong: %d %d %d %d", f.UnitsPerEm, f.NumGlyphs, f.Ascent, f.Descent)
	}
	for r, want := range spec.Cmap {
		if got := f.Index(r); got != want {
			t.Errorf("cmap U+%04X = %d, want %d", r, got, want)
		}
	}
	if f.Index('Z') != 0 || f.Index(0x1F601) != 0 {
		t.Error("unmapped runes must give .notdef")
	}
	for g, gs := range spec.Glyphs {
		o, err := f.Glyph(uint16(g))
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(o.Contours, nilIfEmpty(gs.Outline.Contours)) && !(len(o.Contours) == 0 && len(gs.Outline.Contours) == 0) {
			t.Errorf("glyph %d outline changed in round trip:\n got %v\nwant %v", g, o.Contours, gs.Outline.Contours)
		}
		if f.Advance(uint16(g)) != gs.Advance {
			t.Errorf("glyph %d advance %d != %d", g, f.Advance(uint16(g)), gs.Advance)
		}
	}
	for k, v := range spec.Kern {
		if got := f.Kerning(k[0], k[1]); got != v {
			t.Errorf("kern %v = %d, want %d", k, got, v)
		}
	}
	if f.Kerning(1, 2) != 0 {
		t.Error("absent pair must not kern")
	}
	if p, e, fm := f.CmapInfo(); fm != 12 || p != 3 || e != 10 {
		t.Errorf("astral cmap should prefer (3,10,12); got %d,%d,%d", p, e, fm)
	}
}

func nilIfEmpty(c []ttf.Contour) []ttf.Contour { return c }

func TestBuildRejectsBadSpecs(t *testing.T) {
	good := syntheticSpec()
	mut := func(f func(*ttf.Spec)) error {
		s := syntheticSpec()
		f(&s)
		_, err := ttf.Build(s)
		return err
	}
	if _, err := ttf.Build(good); err != nil {
		t.Fatal(err)
	}
	cases := map[string]func(*ttf.Spec){
		"upem too small":   func(s *ttf.Spec) { s.UnitsPerEm = 4 },
		"no glyphs":        func(s *ttf.Spec) { s.Glyphs = nil },
		"cmap past glyphs": func(s *ttf.Spec) { s.Cmap['Q'] = 99 },
		"negative advance": func(s *ttf.Spec) { s.Glyphs[0].Advance = -1 },
		"coordinate range": func(s *ttf.Spec) { s.Glyphs[2].Outline.Contours[0][0].X = 99999 },
		"NaN coordinate":   func(s *ttf.Spec) { s.Glyphs[2].Outline.Contours[0][0].Y = math.NaN() },
		"delta wraps int16": func(s *ttf.Spec) {
			s.Glyphs[4].Outline.Contours[0][1].Y = 30000
			s.Glyphs[4].Outline.Contours[0][0].Y = -30000
		},
		"bad kern magnitude": func(s *ttf.Spec) { s.Kern[[2]uint16{1, 1}] = 40000 },
	}
	for name, f := range cases {
		if mut(f) == nil {
			t.Errorf("%s: Build accepted invalid spec", name)
		}
	}
}

func TestLongLocaFont(t *testing.T) {
	// > 128 KiB of glyf data forces the long loca format.
	var gs []ttf.GlyphSpec
	gs = append(gs, ttf.GlyphSpec{Advance: 500})
	big := ttf.Contour{}
	for i := 0; i < 400; i++ {
		a := float64(i) * 2 * math.Pi / 400
		big = append(big, ttf.Point{X: 500 + 400*math.Cos(a), Y: 400 + 400*math.Sin(a), On: i%2 == 0})
	}
	for i := 0; i < 90; i++ {
		gs = append(gs, ttf.GlyphSpec{Outline: ttf.Outline{Contours: []ttf.Contour{big, big}}, Advance: 900})
	}
	b, err := ttf.Build(ttf.Spec{UnitsPerEm: 1000, Ascent: 800, Descent: -200, Glyphs: gs, Cmap: map[rune]uint16{'a': 90}})
	if err != nil {
		t.Fatal(err)
	}
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	o, _ := f.Glyph(90)
	if len(o.Contours) != 2 || len(o.Contours[0]) != 400 {
		t.Errorf("long-loca glyph came back with %d contours", len(o.Contours))
	}
	if bad := f.Verify(); len(bad) != 0 {
		t.Error(bad)
	}
}

// Subsetting a real font must preserve the glyphs, advances, kerning and metrics of the kept text.
func TestSubsetPreservesGlyphsAndKerning(t *testing.T) {
	files, _ := filepath.Glob("../testdata/fonts/*.ttf")
	if len(files) == 0 {
		t.Skip()
	}
	const text = "AVATAR Typography: To Wave, fi fl é ñ ü Ω? 0123 !"
	for _, p := range files {
		b, _ := os.ReadFile(p)
		f, _ := ttf.Parse(b)
		sb, err := f.Subset(text)
		if err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		s, err := ttf.Parse(sb)
		if err != nil {
			t.Fatalf("%s: subset does not parse: %v", p, err)
		}
		if bad := s.Verify(); len(bad) != 0 {
			t.Errorf("%s: %v", p, bad)
		}
		if len(sb) >= len(b)/2 {
			t.Errorf("%s: subset is %d bytes vs %d original", p, len(sb), len(b))
		}
		pairs := 0
		for _, r := range text {
			g, sg := f.Index(r), s.Index(r)
			if (g == 0) != (sg == 0) {
				t.Errorf("%s: U+%04X mapping presence differs", p, r)
				continue
			}
			if g == 0 {
				continue
			}
			og, _ := f.Glyph(g)
			ng, _ := s.Glyph(sg)
			if !sameShape(og, ng) {
				t.Errorf("%s: glyph for %q differs after subset", filepath.Base(p), r)
			}
			if f.Advance(g) != s.Advance(sg) {
				t.Errorf("%s: advance of %q differs", filepath.Base(p), r)
			}
			for _, r2 := range text {
				g2, sg2 := f.Index(r2), s.Index(r2)
				if g2 == 0 {
					continue
				}
				if f.Kerning(g, g2) != s.Kerning(sg, sg2) {
					t.Errorf("%s: kern %q%q: %d vs %d", filepath.Base(p), r, r2, f.Kerning(g, g2), s.Kerning(sg, sg2))
				}
				if f.Kerning(g, g2) != 0 {
					pairs++
				}
			}
		}
		t.Logf("%s: %d → %d bytes, %d kerned pairs preserved", filepath.Base(p), len(b), len(sb), pairs)
	}
}

func sameShape(a, b ttf.Outline) bool {
	if len(a.Contours) != len(b.Contours) {
		return false
	}
	for i := range a.Contours {
		if len(a.Contours[i]) != len(b.Contours[i]) {
			return false
		}
		for j, p := range a.Contours[i] {
			q := b.Contours[i][j]
			if math.Abs(p.X-q.X) > 0.51 || math.Abs(p.Y-q.Y) > 0.51 || p.On != q.On {
				return false
			}
		}
	}
	return true
}
