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
// The canvas grows to hold all ink (negative side bearings, slant overhang,
// wrap widths narrower than one glyph) so nothing is ever clipped.
func Text(f *ttf.Font, text string, st Style) (*img.Canvas, *layout.Result, error) {
	res, err := layout.Layout(f, text, st.Options)
	if err != nil {
		return nil, nil, err
	}
	pad := max(st.Padding, 0)
	pt := NewPainter(f, st)
	type placed struct {
		bm     *raster.Bitmap
		px, py int
	}
	var ps []placed
	minX, minY := 0, 0
	maxX, maxY := int(math.Ceil(math.Max(res.Width, st.Width))), int(math.Ceil(res.Height))+1
	for _, g := range res.Glyphs {
		ix := math.Floor(g.X)
		bm, err := pt.Glyph(g.GID, g.X-ix)
		if err != nil {
			return nil, nil, err
		}
		if bm.W == 0 {
			continue
		}
		p := placed{bm, int(ix), int(math.Round(g.Y))}
		minX, minY = min(minX, p.px+bm.X0), min(minY, p.py+bm.Y0)
		maxX, maxY = max(maxX, p.px+bm.X0+bm.W), max(maxY, p.py+bm.Y0+bm.H)
		ps = append(ps, p)
	}
	w, h := maxX-minX+2*pad, maxY-minY+2*pad
	if w <= 0 || h <= 0 || w > MaxPixels/h {
		return nil, nil, fmt.Errorf("canvas %dx%d is too large (limit %d pixels)", w, h, MaxPixels)
	}
	cv := img.NewCanvas(w, h, st.BG)
	for _, p := range ps {
		cv.Blend(p.bm, pad-minX+p.px, pad-minY+p.py, st.FG, st.Gamma)
	}
	return cv, res, nil
}
