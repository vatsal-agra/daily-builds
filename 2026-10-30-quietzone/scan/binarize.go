package scan

import (
	"image"
	"image/color"
)

// Gray is an 8-bit luminance raster.
type Gray struct {
	W, H int
	Pix  []uint8
}

// FromImage converts any image.Image to luminance (alpha composited on white).
func FromImage(img image.Image) *Gray {
	b := img.Bounds()
	g := &Gray{W: b.Dx(), H: b.Dy(), Pix: make([]uint8, b.Dx()*b.Dy())}
	for y := 0; y < g.H; y++ {
		for x := 0; x < g.W; x++ {
			r, gg, bb, a := img.At(b.Min.X+x, b.Min.Y+y).RGBA()
			// premultiplied -> composite over white
			r += 0xFFFF - a
			gg += 0xFFFF - a
			bb += 0xFFFF - a
			l := (299*r + 587*gg + 114*bb) / 1000
			g.Pix[y*g.W+x] = uint8(l >> 8)
		}
	}
	return g
}

// Bin is a binary raster; true = dark.
type Bin struct {
	W, H int
	Pix  []bool
}

// At returns the pixel, treating outside as light.
func (b *Bin) At(x, y int) bool {
	if x < 0 || y < 0 || x >= b.W || y >= b.H {
		return false
	}
	return b.Pix[y*b.W+x]
}

// Strategy names a binarisation recipe.
type Strategy struct {
	Name     string
	Window   int // adaptive window as a fraction denominator of max(W,H); 0 = global Otsu
	Inverted bool
}

// Strategies is the ordered retry list used by Scan.
func Strategies() []Strategy {
	var out []Strategy
	for _, inv := range []bool{false, true} {
		out = append(out,
			Strategy{"adaptive/4", 4, inv}, Strategy{"otsu", 0, inv},
			Strategy{"adaptive/10", 10, inv}, Strategy{"adaptive/24", 24, inv})
	}
	return out
}

// Binarize applies a strategy.
func (g *Gray) Binarize(s Strategy) *Bin {
	b := &Bin{W: g.W, H: g.H, Pix: make([]bool, len(g.Pix))}
	if s.Window == 0 {
		t := g.otsu()
		for i, v := range g.Pix {
			b.Pix[i] = int(v) < t
		}
	} else {
		g.bradley(b, max(15, max(g.W, g.H)/s.Window), 0.88)
	}
	if s.Inverted {
		for i := range b.Pix {
			b.Pix[i] = !b.Pix[i]
		}
	}
	return b
}

func (g *Gray) otsu() int {
	var hist [256]int
	for _, v := range g.Pix {
		hist[v]++
	}
	total := len(g.Pix)
	var sum float64
	for i, c := range hist {
		sum += float64(i * c)
	}
	var wB int
	var sumB, best float64
	thr := 128
	for t := 0; t < 256; t++ {
		wB += hist[t]
		if wB == 0 {
			continue
		}
		wF := total - wB
		if wF == 0 {
			break
		}
		sumB += float64(t * hist[t])
		mB, mF := sumB/float64(wB), (sum-sumB)/float64(wF)
		v := float64(wB) * float64(wF) * (mB - mF) * (mB - mF)
		if v > best {
			best, thr = v, t+1
		}
	}
	return thr
}

// bradley is the Bradley-Roth adaptive threshold: a pixel is dark when it is
// more than (1-ratio) darker than the mean of its window, computed with an
// integral image in O(pixels). A flat window falls back to a global compare.
func (g *Gray) bradley(out *Bin, win int, ratio float64) {
	w, h := g.W, g.H
	integ := make([]int64, (w+1)*(h+1))
	for y := 0; y < h; y++ {
		var row int64
		for x := 0; x < w; x++ {
			row += int64(g.Pix[y*w+x])
			integ[(y+1)*(w+1)+x+1] = integ[y*(w+1)+x+1] + row
		}
	}
	half := win / 2
	glob := g.otsu()
	for y := 0; y < h; y++ {
		y0, y1 := max(0, y-half), min(h, y+half+1)
		for x := 0; x < w; x++ {
			x0, x1 := max(0, x-half), min(w, x+half+1)
			cnt := int64((x1 - x0) * (y1 - y0))
			s := integ[y1*(w+1)+x1] - integ[y0*(w+1)+x1] - integ[y1*(w+1)+x0] + integ[y0*(w+1)+x0]
			mean := float64(s) / float64(cnt)
			v := float64(g.Pix[y*w+x])
			// Contrast guard: nearly flat windows carry no edge information,
			// decide them against the global threshold instead.
			if lo, hi := windowRange(g, x0, y0, x1, y1, 4); hi-lo < 24 {
				out.Pix[y*w+x] = int(v) < glob
			} else {
				out.Pix[y*w+x] = v < mean*ratio
			}
		}
	}
}

// windowRange estimates min/max in a window by sparse sampling.
func windowRange(g *Gray, x0, y0, x1, y1, n int) (lo, hi uint8) {
	lo, hi = 255, 0
	for j := 0; j <= n; j++ {
		for i := 0; i <= n; i++ {
			x := x0 + (x1-1-x0)*i/n
			y := y0 + (y1-1-y0)*j/n
			v := g.Pix[y*g.W+x]
			if v < lo {
				lo = v
			}
			if v > hi {
				hi = v
			}
		}
	}
	return
}

// ToImage renders the binary raster (for debugging and reports).
func (b *Bin) ToImage() *image.Gray {
	img := image.NewGray(image.Rect(0, 0, b.W, b.H))
	for i, v := range b.Pix {
		if v {
			img.Pix[i] = 0
		} else {
			img.Pix[i] = 255
		}
	}
	_ = color.Gray{}
	return img
}
