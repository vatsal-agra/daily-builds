package render

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"

	"glyph/img"
	"glyph/raster"
	"glyph/ttf"
)

// AtlasGlyph locates one glyph's distance-field cell in the atlas.
type AtlasGlyph struct {
	Rune               rune
	X, Y, W, H         int     // cell rectangle in atlas pixels (W=H=0 for blank glyphs such as space)
	BearingX, BearingY float64 // pen-origin → cell top-left (px at atlas size, y down)
	Advance            float64 // px at atlas size
}

// Atlas is a packed 8-bit signed-distance-field glyph atlas (127.5 = outline).
type Atlas struct {
	Size                    float64 // px per em the glyphs were rasterized at
	Spread                  int     // distance range: ±Spread px maps to 0..255
	W, H                    int
	Pix                     []byte
	Glyphs                  map[rune]AtlasGlyph
	Kern                    map[[2]rune]float64
	Ascent, Descent, Height float64
}

// BuildAtlas rasterizes distance fields for every distinct rune in text.
func BuildAtlas(f *ttf.Font, text string, px float64, spread int) (*Atlas, error) {
	if !(px >= 4 && px <= 512) {
		return nil, fmt.Errorf("sdf glyph size must be in [4, 512] px, got %v", px)
	}
	if spread < 1 || spread > 64 {
		return nil, fmt.Errorf("sdf spread must be in [1, 64] px, got %d", spread)
	}
	seen := map[rune]bool{}
	var runes []rune
	for _, r := range text {
		if r < 0x20 || seen[r] {
			continue
		}
		seen[r] = true
		runes = append(runes, r)
	}
	if len(runes) == 0 {
		return nil, fmt.Errorf("no printable characters to put in the atlas")
	}
	sort.Slice(runes, func(i, j int) bool { return runes[i] < runes[j] })
	scale := px / float64(f.UnitsPerEm)
	type cell struct {
		r   rune
		sdf *raster.SDF
		adv float64
	}
	var cells []cell
	area := 0
	for _, r := range runes {
		g := f.Index(r)
		o, err := f.Glyph(g)
		if err != nil {
			return nil, err
		}
		c := cell{r: r, adv: float64(f.Advance(g)) * scale}
		if len(o.Contours) > 0 {
			c.sdf = raster.SignedDistance(raster.Flatten(o, raster.Scale(scale, 0, 0, 0), 0), spread)
			area += (c.sdf.W + 1) * (c.sdf.H + 1)
		}
		cells = append(cells, c)
	}
	// shelf packing: tallest first, power-of-two width
	order := make([]int, len(cells))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(a, b int) bool {
		ha, hb := 0, 0
		if cells[order[a]].sdf != nil {
			ha = cells[order[a]].sdf.H
		}
		if cells[order[b]].sdf != nil {
			hb = cells[order[b]].sdf.H
		}
		return ha > hb
	})
	width := 64
	for float64(width*width) < float64(area)*1.25 && width < 4096 {
		width *= 2
	}
	pos := map[rune][2]int{}
	x, y, rowH := 0, 0, 0
	for _, i := range order {
		c := cells[i]
		if c.sdf == nil {
			continue
		}
		if c.sdf.W > width {
			return nil, fmt.Errorf("glyph %q (%d px wide) does not fit a %d px atlas", c.r, c.sdf.W, width)
		}
		if x+c.sdf.W > width {
			x, y, rowH = 0, y+rowH+1, 0
		}
		pos[c.r] = [2]int{x, y}
		x += c.sdf.W + 1
		rowH = max(rowH, c.sdf.H)
	}
	height := 1
	for height < y+rowH {
		height *= 2
	}
	if height > 4096 {
		return nil, fmt.Errorf("atlas would need %dx%d px; use fewer glyphs or a smaller size", width, height)
	}
	a := &Atlas{Size: px, Spread: spread, W: width, H: height, Pix: make([]byte, width*height),
		Glyphs: map[rune]AtlasGlyph{}, Kern: map[[2]rune]float64{},
		Ascent: float64(f.Ascent) * scale, Descent: float64(-f.Descent) * scale,
		Height: float64(f.Ascent-f.Descent+f.LineGap) * scale}
	for i := range a.Pix {
		a.Pix[i] = 0 // far outside
	}
	for _, c := range cells {
		ag := AtlasGlyph{Rune: c.r, Advance: c.adv}
		if c.sdf != nil {
			p := pos[c.r]
			ag.X, ag.Y, ag.W, ag.H = p[0], p[1], c.sdf.W, c.sdf.H
			ag.BearingX, ag.BearingY = float64(c.sdf.X0), float64(c.sdf.Y0)
			for yy := 0; yy < c.sdf.H; yy++ {
				for xx := 0; xx < c.sdf.W; xx++ {
					d := float64(c.sdf.Dist[yy*c.sdf.W+xx])
					v := math.Round(255 * (0.5 + d/(2*float64(spread))))
					a.Pix[(p[1]+yy)*width+p[0]+xx] = uint8(math.Max(0, math.Min(255, v)))
				}
			}
		}
		a.Glyphs[c.r] = ag
	}
	for _, l := range runes {
		for _, r := range runes {
			if k := f.Kerning(f.Index(l), f.Index(r)); k != 0 {
				a.Kern[[2]rune{l, r}] = float64(k) * scale
			}
		}
	}
	return a, nil
}

// Distance samples the stored distance (px at atlas size, + inside) at continuous
// cell coordinates (u,v) of glyph g using bilinear filtering.
func (a *Atlas) Distance(g AtlasGlyph, u, v float64) float64 {
	fx, fy := u-0.5, v-0.5
	x0, y0 := int(math.Floor(fx)), int(math.Floor(fy))
	tx, ty := fx-float64(x0), fy-float64(y0)
	get := func(x, y int) float64 {
		x, y = max(0, min(g.W-1, x)), max(0, min(g.H-1, y))
		return (float64(a.Pix[(g.Y+y)*a.W+g.X+x])/255 - 0.5) * 2 * float64(a.Spread)
	}
	top := get(x0, y0)*(1-tx) + get(x0+1, y0)*tx
	bot := get(x0, y0+1)*(1-tx) + get(x0+1, y0+1)*tx
	return top*(1-ty) + bot*ty
}

// Coverage rasterizes one glyph at scale s (output px per atlas px) by thresholding
// the distance field with a 1-output-pixel linear ramp. Origin is the pen position.
func (a *Atlas) Coverage(g AtlasGlyph, s, fx float64) *raster.Bitmap {
	if g.W == 0 {
		return &raster.Bitmap{}
	}
	left, top := (g.BearingX*s)+fx, g.BearingY*s
	x0, y0 := int(math.Floor(left)), int(math.Floor(top))
	w, h := int(math.Ceil(float64(g.W)*s))+2, int(math.Ceil(float64(g.H)*s))+2
	bm := &raster.Bitmap{W: w, H: h, X0: x0, Y0: y0, Pix: make([]float32, w*h)}
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			u := (float64(x0+x) + 0.5 - left) / s
			v := (float64(y0+y) + 0.5 - top) / s
			if u < 0 || v < 0 || u > float64(g.W) || v > float64(g.H) {
				continue
			}
			d := a.Distance(g, u, v) * s
			bm.Pix[y*w+x] = float32(math.Max(0, math.Min(1, 0.5+d)))
		}
	}
	return bm
}

// Text draws text from the atlas alone (no font needed) at the given pixel size.
func (a *Atlas) Text(text string, size float64, fg, bg img.RGB, pad int) (*img.Canvas, error) {
	if !(size >= 1 && size <= 2000) {
		return nil, fmt.Errorf("size must be in [1, 2000]")
	}
	s := size / a.Size
	type pg struct {
		g AtlasGlyph
		x float64
		y float64
	}
	var placed []pg
	y := a.Ascent * s
	maxX := 0.0
	lines := 1
	for li, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		if li > 0 {
			y += a.Height * s
			lines++
		}
		x := 0.0
		var prev rune
		for i, r := range []rune(line) {
			g, ok := a.Glyphs[r]
			if !ok {
				if r < 0x20 {
					continue
				}
				return nil, fmt.Errorf("character %q is not in this atlas", r)
			}
			if i > 0 {
				x += a.Kern[[2]rune{prev, r}] * s
			}
			placed = append(placed, pg{g, x, y})
			x += g.Advance * s
			prev = r
		}
		maxX = math.Max(maxX, x)
	}
	h := int(math.Ceil((a.Ascent+a.Descent)*s+a.Height*s*float64(lines-1))) + 2*pad + 2
	w := int(math.Ceil(maxX)) + 2*pad + 2
	if w*h > MaxPixels {
		return nil, fmt.Errorf("canvas %dx%d too large", w, h)
	}
	cv := img.NewCanvas(w, h, bg)
	for _, p := range placed {
		ix := math.Floor(p.x)
		bm := a.Coverage(p.g, s, p.x-ix)
		cv.Blend(bm, pad+int(ix), pad+int(math.Round(p.y)), fg, true)
	}
	return cv, nil
}

// Preview renders the atlas texture itself (distance values as grey) as RGB.
func (a *Atlas) PNG() ([]byte, error) {
	var b []byte
	w := &sliceWriter{&b}
	if err := img.EncodePNG(w, a.W, a.H, 1, a.Pix); err != nil {
		return nil, err
	}
	return b, nil
}

type sliceWriter struct{ b *[]byte }

func (w *sliceWriter) Write(p []byte) (int, error) { *w.b = append(*w.b, p...); return len(p), nil }

// JSON describes the atlas layout for use by a game engine / shader.
func (a *Atlas) JSON(imageName string) ([]byte, error) {
	type glyph struct {
		Char     string  `json:"char"`
		Code     int     `json:"code"`
		X        int     `json:"x"`
		Y        int     `json:"y"`
		W        int     `json:"w"`
		H        int     `json:"h"`
		BearingX float64 `json:"bearingX"`
		BearingY float64 `json:"bearingY"`
		Advance  float64 `json:"advance"`
	}
	type kern struct {
		Left, Right string
		Value       float64
	}
	doc := struct {
		Image   string  `json:"image"`
		Size    float64 `json:"size"`
		Spread  int     `json:"spread"`
		W       int     `json:"width"`
		H       int     `json:"height"`
		Ascent  float64 `json:"ascent"`
		Descent float64 `json:"descent"`
		Line    float64 `json:"lineHeight"`
		Glyphs  []glyph `json:"glyphs"`
		Kerning []kern  `json:"kerning,omitempty"`
	}{Image: imageName, Size: a.Size, Spread: a.Spread, W: a.W, H: a.H, Ascent: a.Ascent, Descent: a.Descent, Line: a.Height}
	rs := make([]rune, 0, len(a.Glyphs))
	for r := range a.Glyphs {
		rs = append(rs, r)
	}
	sort.Slice(rs, func(i, j int) bool { return rs[i] < rs[j] })
	for _, r := range rs {
		g := a.Glyphs[r]
		doc.Glyphs = append(doc.Glyphs, glyph{string(r), int(r), g.X, g.Y, g.W, g.H, g.BearingX, g.BearingY, g.Advance})
	}
	ks := make([][2]rune, 0, len(a.Kern))
	for k := range a.Kern {
		ks = append(ks, k)
	}
	sort.Slice(ks, func(i, j int) bool {
		if ks[i][0] != ks[j][0] {
			return ks[i][0] < ks[j][0]
		}
		return ks[i][1] < ks[j][1]
	})
	for _, k := range ks {
		doc.Kerning = append(doc.Kerning, kern{string(k[0]), string(k[1]), a.Kern[k]})
	}
	return json.MarshalIndent(doc, "", "  ")
}
