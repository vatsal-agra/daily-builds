package layout_test

import (
	"math"
	"os"
	"strings"
	"testing"

	"glyph/layout"
	"glyph/ttf"
)

func font(t testing.TB, name string) *ttf.Font {
	b, err := os.ReadFile("../testdata/fonts/" + name)
	if err != nil {
		t.Skip("bundled font missing")
	}
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func near(a, b, tol float64) bool { return math.Abs(a-b) <= tol }

func TestAdvancesAndKerning(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	const size = 100.0
	sc := size / float64(f.UnitsPerEm)
	plain, err := layout.Layout(f, "AV", layout.Options{Size: size, NoKerning: true})
	if err != nil {
		t.Fatal(err)
	}
	kerned, _ := layout.Layout(f, "AV", layout.Options{Size: size})
	a, v := f.Index('A'), f.Index('V')
	if !near(plain.Glyphs[1].X, float64(f.Advance(a))*sc, 1e-9) {
		t.Errorf("unkerned V.X = %v, want advance of A %v", plain.Glyphs[1].X, float64(f.Advance(a))*sc)
	}
	want := (float64(f.Advance(a)) + float64(f.Kerning(a, v))) * sc
	if !near(kerned.Glyphs[1].X, want, 1e-9) || kerned.Glyphs[1].X >= plain.Glyphs[1].X {
		t.Errorf("kerned V.X = %v, want %v (< %v)", kerned.Glyphs[1].X, want, plain.Glyphs[1].X)
	}
	if kerned.Width >= plain.Width {
		t.Error("kerned AV should be narrower")
	}
	// kerning never crosses a line break
	r, _ := layout.Layout(f, "A\nV", layout.Options{Size: size})
	if r.Glyphs[0].X != 0 || r.Glyphs[1].X != 0 || r.Glyphs[1].Line != 1 {
		t.Errorf("newline placement wrong: %+v", r.Glyphs)
	}
	// letter spacing adds to every advance
	ls, _ := layout.Layout(f, "ii", layout.Options{Size: size, LetterSpacing: 5, NoKerning: true})
	base, _ := layout.Layout(f, "ii", layout.Options{Size: size, NoKerning: true})
	if !near(ls.Glyphs[1].X-base.Glyphs[1].X, 5, 1e-9) {
		t.Error("letter spacing not applied")
	}
	// glyph placement scales linearly with size
	small, _ := layout.Layout(f, "Typography", layout.Options{Size: 10})
	big, _ := layout.Layout(f, "Typography", layout.Options{Size: 40})
	for i := range small.Glyphs {
		if !near(big.Glyphs[i].X, 4*small.Glyphs[i].X, 1e-9) {
			t.Fatalf("glyph %d: layout is not linear in size", i)
		}
	}
}

func TestMetricsAndLines(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	r, _ := layout.Layout(f, "a\nb\nc", layout.Options{Size: 50})
	sc := 50.0 / 1000
	if !near(r.Ascent, 1006*sc, 1e-9) || !near(r.Descent, 274*sc, 1e-9) || !near(r.Step, 1280*sc, 1e-9) {
		t.Errorf("metrics: %v %v %v", r.Ascent, r.Descent, r.Step)
	}
	if len(r.Lines) != 3 || !near(r.Glyphs[2].Y, r.Ascent+2*r.Step, 1e-9) || !near(r.Height, r.Ascent+r.Descent+2*r.Step, 1e-9) {
		t.Errorf("lines/height: %v %v", len(r.Lines), r.Height)
	}
	r2, _ := layout.Layout(f, "a\nb", layout.Options{Size: 50, LineHeight: 2})
	if !near(r2.Step, 2*r.Step, 1e-9) {
		t.Error("line height multiplier ignored")
	}
}

func TestEdgeCasesNeverPanic(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	for name, text := range map[string]string{
		"empty":     "",
		"newlines":  "\n\n\n",
		"crlf":      "a\r\nb\rc",
		"spaces":    "      ",
		"controls":  "a\x00b\x07c\u200bd\ufeffe",
		"tab":       "a\tb",
		"invalid":   "\xff\xfe bad \xc3",
		"emoji":     "x😀y",
		"cjk":       "中文",
		"combining": "é",
		"long":      strings.Repeat("word ", 400),
	} {
		for _, w := range []float64{0, 1, 37, 500} {
			for _, al := range []layout.Align{layout.Left, layout.Center, layout.Right, layout.Justify} {
				r, err := layout.Layout(f, text, layout.Options{Size: 17, Width: w, Align: al})
				if err != nil {
					t.Fatalf("%s: %v", name, err)
				}
				if math.IsNaN(r.Width) || math.IsNaN(r.Height) || r.Height <= 0 {
					t.Fatalf("%s w=%v: bad size %v x %v", name, w, r.Width, r.Height)
				}
				for _, g := range r.Glyphs {
					if math.IsNaN(g.X) || math.IsInf(g.X, 0) {
						t.Fatalf("%s: NaN position", name)
					}
				}
			}
		}
	}
	r, _ := layout.Layout(f, "a\x00b", layout.Options{Size: 10})
	if len(r.Glyphs) != 2 {
		t.Errorf("control character produced a glyph: %d", len(r.Glyphs))
	}
	r, _ = layout.Layout(f, "x中y", layout.Options{Size: 10})
	if len(r.Glyphs) != 3 || r.Glyphs[1].GID != 0 {
		t.Error("unmapped character must become .notdef")
	}
	tab, _ := layout.Layout(f, "a\tb", layout.Options{Size: 10})
	sp, _ := layout.Layout(f, "a    b", layout.Options{Size: 10, NoKerning: true})
	if !near(tab.Glyphs[2].X, sp.Glyphs[5].X, 1e-6) {
		t.Errorf("tab advance %v != four spaces %v", tab.Glyphs[2].X, sp.Glyphs[5].X)
	}
}

func TestInvalidOptions(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	for name, o := range map[string]layout.Options{
		"zero":     {Size: 0},
		"negative": {Size: -3},
		"nan":      {Size: math.NaN()},
		"inf":      {Size: math.Inf(1)},
		"huge":     {Size: 1e6},
		"width":    {Size: 10, Width: -1},
	} {
		if _, err := layout.Layout(f, "x", o); err == nil {
			t.Errorf("%s accepted", name)
		}
	}
}

func lineText(r *layout.Result, i int) string {
	var sb strings.Builder
	for _, g := range r.Glyphs[r.Lines[i].Start:r.Lines[i].End] {
		sb.WriteRune(g.Rune)
	}
	return sb.String()
}

func TestWrapInvariants(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	text := "The quick brown fox jumps over the lazy dog, and then something-hyphenated happens; supercalifragilisticexpialidocious!"
	for _, w := range []float64{80, 150, 260, 600} {
		r, err := layout.Layout(f, text, layout.Options{Size: 20, Width: w})
		if err != nil {
			t.Fatal(err)
		}
		var rebuilt []string
		for i, ln := range r.Lines {
			if ln.Width > w+1e-6 {
				t.Errorf("w=%v line %d is %.1f wide: %q", w, i, ln.Width, lineText(r, i))
			}
			rebuilt = append(rebuilt, strings.TrimRight(lineText(r, i), " "))
		}
		// content preserved: removing all whitespace gives back the original word characters in order
		if strings.Join(strings.Fields(strings.Join(rebuilt, " ")), "") != strings.Join(strings.Fields(text), "") {
			t.Errorf("w=%v: wrapped text lost or reordered characters", w)
		}
		// greedy: the first word of line i+1 would not have fit on line i
		for i := 0; i+1 < len(r.Lines); i++ {
			next := strings.Fields(lineText(r, i+1))
			if len(next) == 0 {
				continue
			}
			w1, _ := layout.Layout(f, strings.TrimRight(lineText(r, i), " ")+" "+next[0], layout.Options{Size: 20})
			if w1.Width <= w && !strings.Contains(next[0], "-") && len(next[0]) < 15 {
				t.Errorf("w=%v: line %d should have taken %q (fits in %.1f)", w, i, next[0], w1.Width)
			}
		}
	}
	// a word wider than the box is split by character, never dropped or looped on
	r, _ := layout.Layout(f, strings.Repeat("W", 30), layout.Options{Size: 20, Width: 60})
	if len(r.Lines) < 8 || len(r.Glyphs) != 30 {
		t.Errorf("hard split: %d lines, %d glyphs", len(r.Lines), len(r.Glyphs))
	}
	for i, ln := range r.Lines {
		if i < len(r.Lines)-1 && ln.End-ln.Start < 1 {
			t.Error("empty line in hard split")
		}
	}
	// hyphen is a break opportunity
	r, _ = layout.Layout(f, "well-known fact", layout.Options{Size: 20, Width: 75})
	if lineText(r, 0) != "well-" {
		t.Errorf("hyphen break: first line %q", lineText(r, 0))
	}
}

func TestAlignment(t *testing.T) {
	f := font(t, "Lora-Regular.ttf")
	text := "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
	opts := layout.Options{Size: 18, Width: 200}
	left, _ := layout.Layout(f, text, opts)
	for _, ln := range left.Lines {
		if left.Glyphs[ln.Start].X != 0 {
			t.Error("left-aligned line does not start at 0")
		}
	}
	opts.Align = layout.Right
	r, _ := layout.Layout(f, text, opts)
	for i, ln := range r.Lines {
		last := r.Glyphs[ln.End-1]
		for j := ln.End - 1; j > ln.Start && r.Glyphs[j].Rune == ' '; j-- {
			last = r.Glyphs[j-1]
		}
		right := last.X + float64(f.Advance(last.GID))*18/1000
		if !near(right, 200, 0.01) {
			t.Errorf("right-aligned line %d ends at %.2f", i, right)
		}
	}
	opts.Align = layout.Center
	r, _ = layout.Layout(f, text, opts)
	for i, ln := range r.Lines {
		l, rr := r.Glyphs[ln.Start].X, 200-ln.Width-r.Glyphs[ln.Start].X
		if !near(l, rr, 0.01) {
			t.Errorf("centered line %d margins %.2f vs %.2f", i, l, rr)
		}
	}
	opts.Align = layout.Justify
	r, _ = layout.Layout(f, text, opts)
	if len(r.Lines) < 3 {
		t.Fatal("need several lines")
	}
	rightEdge := func(ln layout.Line) float64 { // measured from glyph positions, not from the reported width
		j := ln.End - 1
		for j > ln.Start && r.Glyphs[j].Rune == ' ' {
			j--
		}
		return r.Glyphs[j].X + float64(f.Advance(r.Glyphs[j].GID))*18/1000
	}
	for i, ln := range r.Lines {
		if i < len(r.Lines)-1 && (!near(ln.Width, 200, 0.01) || !near(rightEdge(ln), 200, 0.01)) {
			t.Errorf("justified line %d: reported width %.2f, right edge %.2f, want 200", i, ln.Width, rightEdge(ln))
		}
		if i == len(r.Lines)-1 && ln.Width >= 200 {
			t.Error("last line must not be stretched")
		}
	}
	// a single-word line cannot be justified and must not blow up
	r, _ = layout.Layout(f, "supercalifragilistic word", layout.Options{Size: 18, Width: 190, Align: layout.Justify})
	for _, g := range r.Glyphs {
		if math.IsNaN(g.X) || g.X < 0 {
			t.Fatalf("bad position %v", g.X)
		}
	}
}

func TestParseAlign(t *testing.T) {
	for in, want := range map[string]layout.Align{"": layout.Left, "LEFT": layout.Left, "Centre": layout.Center, "center": layout.Center, "right": layout.Right, "justify": layout.Justify} {
		if got, err := layout.ParseAlign(in); err != nil || got != want {
			t.Errorf("%q → %v, %v", in, got, err)
		}
	}
	if _, err := layout.ParseAlign("middle"); err == nil {
		t.Error("middle accepted")
	}
}

func TestMonospaceHasNoKerning(t *testing.T) {
	f := font(t, "JetBrainsMono-Regular.ttf")
	r, _ := layout.Layout(f, "iiWWii", layout.Options{Size: 30})
	step := r.Glyphs[1].X - r.Glyphs[0].X
	for i := 1; i < len(r.Glyphs); i++ {
		if !near(r.Glyphs[i].X-r.Glyphs[i-1].X, step, 1e-9) {
			t.Fatal("monospace glyphs are not evenly spaced")
		}
	}
}
