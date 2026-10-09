package render_test

import (
	"os"
	"testing"

	"glyph/img"
	"glyph/raster"
	"glyph/render"
	"glyph/ttf"
)

func lora(t testing.TB) *ttf.Font {
	b, err := os.ReadFile("../testdata/fonts/Lora-Regular.ttf")
	if err != nil {
		t.Skip("bundled font missing")
	}
	f, err := ttf.Parse(b)
	if err != nil {
		t.Fatal(err)
	}
	return f
}

// inkTouchesEdge reports whether any non-background pixel sits in the outermost ring.
func inkTouchesEdge(c *img.Canvas, bg img.RGB) bool {
	at := func(x, y int) bool {
		i := 3 * (y*c.W + x)
		return c.Pix[i] != bg.R || c.Pix[i+1] != bg.G || c.Pix[i+2] != bg.B
	}
	for x := 0; x < c.W; x++ {
		if at(x, 0) || at(x, c.H-1) {
			return true
		}
	}
	for y := 0; y < c.H; y++ {
		if at(0, y) || at(c.W-1, y) {
			return true
		}
	}
	return false
}

// REVIEW R3: a wrap width narrower than a single glyph used to clip the ink.
func TestNarrowWrapDoesNotClip(t *testing.T) {
	st := render.DefaultStyle(60)
	st.Width = 5
	st.Padding = 0
	cv, _, err := render.Text(lora(t), "WM", st)
	if err != nil {
		t.Fatal(err)
	}
	if cv.W < 40 {
		t.Errorf("canvas only %d px wide for 60px glyphs", cv.W)
	}
	if inkTouchesEdge(cv, st.BG) {
		t.Error("ink touches the canvas edge (clipped)")
	}
}

// REVIEW R4: negative slant used to hang off the left edge.
func TestSlantNeverClips(t *testing.T) {
	for _, sl := range []float64{-0.6, -0.2, 0, 0.3, 0.6} {
		st := render.DefaultStyle(64)
		st.Slant, st.Padding = sl, 0
		for _, txt := range []string{"Hy/jfV", "fg"} {
			cv, _, err := render.Text(lora(t), txt, st)
			if err != nil {
				t.Fatal(err)
			}
			if inkTouchesEdge(cv, st.BG) {
				t.Errorf("slant %v %q: ink touches canvas edge", sl, txt)
			}
		}
	}
}

// REVIEW R2: a hostile outline must not allocate an unbounded bitmap.
func TestRenderBitmapBounded(t *testing.T) {
	huge := raster.Path{{{X: -1e7, Y: -1e7}, {X: 1e7, Y: -1e7}, {X: 1e7, Y: 1e7}, {X: -1e7, Y: 1e7}}}
	bm := raster.Render(huge, 4)
	if bm.W > raster.MaxDim || bm.H > raster.MaxDim {
		t.Fatalf("bitmap %dx%d exceeds MaxDim %d", bm.W, bm.H, raster.MaxDim)
	}
	if bm.Sum() < float64(bm.W*bm.H)*0.99 {
		t.Errorf("clipped window should be fully covered, got %.0f of %d", bm.Sum(), bm.W*bm.H)
	}
}
