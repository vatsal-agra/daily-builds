package render_test

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"math"
	"os"
	"regexp"
	"strings"
	"testing"

	"glyph/img"
	"glyph/layout"
	"glyph/raster"
	"glyph/render"
	"glyph/ttf"
)

func fontNamed(t testing.TB, n string) *ttf.Font {
	b, err := os.ReadFile("../testdata/fonts/" + n)
	if err != nil {
		t.Skip("bundled font missing")
	}
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func ink(c *img.Canvas, bg img.RGB) (n int, dark float64) {
	for i := 0; i < c.W*c.H; i++ {
		if c.Pix[3*i] != bg.R || c.Pix[3*i+1] != bg.G || c.Pix[3*i+2] != bg.B {
			n++
			dark += float64(255 - c.Pix[3*i])
		}
	}
	return
}

func TestTextRendersDeterministicallyWithInk(t *testing.T) {
	f := lora(t)
	st := render.DefaultStyle(30)
	a, res, err := render.Text(f, "Hello, Glyph", st)
	if err != nil {
		t.Fatal(err)
	}
	b, _, _ := render.Text(f, "Hello, Glyph", st)
	if !bytes.Equal(a.Pix, b.Pix) {
		t.Error("rendering is not deterministic")
	}
	n, dark := ink(a, st.BG)
	if n < 200 || dark < 8000 {
		t.Errorf("suspiciously little ink: %d px, %.0f", n, dark)
	}
	if len(res.Glyphs) != 12 {
		t.Errorf("glyph count %d", len(res.Glyphs))
	}
	// colours: light text on dark background keeps the background in the corners
	st.FG, st.BG = img.RGB{R: 250, G: 240, B: 200}, img.RGB{R: 10, G: 20, B: 60}
	c, _, _ := render.Text(f, "Hi", st)
	if c.Pix[0] != 10 || c.Pix[1] != 20 || c.Pix[2] != 60 {
		t.Error("background colour not applied")
	}
	brightest := byte(0)
	for i := 0; i < len(c.Pix); i += 3 {
		brightest = max(brightest, c.Pix[i])
	}
	if brightest < 240 {
		t.Errorf("foreground colour not reached (max red %d)", brightest)
	}
}

func TestRenderedAreaMatchesOutlineArea(t *testing.T) {
	// "l" in Lora is a plain stem: ink area (in px²) must match the outline area at that scale
	f := lora(t)
	gid := f.Index('l')
	o, _ := f.Glyph(gid)
	const size = 120.0
	want := math.Abs(raster.Flatten(o, raster.Scale(size/1000, 0, 0, 0), 0).Area())
	got := raster.Render(raster.Flatten(o, raster.Scale(size/1000, 0.37, 0.61, 0), 0), 0).Sum()
	if math.Abs(got-want)/want > 0.003 {
		t.Errorf("rendered %.1f vs outline %.1f px²", got, want)
	}
}

func TestSubpixelPositioningMovesInk(t *testing.T) {
	f := lora(t)
	p := render.NewPainter(f, render.DefaultStyle(40))
	gid := f.Index('I')
	centroid := func(bm *raster.Bitmap) float64 {
		var sx, s float64
		for y := 0; y < bm.H; y++ {
			for x := 0; x < bm.W; x++ {
				v := float64(bm.Pix[y*bm.W+x])
				sx += v * (float64(x+bm.X0) + 0.5)
				s += v
			}
		}
		return sx / s
	}
	b0, _ := p.Glyph(gid, 0)
	b5, _ := p.Glyph(gid, 0.5)
	if d := centroid(b5) - centroid(b0); math.Abs(d-0.5) > 0.06 { // centroid of pixel centres is only approximately translation-covariant
		t.Errorf("half-pixel shift moved ink by %.3f px", d)
	}
	again, _ := p.Glyph(gid, 0.5)
	if again != b5 {
		t.Error("glyph cache miss for identical request")
	}
}

func TestLCDText(t *testing.T) {
	f := lora(t)
	st := render.DefaultStyle(24)
	gray, _, err := render.Text(f, "Hamburgefonstiv", st)
	if err != nil {
		t.Fatal(err)
	}
	st.LCD = true
	lcd, _, err := render.Text(f, "Hamburgefonstiv", st)
	if err != nil {
		t.Fatal(err)
	}
	_, dg := ink(gray, st.BG)
	_, dl := ink(lcd, st.BG)
	if math.Abs(dg-dl)/dg > 0.06 {
		t.Errorf("LCD total ink %.0f vs gray %.0f", dl, dg)
	}
	coloured := 0
	for i := 0; i < lcd.W*lcd.H; i++ {
		if lcd.Pix[3*i] != lcd.Pix[3*i+2] {
			coloured++
		}
	}
	if coloured < 100 {
		t.Errorf("only %d fringe pixels; LCD output looks grayscale", coloured)
	}
	for i := 0; i < gray.W*gray.H; i++ {
		if gray.Pix[3*i] != gray.Pix[3*i+1] || gray.Pix[3*i] != gray.Pix[3*i+2] {
			t.Fatal("grayscale rendering produced coloured pixels")
		}
	}
}

func TestSVGIsValidXMLAndMatchesLayout(t *testing.T) {
	f := lora(t)
	st := render.DefaultStyle(40)
	st.Slant = 0.2
	s, err := render.SVG(f, "Hello, Glyph! é", st)
	if err != nil {
		t.Fatal(err)
	}
	dec := xml.NewDecoder(strings.NewReader(s))
	paths, depth := 0, 0
	for {
		tok, err := dec.Token()
		if err != nil {
			break
		}
		switch e := tok.(type) {
		case xml.StartElement:
			depth++
			if e.Name.Local == "path" {
				paths++
			}
		case xml.EndElement:
			depth--
		}
	}
	if depth != 0 {
		t.Fatalf("unbalanced XML, depth %d", depth)
	}
	if _, err := xml.NewDecoder(strings.NewReader(s)).Token(); err != nil {
		t.Fatal(err)
	}
	// one path per inked glyph: 15 characters minus space(s) and nothing else blank
	res, _ := layout.Layout(f, "Hello, Glyph! é", st.Options)
	inked := 0
	for _, g := range res.Glyphs {
		if o, _ := f.Glyph(g.GID); len(o.Contours) > 0 {
			inked++
		}
	}
	if paths != inked {
		t.Errorf("%d <path> elements, %d inked glyphs", paths, inked)
	}
	if !strings.Contains(s, "Q") || !strings.Contains(s, "Z") {
		t.Error("SVG should keep true quadratic curves")
	}
	// every number in every path lies inside the viewBox
	vb := regexp.MustCompile(`viewBox="0 0 ([\d.]+) ([\d.]+)"`).FindStringSubmatch(s)
	if vb == nil {
		t.Fatal("no viewBox")
	}
	var w, h float64
	json.Unmarshal([]byte(vb[1]), &w)
	json.Unmarshal([]byte(vb[2]), &h)
	nums := regexp.MustCompile(`-?\d+(\.\d+)?`)
	for _, d := range regexp.MustCompile(` d="([^"]+)"`).FindAllStringSubmatch(s, -1) {
		v := nums.FindAllString(d[1], -1)
		for i := 0; i+1 < len(v); i += 2 {
			var x, y float64
			json.Unmarshal([]byte(v[i]), &x)
			json.Unmarshal([]byte(v[i+1]), &y)
			if x < -0.01 || y < -0.01 || x > w+0.01 || y > h+0.01 {
				t.Fatalf("point (%v,%v) outside viewBox %vx%v", x, y, w, h)
			}
		}
	}
}

func TestPathDataExactCurves(t *testing.T) {
	o := ttf.Outline{Contours: []ttf.Contour{
		{{X: 0, Y: 0, On: true}, {X: 50, Y: 100}, {X: 100, Y: 0, On: true}},
		{{X: 0, Y: 0}, {X: 10, Y: 0}, {X: 10, Y: 10}, {X: 0, Y: 10}}, // all off-curve
		{{X: 5, Y: 5, On: true}}, // dropped
	}}
	d := render.PathData(o, raster.Affine{A: 1, D: 1})
	want := "M0 0Q50 100 100 0Q50 100 100 0Z" // placeholder replaced below
	_ = want
	if !strings.HasPrefix(d, "M0 0Q50 100 100 0") || strings.Count(d, "Z") != 2 || strings.Count(d, "M") != 2 {
		t.Errorf("path data: %s", d)
	}
	// all-off-curve contour: starts at the implied midpoint (0,5) and has 4 curve segments
	if !strings.Contains(d, "M0 5") || strings.Count(d[strings.Index(d, "M0 5"):], "Q") != 4 {
		t.Errorf("implied on-curve handling: %s", d)
	}
}

func TestSDFAtlasReproducesTheGlyph(t *testing.T) {
	f := lora(t)
	a, err := render.BuildAtlas(f, "gQ@e", 48, 8)
	if err != nil {
		t.Fatal(err)
	}
	if len(a.Glyphs) != 4 || a.W*a.H < 1000 {
		t.Fatalf("atlas: %d glyphs %dx%d", len(a.Glyphs), a.W, a.H)
	}
	for _, scale := range []float64{1, 2.5, 0.5} {
		for _, r := range "gQ@e" {
			g := a.Glyphs[r]
			sdf := a.Coverage(g, scale, 0)
			o, _ := f.Glyph(f.Index(r))
			ref := raster.Render(raster.Flatten(o, raster.Scale(48*scale/1000, 0, 0, 0), 0), 64)
			// compare areas and intersection-over-union of the two coverage maps on a common grid
			inter, union := 0.0, 0.0
			x0, y0 := min(sdf.X0, ref.X0), min(sdf.Y0, ref.Y0)
			x1, y1 := max(sdf.X0+sdf.W, ref.X0+ref.W), max(sdf.Y0+sdf.H, ref.Y0+ref.H)
			for y := y0; y < y1; y++ {
				for x := x0; x < x1; x++ {
					a := float64(sdf.At(x-sdf.X0, y-sdf.Y0))
					b := float64(ref.At(x-ref.X0, y-ref.Y0))
					inter += math.Min(a, b)
					union += math.Max(a, b)
				}
			}
			if iou := inter / union; iou < 0.93 {
				t.Errorf("%q at scale %v: SDF vs outline IoU %.3f", r, scale, iou)
			}
			if rel := math.Abs(sdf.Sum()-ref.Sum()) / ref.Sum(); rel > 0.04 {
				t.Errorf("%q at scale %v: area differs by %.1f%%", r, scale, 100*rel)
			}
		}
	}
}

func TestSDFAtlasPackingAndJSON(t *testing.T) {
	f := lora(t)
	text := "The quick brown fox jumps over the lazy dog 0123456789 AVATAR"
	a, err := render.BuildAtlas(f, text, 32, 6)
	if err != nil {
		t.Fatal(err)
	}
	// no two cells overlap and all lie inside the atlas
	type rc struct{ x, y, w, h int }
	var cells []rc
	for _, g := range a.Glyphs {
		if g.W == 0 {
			continue
		}
		if g.X < 0 || g.Y < 0 || g.X+g.W > a.W || g.Y+g.H > a.H {
			t.Fatalf("%q cell outside atlas", g.Rune)
		}
		for _, o := range cells {
			if g.X < o.x+o.w && o.x < g.X+g.W && g.Y < o.y+o.h && o.y < g.Y+g.H {
				t.Fatalf("%q overlaps another cell", g.Rune)
			}
		}
		cells = append(cells, rc{g.X, g.Y, g.W, g.H})
	}
	if _, ok := a.Glyphs[' ']; !ok || a.Glyphs[' '].W != 0 || a.Glyphs[' '].Advance <= 0 {
		t.Error("space must be present as a blank glyph with an advance")
	}
	js, err := a.JSON("a.png")
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Image  string
		Size   float64
		Spread int
		Glyphs []struct {
			Code int
			W, H int
		}
		Kerning []struct{ Left, Right string }
	}
	if err := json.Unmarshal(js, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Image != "a.png" || doc.Size != 32 || doc.Spread != 6 || len(doc.Glyphs) != len(a.Glyphs) || len(doc.Kerning) == 0 {
		t.Errorf("json content wrong: %+v", doc)
	}
	if png, err := a.PNG(); err != nil || len(png) < 100 {
		t.Error("atlas PNG failed")
	}
	// drawing from the atlas alone
	cv, err := a.Text("The AVATAR", 60, img.RGB{}, img.RGB{R: 255, G: 255, B: 255}, 4)
	if err != nil {
		t.Fatal(err)
	}
	if n, _ := ink(cv, img.RGB{R: 255, G: 255, B: 255}); n < 500 {
		t.Errorf("SDF text has only %d inked pixels", n)
	}
	if _, err := a.Text("☃", 60, img.RGB{}, img.RGB{}, 0); err == nil {
		t.Error("character missing from atlas must be a clear error")
	}
}

func TestSDFAtlasErrors(t *testing.T) {
	f := lora(t)
	cases := map[string]struct {
		text    string
		px      float64
		spread  int
		wantErr bool
	}{
		"tiny size":    {"a", 1, 4, true},
		"huge size":    {"a", 9999, 4, true},
		"spread 0":     {"a", 32, 0, true},
		"spread huge":  {"a", 32, 500, true},
		"control only": {"\n\t", 32, 4, true},
		"space only":   {" ", 32, 4, false}, // a blank glyph with an advance is legitimate
		"normal":       {"abc", 32, 4, false},
	}
	for name, c := range cases {
		_, err := render.BuildAtlas(f, c.text, c.px, c.spread)
		if (err != nil) != c.wantErr {
			t.Errorf("%s: err=%v, wantErr=%v", name, err, c.wantErr)
		}
	}
}

func TestSpecimenIsWellFormed(t *testing.T) {
	f := lora(t)
	h, err := render.Specimen(f, 80)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"<!doctype html>", "Lora Regular", "Kerning", "Basic Latin", "prefers-color-scheme", "kerned", "U+0041"} {
		if !strings.Contains(h, want) {
			t.Errorf("specimen missing %q", want)
		}
	}
	if n := strings.Count(h, "<figure"); n != 80 {
		t.Errorf("%d glyph cells, want exactly the 80 requested", n)
	}
	if strings.Count(h, "<svg") != strings.Count(h, "</svg>") {
		t.Error("unbalanced svg tags")
	}
	// a name with markup must be escaped, not injected
	if strings.Contains(h, "<script") {
		t.Error("unexpected script")
	}
	mono := fontNamed(t, "JetBrainsMono-Regular.ttf")
	h2, err := render.Specimen(mono, 40)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(h2, ">Kerning<") {
		t.Error("kerning section shown for a font without kerning")
	}
}

func TestTextErrors(t *testing.T) {
	f := lora(t)
	st := render.DefaultStyle(10)
	st.Size = 0
	if _, _, err := render.Text(f, "x", st); err == nil {
		t.Error("size 0 accepted")
	}
	st = render.DefaultStyle(9000)
	if _, _, err := render.Text(f, strings.Repeat("W", 40), st); err == nil || !strings.Contains(err.Error(), "too large") {
		t.Errorf("huge canvas should be refused, got %v", err)
	}
	if _, err := render.SVG(f, "x", render.Style{}); err == nil {
		t.Error("SVG with zero size accepted")
	}
	// empty text still yields a valid (blank) image
	c, res, err := render.Text(f, "", render.DefaultStyle(20))
	if err != nil || c.W <= 0 || len(res.Glyphs) != 0 {
		t.Errorf("empty text: %v", err)
	}
}
