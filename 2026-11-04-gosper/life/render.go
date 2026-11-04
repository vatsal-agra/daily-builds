package life

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"math"
)

// Theme holds the colours used by RenderImage.
type Theme struct{ BG, FG, Grid color.RGBA }

var (
	DarkTheme  = Theme{BG: color.RGBA{13, 17, 23, 255}, FG: color.RGBA{126, 231, 135, 255}, Grid: color.RGBA{22, 29, 38, 255}}
	LightTheme = Theme{BG: color.RGBA{250, 250, 247, 255}, FG: color.RGBA{16, 94, 54, 255}, Grid: color.RGBA{232, 232, 226, 255}}
)

func mix(a, b color.RGBA, t float64) color.RGBA {
	t = math.Max(0, math.Min(1, t))
	f := func(x, y uint8) uint8 { return uint8(math.Round(float64(x)*(1-t) + float64(y)*t)) }
	return color.RGBA{f(a.R, b.R), f(a.G, b.G), f(a.B, b.B), 255}
}

// View is a square-pixel window onto the plane: top-left cell (X0,Y0) and the
// number of cells per pixel (Scale; <1 means zoomed in).
type View struct {
	X0, Y0 float64
	Scale  float64
}

// FitView centres the pattern's bounding box (plus margin) in a w x h image.
func FitView(s *Sim, w, h int) View {
	x0, y0, x1, y1, ok := s.BBox()
	if !ok {
		return View{-float64(w) / 2, -float64(h) / 2, 1}
	}
	bw, bh := float64(x1-x0+1), float64(y1-y0+1)
	scale := math.Max(bw/float64(w), bh/float64(h)) * 1.08
	if scale < 1 { // zoom in by whole pixels per cell so cells stay crisp
		scale = 1 / math.Floor(1/scale)
	}
	cx, cy := float64(x0)+bw/2, float64(y0)+bh/2
	return View{cx - scale*float64(w)/2, cy - scale*float64(h)/2, scale}
}

// RenderImage draws the universe. Zoomed in it draws crisp cells; zoomed out it
// accumulates node populations so billion-cell patterns render in milliseconds
// as density shading.
func RenderImage(s *Sim, v View, w, h int, th Theme) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for i := 0; i < len(img.Pix); i += 4 {
		img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = th.BG.R, th.BG.G, th.BG.B, 255
	}
	if s.Root.pop == 0 {
		return img
	}
	o := s.origin()
	if v.Scale <= 1 {
		cell := 1 / v.Scale
		gap := 0
		if cell >= 6 {
			gap = 1
		}
		px := int(math.Round(cell))
		var walk func(n *Node, x, y int64)
		walk = func(n *Node, x, y int64) {
			if n.pop == 0 {
				return
			}
			sz := float64(int64(1) << uint(n.level))
			if (float64(x)+sz-v.X0)/v.Scale < 0 || (float64(y)+sz-v.Y0)/v.Scale < 0 ||
				(float64(x)-v.X0)/v.Scale > float64(w) || (float64(y)-v.Y0)/v.Scale > float64(h) {
				return
			}
			if n.level == 0 {
				sx := int(math.Round((float64(x) - v.X0) / v.Scale))
				sy := int(math.Round((float64(y) - v.Y0) / v.Scale))
				for dy := 0; dy < px-gap; dy++ {
					for dx := 0; dx < px-gap; dx++ {
						if X, Y := sx+dx, sy+dy; X >= 0 && Y >= 0 && X < w && Y < h {
							img.SetRGBA(X, Y, th.FG)
						}
					}
				}
				return
			}
			hh := int64(1) << uint(n.level-1)
			walk(n.nw, x, y)
			walk(n.ne, x+hh, y)
			walk(n.sw, x, y+hh)
			walk(n.se, x+hh, y+hh)
		}
		walk(s.Root, o, o)
		return img
	}
	acc := make([]float64, w*h)
	var walk func(n *Node, x, y int64)
	walk = func(n *Node, x, y int64) {
		if n.pop == 0 {
			return
		}
		sz := float64(int64(1) << uint(n.level))
		px0, py0 := (float64(x)-v.X0)/v.Scale, (float64(y)-v.Y0)/v.Scale
		pw := sz / v.Scale
		if px0+pw < 0 || py0+pw < 0 || px0 > float64(w) || py0 > float64(h) {
			return
		}
		if pw <= 1 || n.level == 0 {
			cx, cy := int(math.Floor(px0+pw/2)), int(math.Floor(py0+pw/2))
			if cx >= 0 && cy >= 0 && cx < w && cy < h {
				acc[cy*w+cx] += float64(n.pop)
			}
			return
		}
		hh := int64(1) << uint(n.level-1)
		walk(n.nw, x, y)
		walk(n.ne, x+hh, y)
		walk(n.sw, x, y+hh)
		walk(n.se, x+hh, y+hh)
	}
	walk(s.Root, o, o)
	area := v.Scale * v.Scale
	for i, a := range acc {
		if a > 0 {
			d := a / area
			img.SetRGBA(i%w, i/w, mix(th.BG, th.FG, 0.25+0.75*(1-math.Exp(-5*d))))
		}
	}
	return img
}

// EncodePNG encodes the image.
func EncodePNG(img image.Image) ([]byte, error) {
	var b bytes.Buffer
	enc := png.Encoder{CompressionLevel: png.BestCompression}
	if err := enc.Encode(&b, img); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}
