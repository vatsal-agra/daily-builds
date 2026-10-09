package raster

import "math"

// SDF is a signed distance field sampled at pixel centres: Dist is in pixels,
// positive inside the shape, negative outside.
type SDF struct {
	W, H   int
	X0, Y0 int // pixel offset of Dist[0] relative to the glyph origin
	Dist   []float32
}

// SignedDistance computes the exact distance from each pixel centre to the
// polyline outline (brute force over segments, pruned by the spread radius) and
// the sign from the non-zero winding rule. The field covers the path bounds
// grown by `margin` pixels.
func SignedDistance(p Path, margin int) *SDF {
	x0, y0, x1, y1, ok := p.Bounds()
	if !ok {
		return &SDF{}
	}
	ix0, iy0 := clampInt(math.Floor(x0)-float64(margin), -MaxDim/2, MaxDim/2), clampInt(math.Floor(y0)-float64(margin), -MaxDim/2, MaxDim/2)
	ix1, iy1 := clampInt(math.Ceil(x1)+float64(margin), float64(ix0+1), float64(ix0+MaxDim)), clampInt(math.Ceil(y1)+float64(margin), float64(iy0+1), float64(iy0+MaxDim))
	w, h := ix1-ix0, iy1-iy0
	type seg struct{ ax, ay, bx, by float64 }
	var segs []seg
	for _, poly := range p {
		for i := range poly {
			a, b := poly[i], poly[(i+1)%len(poly)]
			if a != b {
				segs = append(segs, seg{a.X, a.Y, b.X, b.Y})
			}
		}
	}
	out := &SDF{W: w, H: h, X0: ix0, Y0: iy0, Dist: make([]float32, w*h)}
	cut := float64(margin) + 1 // distances beyond this are clamped anyway
	for py := 0; py < h; py++ {
		y := float64(iy0+py) + 0.5
		for px := 0; px < w; px++ {
			x := float64(ix0+px) + 0.5
			best := math.Inf(1)
			wind := 0
			for _, s := range segs {
				// winding by horizontal ray to +x
				if (s.ay <= y) != (s.by <= y) {
					t := (y - s.ay) / (s.by - s.ay)
					if s.ax+t*(s.bx-s.ax) > x {
						if s.by > s.ay {
							wind++
						} else {
							wind--
						}
					}
				}
				if math.Min(s.ay, s.by)-y > cut || y-math.Max(s.ay, s.by) > cut ||
					math.Min(s.ax, s.bx)-x > cut || x-math.Max(s.ax, s.bx) > cut {
					continue
				}
				dx, dy := s.bx-s.ax, s.by-s.ay
				t := ((x-s.ax)*dx + (y-s.ay)*dy) / (dx*dx + dy*dy)
				t = math.Max(0, math.Min(1, t))
				if d := math.Hypot(x-(s.ax+t*dx), y-(s.ay+t*dy)); d < best {
					best = d
				}
			}
			if math.IsInf(best, 1) {
				best = cut
			}
			if wind == 0 {
				best = -best
			}
			out.Dist[py*w+px] = float32(best)
		}
	}
	return out
}
