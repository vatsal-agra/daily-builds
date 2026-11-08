package codec

import (
	"bytes"
	"fmt"
	"testing"
)

func gen(t testing.TB, preset string, w, h, n int) *Video {
	t.Helper()
	v, err := Generate(GenParams{Preset: preset, W: w, H: h, N: n, Seed: 3})
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func framesEqual(a, b *Frame) bool {
	for i := 0; i < 3; i++ {
		w, h := a.visW(i), a.visH(i)
		pa, pb := a.planes()[i], b.planes()[i]
		for y := 0; y < h; y++ {
			if !bytes.Equal(pa.Pix[pa.idx(0, y):pa.idx(0, y)+w], pb.Pix[pb.idx(0, y):pb.idx(0, y)+w]) {
				return false
			}
		}
	}
	return true
}

// The decoder must reproduce the encoder's reconstruction bit-for-bit.
func TestBitExactAllTools(t *testing.T) {
	cases := []struct {
		name   string
		preset string
		w, h   int
		p      func(*EncParams)
	}{
		{"default", "mixed", 96, 80, func(p *EncParams) {}},
		{"intra-only", "pan", 64, 48, func(p *EncParams) { p.GOP = 1 }},
		{"nodeblock-int", "objects", 80, 64, func(p *EncParams) { p.Deblock = false; p.SubPel = 0 }},
		{"half", "zoom", 80, 64, func(p *EncParams) { p.SubPel = 1 }},
		{"full-search", "pan", 64, 64, func(p *EncParams) { p.Search = SearchFull; p.Range = 8 }},
		{"bframes", "mixed", 96, 80, func(p *EncParams) { p.BFrames = 2 }},
		{"bframes4-gop", "objects", 80, 64, func(p *EncParams) { p.BFrames = 4; p.GOP = 7 }},
		{"fast", "mixed", 96, 80, func(p *EncParams) { p.Effort = 0 }},
		{"hiqp", "noise", 64, 64, func(p *EncParams) { p.QP = 6 }},
		{"loqp", "noise", 64, 64, func(p *EncParams) { p.QP = 51 }},
		{"cut", "cut", 80, 64, func(p *EncParams) { p.BFrames = 1 }},
		{"odd-size", "mixed", 83, 51, func(p *EncParams) { p.BFrames = 1 }},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			v := gen(t, c.preset, c.w, c.h, 10)
			p := DefaultParams()
			c.p(&p)
			r, err := Encode(v, p)
			if err != nil {
				t.Fatal(err)
			}
			d, _, err := Decode(r.Stream)
			if err != nil {
				t.Fatal(err)
			}
			if len(d.Frames) != len(v.Frames) {
				t.Fatalf("frame count %d != %d", len(d.Frames), len(v.Frames))
			}
			for i := range d.Frames {
				if !framesEqual(d.Frames[i], r.Recon[i]) {
					t.Fatalf("frame %d: decoder output differs from encoder reconstruction", i)
				}
			}
		})
	}
}

func TestSmoke(t *testing.T) { fmt.Sprint() }
