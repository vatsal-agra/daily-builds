package codec

import (
	"fmt"
	"math"
)

// noise is a tiny deterministic PRNG so decoded noise filling is reproducible.
type noise uint32

func (n *noise) next() float64 {
	*n = *n*1664525 + 1013904223
	return float64(*n>>8)/float64(1<<23) - 1 // uniform in [-1,1)
}

// dequantize turns one BlockQ into MDCT coefficients.
func dequantize(b *BlockQ, lay *Layout, rng *noise) []float64 {
	x := make([]float64, lay.M)
	for bd := 0; bd < lay.NB(); bd++ {
		lo, hi := lay.Edges[bd], lay.Edges[bd+1]
		if b.NZ[bd] {
			st := Step(b.SF[bd])
			for k := lo; k < hi; k++ {
				x[k] = float64(b.Q[k]) * st
			}
		} else if b.NF[bd] > 0 {
			amp := NoiseRMS(b.NF[bd]) * math.Sqrt(3)
			for k := lo; k < hi; k++ {
				x[k] = rng.next() * amp
			}
		}
	}
	return x
}

// Decode reconstructs audio from a .chm image.
func Decode(file []byte) (*Audio, error) {
	h, err := ParseContainer(file)
	if err != nil {
		return nil, err
	}
	rc := NewDecoder(h.Payload)
	sx := NewSyntax(rc, h.Rate, h.Channels, h.NoiseFill)
	nf := NumFrames(h.Samples)
	short := make([]bool, nf)
	sx.Flags(short)
	if rc.Err != nil {
		return nil, rc.Err
	}
	out := &Audio{Rate: h.Rate, Ch: make([][]float64, h.Channels)}
	rng := noise(12345)
	for f := 0; f < nf; f++ {
		// grow lazily so a hostile header cannot force a huge allocation up front
		need := (f + 1) * FrameN
		if need > h.Samples {
			need = h.Samples
		}
		for c := range out.Ch {
			if len(out.Ch[c]) < need {
				out.Ch[c] = append(out.Ch[c], make([]float64, need-len(out.Ch[c]))...)
			}
		}
		fr := AllocFrame(h.Channels, h.Rate, short[f])
		sx.Frame(fr, short[f])
		if rc.Err != nil {
			return nil, fmt.Errorf("frame %d: %w", f, rc.Err)
		}
		coef := make([][][]float64, h.Channels)
		for c := 0; c < h.Channels; c++ {
			coef[c] = make([][]float64, len(fr.Blocks[c]))
			for i := range fr.Blocks[c] {
				lay := LayoutFor(len(fr.Blocks[c][i].Q), h.Rate)
				coef[c][i] = dequantize(&fr.Blocks[c][i], lay, &rng)
			}
		}
		if fr.MS {
			for i := range coef[0] {
				for k := range coef[0][i] {
					m, s := coef[0][i][k], coef[1][i][k]
					coef[0][i][k] = (m + s) * math.Sqrt2 / 2
					coef[1][i][k] = (m - s) * math.Sqrt2 / 2
				}
			}
		}
		for c := 0; c < h.Channels; c++ {
			SynthesizeFrame(coef[c], f, short, out.Ch[c])
		}
	}
	return out, nil
}
