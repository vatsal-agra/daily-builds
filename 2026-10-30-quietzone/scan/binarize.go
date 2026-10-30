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
// Common concrete types take fast paths; everything else goes through At().
func FromImage(img image.Image) *Gray {
	b := img.Bounds()
	g := &Gray{W: b.Dx(), H: b.Dy(), Pix: make([]uint8, b.Dx()*b.Dy())}
	switch im := img.(type) {
	case *image.Gray:
		for y := 0; y < g.H; y++ {
			copy(g.Pix[y*g.W:(y+1)*g.W], im.Pix[y*im.Stride:y*im.Stride+g.W])
		}
	case *image.NRGBA:
		for y := 0; y < g.H; y++ {
			row := im.Pix[y*im.Stride:]
			for x := 0; x < g.W; x++ {
				r, gg, bb, a := int(row[4*x]), int(row[4*x+1]), int(row[4*x+2]), int(row[4*x+3])
				l := (299*r + 587*gg + 114*bb) / 1000
				g.Pix[y*g.W+x] = uint8((l*a + 255*(255-a)) / 255)
			}
		}
	case *image.YCbCr:
		for y := 0; y < g.H; y++ {
			for x := 0; x < g.W; x++ {
				g.Pix[y*g.W+x] = im.Y[im.YOffset(b.Min.X+x, b.Min.Y+y)]
			}
		}
	default:
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
	Denoise  bool // 3x3 median filter before thresholding (impulse/sensor noise)
}

// Strategies is the ordered retry list used by Scan: cheap plain recipes first,
// then denoised ones, then everything again on the inverted image.
func Strategies() []Strategy {
	var out []Strategy
	for _, inv := range []bool{false, true} {
		out = append(out,
			Strategy{"adaptive/4", 4, inv, false},
			Strategy{"otsu", 0, inv, false},
			Strategy{"denoise+adaptive/4", 4, inv, true},
			Strategy{"adaptive/10", 10, inv, false},
			Strategy{"denoise+otsu", 0, inv, true},
			Strategy{"adaptive/24", 24, inv, false},
			Strategy{"denoise+adaptive/10", 10, inv, true})
	}
	return out
}

// Binarize applies a strategy.
func (g *Gray) Binarize(s Strategy) *Bin {
	src := g
	if s.Denoise {
		src = g.median3()
	}
	b := &Bin{W: g.W, H: g.H, Pix: make([]bool, len(g.Pix))}
	if s.Window == 0 {
		t := src.otsu()
		for i, v := range src.Pix {
			b.Pix[i] = int(v) < t
		}
	} else {
		src.bradley(b, max(15, max(g.W, g.H)/s.Window), 0.88)
	}
	if s.Inverted {
		for i := range b.Pix {
			b.Pix[i] = !b.Pix[i]
		}
	}
	return b
}

// median3 is a 3x3 median filter (edges replicated) using the classic
// 19-exchange sorting network for nine values.
func (g *Gray) median3() *Gray {
	out := &Gray{W: g.W, H: g.H, Pix: make([]uint8, len(g.Pix))}
	cswap := func(a, b *uint8) {
		if *a > *b {
			*a, *b = *b, *a
		}
	}
	for y := 0; y < g.H; y++ {
		r0 := g.Pix[min(max(y-1, 0), g.H-1)*g.W:]
		r1 := g.Pix[y*g.W:]
		r2 := g.Pix[min(y+1, g.H-1)*g.W:]
		for x := 0; x < g.W; x++ {
			xl, xr := max(x-1, 0), min(x+1, g.W-1)
			p0, p1, p2 := r0[xl], r0[x], r0[xr]
			p3, p4, p5 := r1[xl], r1[x], r1[xr]
			p6, p7, p8 := r2[xl], r2[x], r2[xr]
			cswap(&p1, &p2)
			cswap(&p4, &p5)
			cswap(&p7, &p8)
			cswap(&p0, &p1)
			cswap(&p3, &p4)
			cswap(&p6, &p7)
			cswap(&p1, &p2)
			cswap(&p4, &p5)
			cswap(&p7, &p8)
			cswap(&p0, &p3)
			cswap(&p5, &p8)
			cswap(&p4, &p7)
			cswap(&p3, &p6)
			cswap(&p1, &p4)
			cswap(&p2, &p5)
			cswap(&p4, &p7)
			cswap(&p4, &p2)
			cswap(&p6, &p4)
			cswap(&p4, &p2)
			out.Pix[y*g.W+x] = p4
		}
	}
	return out
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
// integral image in O(pixels). Windows with almost no variance carry no edge
// information and are decided against the global Otsu threshold instead.
func (g *Gray) bradley(out *Bin, win int, ratio float64) {
	w, h := g.W, g.H
	integ := make([]int64, (w+1)*(h+1))
	sq := make([]int64, (w+1)*(h+1))
	for y := 0; y < h; y++ {
		var row, rowSq int64
		for x := 0; x < w; x++ {
			v := int64(g.Pix[y*w+x])
			row += v
			rowSq += v * v
			integ[(y+1)*(w+1)+x+1] = integ[y*(w+1)+x+1] + row
			sq[(y+1)*(w+1)+x+1] = sq[y*(w+1)+x+1] + rowSq
		}
	}
	half := win / 2
	glob := g.otsu()
	for y := 0; y < h; y++ {
		y0, y1 := max(0, y-half), min(h, y+half+1)
		for x := 0; x < w; x++ {
			x0, x1 := max(0, x-half), min(w, x+half+1)
			cnt := float64((x1 - x0) * (y1 - y0))
			i11, i01, i10, i00 := (y1)*(w+1)+x1, y0*(w+1)+x1, y1*(w+1)+x0, y0*(w+1)+x0
			s := float64(integ[i11] - integ[i01] - integ[i10] + integ[i00])
			s2 := float64(sq[i11] - sq[i01] - sq[i10] + sq[i00])
			mean := s / cnt
			v := float64(g.Pix[y*w+x])
			if variance := s2/cnt - mean*mean; variance < 12*12 {
				out.Pix[y*w+x] = int(v) < glob
			} else {
				out.Pix[y*w+x] = v < mean*ratio
			}
		}
	}
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
