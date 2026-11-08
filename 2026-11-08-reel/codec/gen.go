package codec

import (
	"fmt"
	"math"
	"sort"
)

// Procedural test-sequence generator. Everything is a pure function of
// (preset, seed, frame, x, y) so sequences are exactly reproducible and carry
// genuine sub-pixel motion, occlusion, texture, noise and scene cuts.

// Presets lists the available generator presets.
func Presets() []string {
	p := []string{"pan", "objects", "mixed", "cut", "noise", "zoom"}
	sort.Strings(p)
	return p
}

type rgb struct{ r, g, b float64 }

func hash2(x, y int, seed uint32) uint32 {
	h := uint32(x)*0x9E3779B1 ^ uint32(y)*0x85EBCA77 ^ seed*0xC2B2AE3D
	h ^= h >> 15
	h *= 0x2C1B3C6D
	h ^= h >> 12
	h *= 0x297A2D39
	h ^= h >> 15
	return h
}

func rnd01(x, y int, seed uint32) float64 {
	return float64(hash2(x, y, seed)&0xFFFFFF) / float64(0x1000000)
}

func smooth(t float64) float64 { return t * t * t * (t*(t*6-15) + 10) }

func vnoise(x, y float64, seed uint32) float64 {
	x0, y0 := math.Floor(x), math.Floor(y)
	fx, fy := smooth(x-x0), smooth(y-y0)
	ix, iy := int(x0), int(y0)
	a, b := rnd01(ix, iy, seed), rnd01(ix+1, iy, seed)
	c, d := rnd01(ix, iy+1, seed), rnd01(ix+1, iy+1, seed)
	return (a*(1-fx)+b*fx)*(1-fy) + (c*(1-fx)+d*fx)*fy
}

func fbm(x, y float64, seed uint32, oct int) float64 {
	s, amp, f, norm := 0.0, 1.0, 1.0, 0.0
	for i := 0; i < oct; i++ {
		s += amp * vnoise(x*f, y*f, seed+uint32(i)*77)
		norm += amp
		amp *= 0.55
		f *= 2.03
	}
	return s / norm
}

func texture(x, y float64, seed uint32) rgb {
	a := fbm(x/38, y/38, seed, 5)
	b := fbm(x/17+9, y/17-4, seed+1, 4)
	c := fbm(x/60-3, y/60+8, seed+2, 3)
	return rgb{0.25 + 0.6*a + 0.15*b, 0.2 + 0.55*c + 0.25*b, 0.3 + 0.5*b + 0.3*a*c}
}

type shape struct {
	kind         int // 0 ellipse, 1 rotated rect
	cx, cy       float64
	vx, vy       float64
	rx, ry       float64
	rot, rotV    float64
	col1, col2   rgb
	stripePeriod float64
}

func makeShapes(w, h int, seed uint32, n int) []shape {
	var out []shape
	for i := 0; i < n; i++ {
		r := func(k uint32) float64 { return rnd01(i, int(k), seed+500) }
		out = append(out, shape{
			kind: i % 2,
			cx:   r(1) * float64(w), cy: r(2) * float64(h),
			vx: (r(3) - 0.5) * 5.0, vy: (r(4) - 0.5) * 4.0,
			rx: float64(w) * (0.06 + 0.07*r(5)), ry: float64(h) * (0.06 + 0.08*r(6)),
			rot: r(7) * 6.28, rotV: (r(8) - 0.5) * 0.12,
			col1:         rgb{0.3 + 0.7*r(9), 0.2 + 0.8*r(10), 0.2 + 0.8*r(11)},
			col2:         rgb{0.1 + 0.5*r(12), 0.1 + 0.5*r(13), 0.1 + 0.5*r(14)},
			stripePeriod: 4 + 6*r(15),
		})
	}
	return out
}

// bounce folds a moving coordinate back into [lo,hi].
func bounce(p, lo, hi float64) float64 {
	span := hi - lo
	q := math.Mod(p-lo, 2*span)
	if q < 0 {
		q += 2 * span
	}
	if q > span {
		q = 2*span - q
	}
	return lo + q
}

func over(base, top rgb, a float64) rgb {
	return rgb{base.r*(1-a) + top.r*a, base.g*(1-a) + top.g*a, base.b*(1-a) + top.b*a}
}

// GenParams configures Generate.
type GenParams struct {
	Preset         string
	W, H, N        int
	Seed           uint32
	FPSNum, FPSDen int
}

// Generate renders a deterministic test video.
func Generate(g GenParams) (*Video, error) {
	valid := false
	for _, p := range Presets() {
		if p == g.Preset {
			valid = true
		}
	}
	if !valid {
		return nil, fmt.Errorf("unknown preset %q (have %v)", g.Preset, Presets())
	}
	if g.W < 16 || g.H < 16 || g.W > maxDim || g.H > maxDim {
		return nil, fmt.Errorf("size %dx%d out of range (16..%d)", g.W, g.H, maxDim)
	}
	if g.N < 1 || g.N > 100000 {
		return nil, fmt.Errorf("frame count %d out of range", g.N)
	}
	if g.FPSNum <= 0 || g.FPSDen <= 0 {
		g.FPSNum, g.FPSDen = 30, 1
	}
	v := &Video{Width: g.W, Height: g.H, FPSNum: g.FPSNum, FPSDen: g.FPSDen}
	shapesA := makeShapes(g.W, g.H, g.Seed, 5)
	shapesB := makeShapes(g.W, g.H, g.Seed+9, 4)
	cw, ch := (g.W+1)/2, (g.H+1)/2
	for t := 0; t < g.N; t++ {
		full := make([]rgb, g.W*g.H)
		for y := 0; y < g.H; y++ {
			for x := 0; x < g.W; x++ {
				full[y*g.W+x] = g.pixel(t, float64(x), float64(y), shapesA, shapesB)
			}
		}
		buf := make([]byte, g.W*g.H+2*cw*ch)
		for y := 0; y < g.H; y++ {
			for x := 0; x < g.W; x++ {
				c := full[y*g.W+x]
				buf[y*g.W+x] = clip255(int(math.Round(16 + 65.481*c.r + 128.553*c.g + 24.966*c.b)))
			}
		}
		for y := 0; y < ch; y++ {
			for x := 0; x < cw; x++ {
				var r, gg, b, n float64
				for dy := 0; dy < 2; dy++ {
					for dx := 0; dx < 2; dx++ {
						xx, yy := imin(2*x+dx, g.W-1), imin(2*y+dy, g.H-1)
						c := full[yy*g.W+xx]
						r += c.r
						gg += c.g
						b += c.b
						n++
					}
				}
				r, gg, b = r/n, gg/n, b/n
				buf[g.W*g.H+y*cw+x] = clip255(int(math.Round(128 - 37.797*r - 74.203*gg + 112*b)))
				buf[g.W*g.H+cw*ch+y*cw+x] = clip255(int(math.Round(128 + 112*r - 93.786*gg - 18.214*b)))
			}
		}
		v.Frames = append(v.Frames, FromPlanar(g.W, g.H, buf))
	}
	return v, nil
}

func (g GenParams) pixel(t int, x, y float64, sa, sb []shape) rgb {
	ft := float64(t)
	W, H := float64(g.W), float64(g.H)
	seed := g.Seed
	var c rgb
	noiseAmp := 0.004
	shapes := sa
	switch g.Preset {
	case "pan":
		c = texture(x+1.7*ft, y+0.6*ft, seed)
		shapes = nil
	case "zoom":
		s := 1 + 0.004*ft
		c = texture((x-W/2)/s+W/2+0.5*ft, (y-H/2)/s+H/2, seed)
		shapes = nil
	case "objects":
		k := y / H
		c = rgb{0.15 + 0.2*k, 0.2 + 0.25*k, 0.35 + 0.3*(1-k)}
	case "mixed", "cut":
		tt, sd := ft, seed
		if g.Preset == "cut" && t >= g.N/2 {
			tt, sd, shapes = ft-float64(g.N/2), seed+31, sb
			c = texture(x-2.4*tt, y+1.1*tt, sd)
		} else {
			c = texture(x+0.8*tt, y+0.3*tt, sd)
		}
		// slow global fade for the "mixed" preset
		if g.Preset == "mixed" {
			f := 0.85 + 0.15*math.Sin(ft/17)
			c = rgb{c.r * f, c.g * f, c.b * f}
		}
	case "noise":
		c = texture(x+3.1*ft, y-2.2*ft, seed)
		noiseAmp = 0.035
		shapes = nil
	}
	for i := range shapes {
		s := shapes[i]
		cx := bounce(s.cx+s.vx*ft, s.rx, W-s.rx)
		cy := bounce(s.cy+s.vy*ft, s.ry, H-s.ry)
		dx, dy := x-cx, y-cy
		var d float64 // signed distance-ish (negative inside)
		var u float64 // texture coordinate
		if s.kind == 0 {
			d = (math.Hypot(dx/s.rx, dy/s.ry) - 1) * math.Min(s.rx, s.ry)
			u = dx + dy
		} else {
			a := s.rot + s.rotV*ft
			ca, sa := math.Cos(a), math.Sin(a)
			lx, ly := dx*ca+dy*sa, -dx*sa+dy*ca
			d = math.Max(math.Abs(lx)-s.rx, math.Abs(ly)-s.ry)
			u = lx
		}
		cov := clampf(0.5-d, 0, 1)
		if cov > 0 {
			st := 0.5 + 0.5*math.Sin(u*2*math.Pi/s.stripePeriod)
			col := over(s.col1, s.col2, st)
			c = over(c, col, cov)
		}
	}
	if g.Preset == "mixed" || g.Preset == "cut" {
		// static HUD strip: checker blocks that must be coded once and then skipped
		if y > H-14 && x < W*0.45 {
			bx, by := int(x/7), int((y-(H-14))/7)
			if (bx+by)&1 == 0 {
				c = rgb{0.92, 0.92, 0.92}
			} else {
				c = rgb{0.1, 0.1, 0.12}
			}
		}
	}
	// zero-mean noise from the hash (sum of 3 uniforms ≈ gaussian)
	n := rnd01(int(x), int(y), seed+uint32(t)*7919+1) + rnd01(int(x), int(y), seed+uint32(t)*7919+2) + rnd01(int(x), int(y), seed+uint32(t)*7919+3) - 1.5
	c.r += n * noiseAmp * 3
	c.g += n * noiseAmp * 3
	c.b += n * noiseAmp * 3
	return rgb{clampf(c.r, 0, 1), clampf(c.g, 0, 1), clampf(c.b, 0, 1)}
}

func clampf(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
