package img

import (
	"math"

	"glyph/raster"
)

// RGB is an 8-bit sRGB colour.
type RGB struct{ R, G, B uint8 }

// Canvas is an opaque RGB surface.
type Canvas struct {
	W, H int
	Pix  []byte // RGB, row-major
}

var toLinear [256]float32
var fromLinear [4097]uint8

func init() {
	for i := range toLinear {
		c := float64(i) / 255
		if c <= 0.04045 {
			toLinear[i] = float32(c / 12.92)
		} else {
			toLinear[i] = float32(math.Pow((c+0.055)/1.055, 2.4))
		}
	}
	for i := range fromLinear {
		l := float64(i) / 4096
		var c float64
		if l <= 0.0031308 {
			c = l * 12.92
		} else {
			c = 1.055*math.Pow(l, 1/2.4) - 0.055
		}
		fromLinear[i] = uint8(math.Round(math.Min(1, math.Max(0, c)) * 255))
	}
}

// NewCanvas returns a w×h canvas filled with bg.
func NewCanvas(w, h int, bg RGB) *Canvas {
	c := &Canvas{W: w, H: h, Pix: make([]byte, w*h*3)}
	for i := 0; i < w*h; i++ {
		c.Pix[3*i], c.Pix[3*i+1], c.Pix[3*i+2] = bg.R, bg.G, bg.B
	}
	return c
}

// Blend composites a coverage bitmap in colour fg with its top-left at
// (ox+bm.X0, oy+bm.Y0). With gamma=true blending happens in linear light,
// which keeps dark-on-light and light-on-dark text equally sharp and even.
func (c *Canvas) Blend(bm *raster.Bitmap, ox, oy int, fg RGB, gamma bool) {
	for y := 0; y < bm.H; y++ {
		py := oy + bm.Y0 + y
		if py < 0 || py >= c.H {
			continue
		}
		for x := 0; x < bm.W; x++ {
			a := bm.Pix[y*bm.W+x]
			if a <= 0 {
				continue
			}
			px := ox + bm.X0 + x
			if px < 0 || px >= c.W {
				continue
			}
			i := 3 * (py*c.W + px)
			c.mix(i, 0, fg.R, a, gamma)
			c.mix(i, 1, fg.G, a, gamma)
			c.mix(i, 2, fg.B, a, gamma)
		}
	}
}

func (c *Canvas) mix(i, k int, fg uint8, a float32, gamma bool) {
	if a > 1 {
		a = 1
	}
	if !gamma {
		c.Pix[i+k] = uint8(float32(c.Pix[i+k])*(1-a) + float32(fg)*a + 0.5)
		return
	}
	l := toLinear[c.Pix[i+k]]*(1-a) + toLinear[fg]*a
	c.Pix[i+k] = fromLinear[int(l*4096+0.5)]
}

// MixChannel blends a single channel k (0=R,1=G,2=B) at pixel (px,py) with coverage a.
func (c *Canvas) MixChannel(px, py, k int, fg uint8, a float32, gamma bool) {
	if px < 0 || py < 0 || px >= c.W || py >= c.H || a <= 0 {
		return
	}
	c.mix(3*(py*c.W+px), k, fg, a, gamma)
}

// WritePNG encodes the canvas.
func (c *Canvas) PNG() ([]byte, error) {
	var b bytesBuf
	err := EncodePNG(&b, c.W, c.H, 3, c.Pix)
	return b.b, err
}

type bytesBuf struct{ b []byte }

func (w *bytesBuf) Write(p []byte) (int, error) { w.b = append(w.b, p...); return len(p), nil }

// GrayPNG encodes a coverage bitmap as an 8-bit grayscale PNG (ink = dark on white).
func GrayPNG(bm *raster.Bitmap) ([]byte, error) {
	pix := make([]byte, len(bm.Pix))
	for i, v := range bm.Pix {
		pix[i] = uint8(255 - math.Round(float64(min(max(v, 0), 1))*255))
	}
	var b bytesBuf
	err := EncodePNG(&b, bm.W, bm.H, 1, pix)
	return b.b, err
}
