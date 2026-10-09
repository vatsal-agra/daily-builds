package raster

import "math"

// LCDBitmap holds per-channel (R,G,B stripe order) coverage. W/H/X0/Y0 are in whole pixels.
type LCDBitmap struct {
	W, H, X0, Y0 int
	Pix          []float32 // 3 floats per pixel: R, G, B coverage
}

// lcdFIR is FreeType's default 5-tap filter (sums to 1) that suppresses colour fringes.
var lcdFIR = [5]float64{8.0 / 256, 77.0 / 256, 86.0 / 256, 77.0 / 256, 8.0 / 256}

// RenderLCD rasterizes at 3× horizontal resolution (one sample per sub-pixel
// stripe) and low-pass filters across sub-pixels, giving per-channel coverage.
func RenderLCD(path Path, samples int) *LCDBitmap {
	x0, y0, x1, y1, ok := path.Bounds()
	if !ok {
		return &LCDBitmap{}
	}
	// pixel bounds, with a 1-pixel margin so the FIR tails are not cut off
	px0 := clampInt(math.Floor(x0)-1, -MaxDim/2, MaxDim/2)
	px1 := clampInt(math.Ceil(x1)+1, float64(px0+1), float64(px0+MaxDim))
	py0 := clampInt(math.Floor(y0)-1, -MaxDim/2, MaxDim/2)
	py1 := clampInt(math.Ceil(y1)+1, float64(py0+1), float64(py0+MaxDim))
	w, h := px1-px0, py1-py0
	shifted := make(Path, len(path))
	for i, poly := range path {
		sp := make([]Pt, len(poly))
		for j, q := range poly {
			sp[j] = Pt{(q.X - float64(px0)) * 3, q.Y - float64(py0)}
		}
		shifted[i] = sp
	}
	hi := Fill(shifted, w*3, h, samples)
	out := &LCDBitmap{W: w, H: h, X0: px0, Y0: py0, Pix: make([]float32, w*h*3)}
	for y := 0; y < h; y++ {
		row := hi.Pix[y*w*3 : (y+1)*w*3]
		for s := 0; s < w*3; s++ {
			var v float64
			for k, c := range lcdFIR {
				if j := s + k - 2; j >= 0 && j < len(row) {
					v += c * float64(row[j])
				}
			}
			out.Pix[(y*w*3)+s] = float32(math.Min(1, v))
		}
	}
	return out
}

// Sum returns the total luminance-weighted coverage (≈ area in px²).
func (b *LCDBitmap) Sum() float64 {
	s := 0.0
	for _, v := range b.Pix {
		s += float64(v)
	}
	return s / 3
}
