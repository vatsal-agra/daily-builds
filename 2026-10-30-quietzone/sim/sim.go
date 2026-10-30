// Package sim degrades clean symbol images the way cameras and printers do:
// 3-D rotation with perspective, blur, sensor noise, uneven lighting, a logo
// punched into the centre and JPEG artefacts. It exists so every scanner
// accuracy claim can be measured against known ground truth.
package sim

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"math"
	"math/rand"
)

// Pose describes a camera-style transform of a flat symbol image.
type Pose struct {
	Roll   float64 // in-plane rotation, degrees
	TiltX  float64 // rotation about the horizontal axis, degrees
	TiltY  float64 // rotation about the vertical axis, degrees
	Scale  float64 // output size relative to the source (1 = same)
	Margin float64 // extra border around the projected symbol, as a fraction
	Mirror bool    // flip horizontally (a back-lit / reversed capture)
}

type pt struct{ x, y float64 }

// Warp renders src through the pose onto a bg-coloured canvas.
func Warp(src *image.Gray, p Pose, bg uint8) *image.Gray {
	w, h := float64(src.Bounds().Dx()), float64(src.Bounds().Dy())
	if p.Scale == 0 {
		p.Scale = 1
	}
	rad := math.Pi / 180
	cx, cy := w/2, h/2
	f := math.Max(w, h) * 2.2 // focal length in px: moderate perspective
	proj := func(x, y float64) pt {
		x, y = x-cx, y-cy
		// roll
		s, c := math.Sincos(p.Roll * rad)
		x, y = x*c-y*s, x*s+y*c
		// tilt about X then Y
		z := 0.0
		s, c = math.Sincos(p.TiltX * rad)
		y, z = y*c-z*s, y*s+z*c
		s, c = math.Sincos(p.TiltY * rad)
		x, z = x*c+z*s, -x*s+z*c
		k := f / (f + z)
		return pt{x * k * p.Scale, y * k * p.Scale}
	}
	corners := [4]pt{{0, 0}, {w, 0}, {w, h}, {0, h}}
	var q [4]pt
	minX, minY, maxX, maxY := math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	for i, c := range corners {
		q[i] = proj(c.x, c.y)
		minX, maxX = math.Min(minX, q[i].x), math.Max(maxX, q[i].x)
		minY, maxY = math.Min(minY, q[i].y), math.Max(maxY, q[i].y)
	}
	pad := math.Max(maxX-minX, maxY-minY) * p.Margin
	ow, oh := int(math.Ceil(maxX-minX+2*pad)), int(math.Ceil(maxY-minY+2*pad))
	for i := range q {
		q[i].x += -minX + pad
		q[i].y += -minY + pad
	}
	// Inverse homography from output quad back to the source rectangle.
	hinv := quadToRect(q, w, h)
	out := image.NewGray(image.Rect(0, 0, ow, oh))
	for y := 0; y < oh; y++ {
		for x := 0; x < ow; x++ {
			u, v, ok := hinv(float64(x)+0.5, float64(y)+0.5)
			if p.Mirror {
				u = w - u
			}
			if !ok || u < 0 || v < 0 || u >= w || v >= h {
				out.Pix[y*out.Stride+x] = bg
				continue
			}
			out.Pix[y*out.Stride+x] = bilinear(src, u-0.5, v-0.5)
		}
	}
	return out
}

func bilinear(g *image.Gray, x, y float64) uint8 {
	b := g.Bounds()
	x0, y0 := int(math.Floor(x)), int(math.Floor(y))
	fx, fy := x-float64(x0), y-float64(y0)
	at := func(i, j int) float64 {
		i = clamp(i, 0, b.Dx()-1)
		j = clamp(j, 0, b.Dy()-1)
		return float64(g.Pix[j*g.Stride+i])
	}
	v := at(x0, y0)*(1-fx)*(1-fy) + at(x0+1, y0)*fx*(1-fy) + at(x0, y0+1)*(1-fx)*fy + at(x0+1, y0+1)*fx*fy
	return uint8(v + 0.5)
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// quadToRect returns the map from quad (TL,TR,BR,BL) pixels back to [0,w]x[0,h].
func quadToRect(q [4]pt, w, h float64) func(x, y float64) (float64, float64, bool) {
	// Solve the projective map rect -> quad, then invert it.
	src := [4]pt{{0, 0}, {w, 0}, {w, h}, {0, h}}
	var a [8][9]float64
	for i := 0; i < 4; i++ {
		u, v, x, y := src[i].x, src[i].y, q[i].x, q[i].y
		a[2*i] = [9]float64{u, v, 1, 0, 0, 0, -u * x, -v * x, x}
		a[2*i+1] = [9]float64{0, 0, 0, u, v, 1, -u * y, -v * y, y}
	}
	for c := 0; c < 8; c++ {
		p := c
		for r := c + 1; r < 8; r++ {
			if math.Abs(a[r][c]) > math.Abs(a[p][c]) {
				p = r
			}
		}
		a[c], a[p] = a[p], a[c]
		for r := 0; r < 8; r++ {
			if r != c {
				f := a[r][c] / a[c][c]
				for k := c; k < 9; k++ {
					a[r][k] -= f * a[c][k]
				}
			}
		}
	}
	var hm [9]float64
	for i := 0; i < 8; i++ {
		hm[i] = a[i][8] / a[i][i]
	}
	hm[8] = 1
	// invert 3x3
	det := hm[0]*(hm[4]*hm[8]-hm[5]*hm[7]) - hm[1]*(hm[3]*hm[8]-hm[5]*hm[6]) + hm[2]*(hm[3]*hm[7]-hm[4]*hm[6])
	inv := [9]float64{
		(hm[4]*hm[8] - hm[5]*hm[7]) / det, (hm[2]*hm[7] - hm[1]*hm[8]) / det, (hm[1]*hm[5] - hm[2]*hm[4]) / det,
		(hm[5]*hm[6] - hm[3]*hm[8]) / det, (hm[0]*hm[8] - hm[2]*hm[6]) / det, (hm[2]*hm[3] - hm[0]*hm[5]) / det,
		(hm[3]*hm[7] - hm[4]*hm[6]) / det, (hm[1]*hm[6] - hm[0]*hm[7]) / det, (hm[0]*hm[4] - hm[1]*hm[3]) / det,
	}
	return func(x, y float64) (float64, float64, bool) {
		d := inv[6]*x + inv[7]*y + inv[8]
		if math.Abs(d) < 1e-12 {
			return 0, 0, false
		}
		return (inv[0]*x + inv[1]*y + inv[2]) / d, (inv[3]*x + inv[4]*y + inv[5]) / d, true
	}
}

// Blur applies a separable Gaussian of the given sigma (pixels).
func Blur(g *image.Gray, sigma float64) *image.Gray {
	if sigma <= 0 {
		return g
	}
	r := int(math.Ceil(sigma * 3))
	k := make([]float64, 2*r+1)
	var sum float64
	for i := range k {
		d := float64(i - r)
		k[i] = math.Exp(-d * d / (2 * sigma * sigma))
		sum += k[i]
	}
	for i := range k {
		k[i] /= sum
	}
	b := g.Bounds()
	w, h := b.Dx(), b.Dy()
	tmp := make([]float64, w*h)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			var s float64
			for i := -r; i <= r; i++ {
				s += k[i+r] * float64(g.Pix[y*g.Stride+clamp(x+i, 0, w-1)])
			}
			tmp[y*w+x] = s
		}
	}
	out := image.NewGray(b)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			var s float64
			for i := -r; i <= r; i++ {
				s += k[i+r] * tmp[clamp(y+i, 0, h-1)*w+x]
			}
			out.Pix[y*out.Stride+x] = uint8(s + 0.5)
		}
	}
	return out
}

// Noise adds Gaussian sensor noise (sigma in grey levels) and, with probability
// salt, impulse noise pixels.
func Noise(g *image.Gray, sigma, salt float64, rng *rand.Rand) *image.Gray {
	out := image.NewGray(g.Bounds())
	for i, v := range g.Pix {
		f := float64(v) + rng.NormFloat64()*sigma
		if salt > 0 && rng.Float64() < salt {
			if rng.Intn(2) == 0 {
				f = 0
			} else {
				f = 255
			}
		}
		out.Pix[i] = uint8(math.Max(0, math.Min(255, f+0.5)))
	}
	return out
}

// Lighting multiplies by a linear gradient (strength 0..1 dark side) at angle
// degrees plus a radial vignette, imitating uneven illumination.
func Lighting(g *image.Gray, strength, vignette, angle float64) *image.Gray {
	b := g.Bounds()
	w, h := float64(b.Dx()), float64(b.Dy())
	out := image.NewGray(b)
	s, c := math.Sincos(angle * math.Pi / 180)
	for y := 0; y < b.Dy(); y++ {
		for x := 0; x < b.Dx(); x++ {
			nx, ny := (float64(x)/w-0.5)*2, (float64(y)/h-0.5)*2
			t := (nx*c + ny*s + 1) / 2 // 0..1 across the image
			gain := 1 - strength*t
			gain *= 1 - vignette*(nx*nx+ny*ny)/2
			out.Pix[y*out.Stride+x] = uint8(math.Max(0, math.Min(255, float64(g.Pix[y*g.Stride+x])*gain+0.5)))
		}
	}
	return out
}

// Contrast squeezes the dynamic range to [lo,hi].
func Contrast(g *image.Gray, lo, hi uint8) *image.Gray {
	out := image.NewGray(g.Bounds())
	for i, v := range g.Pix {
		out.Pix[i] = lo + uint8(float64(v)/255*float64(hi-lo))
	}
	return out
}

// Logo paints a filled square covering `frac` of the symbol width at the centre
// of the rectangle `r` (the symbol's bounds inside the image).
func Logo(g *image.Gray, r image.Rectangle, frac float64, shade uint8) *image.Gray {
	out := image.NewGray(g.Bounds())
	copy(out.Pix, g.Pix)
	side := int(float64(r.Dx()) * frac)
	cx, cy := (r.Min.X+r.Max.X)/2, (r.Min.Y+r.Max.Y)/2
	for y := cy - side/2; y < cy+side/2; y++ {
		for x := cx - side/2; x < cx+side/2; x++ {
			if image.Pt(x, y).In(g.Bounds()) {
				out.Pix[y*out.Stride+x] = shade
			}
		}
	}
	return out
}

// JPEG re-encodes at the given quality (1..100) and decodes back to grey.
func JPEG(g *image.Gray, quality int) (*image.Gray, error) {
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, g, &jpeg.Options{Quality: quality}); err != nil {
		return nil, err
	}
	im, err := jpeg.Decode(&buf)
	if err != nil {
		return nil, err
	}
	out := image.NewGray(im.Bounds())
	for y := 0; y < im.Bounds().Dy(); y++ {
		for x := 0; x < im.Bounds().Dx(); x++ {
			out.SetGray(x, y, color.GrayModel.Convert(im.At(x, y)).(color.Gray))
		}
	}
	return out, nil
}

// Clutter fills the background with low-frequency texture and thin lines so the
// finder-pattern detector has distractors to reject.
func Clutter(g *image.Gray, rng *rand.Rand, lines int) *image.Gray {
	out := image.NewGray(g.Bounds())
	copy(out.Pix, g.Pix)
	b := g.Bounds()
	for i := 0; i < lines; i++ {
		x0, y0 := rng.Intn(b.Dx()), rng.Intn(b.Dy())
		x1, y1 := rng.Intn(b.Dx()), rng.Intn(b.Dy())
		shade := uint8(rng.Intn(120))
		n := int(math.Hypot(float64(x1-x0), float64(y1-y0)))
		for t := 0; t < n; t++ {
			x := x0 + (x1-x0)*t/n
			y := y0 + (y1-y0)*t/n
			// only draw on near-background pixels so the symbol is not touched
			if out.Pix[y*out.Stride+x] > 240 {
				out.Pix[y*out.Stride+x] = shade
			}
		}
	}
	return out
}
