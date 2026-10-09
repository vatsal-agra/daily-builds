// Package render ties the font engine together: layout → rasterize → composite.
package render

import (
	"fmt"
	"math"

	"glyph/img"
	"glyph/layout"
	"glyph/raster"
	"glyph/ttf"
)

// MaxPixels caps canvas area so absurd sizes fail cleanly instead of exhausting memory.
const MaxPixels = 64 << 20

// Style describes how to paint a laid-out block.
type Style struct {
	layout.Options
	FG, BG  img.RGB
	Padding int
	Gamma   bool    // blend in linear light
	Slant   float64 // synthetic oblique shear, e.g. 0.2
	Samples int     // sub-scanlines per pixel (0 = default)
}

// DefaultStyle is black text on white at the given size.
func DefaultStyle(size float64) Style {
	return Style{Options: layout.Options{Size: size}, BG: img.RGB{R: 255, G: 255, B: 255}, Padding: 8, Gamma: true}
}

type cacheKey struct {
	gid uint16
	q   int
}

// Painter caches rasterized glyphs by (glyph, quarter-pixel subposition).
type Painter struct {
	f     *ttf.Font
	scale float64
	st    Style
	cache map[cacheKey]*raster.Bitmap
}

func NewPainter(f *ttf.Font, st Style) *Painter {
	return &Painter{f: f, scale: st.Size / float64(f.UnitsPerEm), st: st, cache: map[cacheKey]*raster.Bitmap{}}
}

// Glyph returns the coverage bitmap of gid with the pen at fractional offset (fx, 0),
// relative to an integer pen position; bm.X0/Y0 are offsets from that pen position.
func (p *Painter) Glyph(gid uint16, fx float64) (*raster.Bitmap, error) {
	q := int(math.Round(fx * 4))
	k := cacheKey{gid, q}
	if bm, ok := p.cache[k]; ok {
		return bm, nil
	}
	o, err := p.f.Glyph(gid)
	if err != nil {
		return nil, err
	}
	m := raster.Scale(p.scale, float64(q)/4, 0, p.st.Slant)
	bm := raster.Render(raster.Flatten(o, m, 0), p.st.Samples)
	p.cache[k] = bm
	return bm, nil
}

// Text lays out and paints text, returning the canvas and the layout result.
func Text(f *ttf.Font, text string, st Style) (*img.Canvas, *layout.Result, error) {
	res, err := layout.Layout(f, text, st.Options)
	if err != nil {
		return nil, nil, err
	}
	pad := st.Padding
	if pad < 0 {
		pad = 0
	}
	w := int(math.Ceil(res.Width)) + 2*pad
	if st.Width > 0 {
		w = int(math.Ceil(st.Width)) + 2*pad
	}
	extraR := int(math.Ceil(st.Slant*st.Size)) + 2 // slanted ink may overhang
	w += extraR
	h := int(math.Ceil(res.Height)) + 2*pad + 2
	if w <= 0 || h <= 0 || w*h > MaxPixels {
		return nil, nil, fmt.Errorf("canvas %dx%d is too large (limit %d pixels)", w, h, MaxPixels)
	}
	cv := img.NewCanvas(w, h, st.BG)
	pt := NewPainter(f, st)
	for _, g := range res.Glyphs {
		ix := math.Floor(g.X)
		bm, err := pt.Glyph(g.GID, g.X-ix)
		if err != nil {
			return nil, nil, err
		}
		cv.Blend(bm, pad+int(ix), pad+int(math.Round(g.Y)), st.FG, st.Gamma)
	}
	return cv, res, nil
}
