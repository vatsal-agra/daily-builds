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
	LCD     bool    // sub-pixel (RGB stripe) rendering
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
	lcd   map[cacheKey]*raster.LCDBitmap
}

func NewPainter(f *ttf.Font, st Style) *Painter {
	return &Painter{f: f, scale: st.Size / float64(f.UnitsPerEm), st: st, cache: map[cacheKey]*raster.Bitmap{}, lcd: map[cacheKey]*raster.LCDBitmap{}}
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

// GlyphLCD is Glyph with per-channel sub-pixel coverage.
func (p *Painter) GlyphLCD(gid uint16, fx float64) (*raster.LCDBitmap, error) {
	q := int(math.Round(fx * 4))
	k := cacheKey{gid, q}
	if bm, ok := p.lcd[k]; ok {
		return bm, nil
	}
	o, err := p.f.Glyph(gid)
	if err != nil {
		return nil, err
	}
	m := raster.Scale(p.scale, float64(q)/4, 0, p.st.Slant)
	bm := raster.RenderLCD(raster.Flatten(o, m, 0), p.st.Samples)
	p.lcd[k] = bm
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
		lcd    *raster.LCDBitmap
		px, py int
	}
	var ps []placed
	minX, minY := 0, 0
	maxX, maxY := int(math.Ceil(math.Max(res.Width, st.Width))), int(math.Ceil(res.Height))+1
	for _, g := range res.Glyphs {
		ix := math.Floor(g.X)
		p := placed{px: int(ix), py: int(math.Round(g.Y))}
		var bx, by, bw, bh int
		if st.LCD {
			if p.lcd, err = pt.GlyphLCD(g.GID, g.X-ix); err != nil {
				return nil, nil, err
			}
			bx, by, bw, bh = p.lcd.X0, p.lcd.Y0, p.lcd.W, p.lcd.H
		} else {
			if p.bm, err = pt.Glyph(g.GID, g.X-ix); err != nil {
				return nil, nil, err
			}
			bx, by, bw, bh = p.bm.X0, p.bm.Y0, p.bm.W, p.bm.H
		}
		if bw == 0 {
			continue
		}
		minX, minY = min(minX, p.px+bx), min(minY, p.py+by)
		maxX, maxY = max(maxX, p.px+bx+bw), max(maxY, p.py+by+bh)
		ps = append(ps, p)
	}
	w, h := maxX-minX+2*pad, maxY-minY+2*pad
	if w <= 0 || h <= 0 || w > MaxPixels/h {
		return nil, nil, fmt.Errorf("canvas %dx%d is too large (limit %d pixels)", w, h, MaxPixels)
	}
	cv := img.NewCanvas(w, h, st.BG)
	for _, p := range ps {
		if p.lcd != nil {
			cv.BlendLCD(p.lcd, pad-minX+p.px, pad-minY+p.py, st.FG, st.Gamma)
		} else {
			cv.Blend(p.bm, pad-minX+p.px, pad-minY+p.py, st.FG, st.Gamma)
		}
	}
	return cv, res, nil
}
