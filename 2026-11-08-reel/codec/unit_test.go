package codec

import (
	"bytes"
	"math"
	"math/rand"
	"testing"
)

// ---- range coder ---------------------------------------------------------

func TestRangeCoderRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	for trial := 0; trial < 50; trial++ {
		n := 1 + rng.Intn(20000)
		skew := []float64{0.5, 0.9, 0.99, 0.9995, 0.05}[trial%5]
		type op struct{ ctx, bit, kind int }
		ops := make([]op, n)
		for i := range ops {
			b := 0
			if rng.Float64() > skew {
				b = 1
			}
			ops[i] = op{rng.Intn(6), b, rng.Intn(5)}
		}
		var ctx [6]Ctx
		for i := range ctx {
			ctx[i] = NewCtx()
		}
		e := newRCEnc()
		for _, o := range ops {
			if o.kind == 0 {
				e.bypass(o.bit)
			} else {
				e.bit(&ctx[o.ctx], o.bit)
			}
		}
		data := e.finish()
		for i := range ctx {
			ctx[i] = NewCtx()
		}
		d := newRCDec(data)
		for i, o := range ops {
			var got int
			if o.kind == 0 {
				got = d.bypass(0)
			} else {
				got = d.bit(&ctx[o.ctx], 0)
			}
			if got != o.bit {
				t.Fatalf("trial %d: bit %d of %d differs", trial, i, n)
			}
		}
		if d.err() != nil {
			t.Fatalf("trial %d: %v", trial, d.err())
		}
	}
}

// A heavily skewed source must compress far below 1 bit/symbol (adaptivity works).
func TestRangeCoderCompresses(t *testing.T) {
	c := NewCtx()
	e := newRCEnc()
	rng := rand.New(rand.NewSource(1))
	n := 100000
	for i := 0; i < n; i++ {
		b := 0
		if rng.Float64() < 0.02 {
			b = 1
		}
		e.bit(&c, b)
	}
	bits := float64(len(e.finish()) * 8)
	h := -(0.02*math.Log2(0.02) + 0.98*math.Log2(0.98)) * float64(n)
	if bits > h*1.08 {
		t.Errorf("coded %.0f bits, entropy %.0f (over 8%% overhead)", bits, h)
	}
}

func TestExpGolombRoundTrip(t *testing.T) {
	vals := []int{0, 1, 2, 3, 7, 8, 100, 319, 1000, 65535, 1 << 20}
	for k := 0; k < 3; k++ {
		e := newRCEnc()
		for _, v := range vals {
			codeEG(e, v, k)
		}
		d := newRCDec(e.finish())
		for _, v := range vals {
			if got := codeEG(d, 0, k); got != v {
				t.Fatalf("k=%d: want %d got %d", k, v, got)
			}
		}
	}
}

// ---- transform -------------------------------------------------------------

func TestTransformQuantRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	for _, qp := range []int{0, 6, 12, 24, 36, 48} {
		var worst float64
		for it := 0; it < 400; it++ {
			var in, w, lv, dq, out [16]int32
			base := int32(rng.Intn(100)) - 50
			for i := range in {
				in[i] = base + int32(rng.Intn(61)) - 30
			}
			fdct4(&in, &w)
			quant(&w, &lv, qp, true)
			dequant(&lv, &dq, qp)
			idct4(&dq, &out)
			var se float64
			for i := range in {
				d := float64(in[i] - out[i])
				se += d * d
			}
			if rm := math.Sqrt(se / 16); rm > worst {
				worst = rm
			}
		}
		// the quantiser error is bounded by a small multiple of the step
		limit := 1.0 + 0.9*Qstep(qp)
		if worst > limit {
			t.Errorf("qp %d: worst RMS error %.2f exceeds %.2f", qp, worst, limit)
		}
		if qp == 0 && worst > 1.0 {
			t.Errorf("qp 0 should be near-lossless, worst RMS %.2f", worst)
		}
	}
}

func TestZigzagIsPermutation(t *testing.T) {
	var seen [16]bool
	for _, z := range zigzag {
		if seen[z] {
			t.Fatal("duplicate")
		}
		seen[z] = true
	}
}

// ---- interpolation -----------------------------------------------------------

// The 6-tap filter and the averaging rules reproduce linear ramps exactly (±1 for rounding):
// a strong check that every one of the 16 quarter-pel cases uses the right neighbours.
func TestInterpolationOnRamp(t *testing.T) {
	p := newPlane(64, 64, 32)
	for y := -32; y < 96; y++ {
		for x := -32; x < 96; x++ {
			p.Pix[p.idx(x, y)] = uint8(40 + x + 2*y/1)
			v := 40 + x + y
			if v < 0 {
				v = 0
			}
			p.Pix[p.idx(x, y)] = clip255(v)
		}
	}
	for fy := 0; fy < 4; fy++ {
		for fx := 0; fx < 4; fx++ {
			var dst [64]uint8
			predLuma(p, (20*4)+fx, (20*4)+fy, 8, 8, dst[:])
			for j := 0; j < 8; j++ {
				for i := 0; i < 8; i++ {
					want := 40 + float64(20+i) + float64(20+j) + float64(fx)/4 + float64(fy)/4
					if math.Abs(float64(dst[j*8+i])-want) > 1.01 {
						t.Fatalf("frac (%d,%d) px (%d,%d): got %d want %.2f", fx, fy, i, j, dst[j*8+i], want)
					}
				}
			}
		}
	}
	// chroma bilinear on the same ramp
	var dst [16]uint8
	predChroma(p, 10, 10, MV{X: 3, Y: 5}, 4, 4, dst[:])
	want := 40 + 10 + 10 + 3.0/8 + 5.0/8
	if math.Abs(float64(dst[0])-want) > 1 {
		t.Errorf("chroma: got %d want %.2f", dst[0], want)
	}
}

// Independent brute-force implementation of the half-pel positions straight from the definition.
func TestHalfPelMatchesDefinition(t *testing.T) {
	rng := rand.New(rand.NewSource(5))
	p := newPlane(48, 48, 32)
	for i := range p.Pix {
		p.Pix[i] = uint8(rng.Intn(256))
	}
	taps := []int{1, -5, 20, 20, -5, 1}
	at := func(x, y int) int { return int(p.Pix[p.idx(x, y)]) }
	for it := 0; it < 200; it++ {
		x, y := rng.Intn(30), rng.Intn(30)
		// horizontal half-pel
		s := 0
		for k, tp := range taps {
			s += tp * at(x-2+k, y)
		}
		wantB := int(clip255((s + 16) >> 5))
		var dst [1]uint8
		predLuma(p, x*4+2, y*4, 1, 1, dst[:])
		if int(dst[0]) != wantB {
			t.Fatalf("b mismatch at (%d,%d): %d vs %d", x, y, dst[0], wantB)
		}
		// centre (j) from unrounded intermediates in either order must agree
		jv := 0
		for k, tp := range taps {
			row := 0
			for k2, tp2 := range taps {
				row += tp2 * at(x-2+k2, y-2+k)
			}
			jv += tp * row
		}
		wantJ := int(clip255((jv + 512) >> 10))
		predLuma(p, x*4+2, y*4+2, 1, 1, dst[:])
		if int(dst[0]) != wantJ {
			t.Fatalf("j mismatch at (%d,%d): %d vs %d", x, y, dst[0], wantJ)
		}
	}
}

// ---- intra / loop filter -------------------------------------------------------------

func TestIntraPredictors(t *testing.T) {
	p := newPlane(32, 32, 4)
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			p.Pix[p.idx(x, y)] = uint8(10 + 3*x + 2*y)
		}
	}
	var dst [256]uint8
	predictIntra(p, 16, 16, 16, 1, dst[:]) // vertical copies the row above
	for i := 0; i < 16; i++ {
		if dst[5*16+i] != p.Pix[p.idx(16+i, 15)] {
			t.Fatal("vertical")
		}
	}
	predictIntra(p, 16, 16, 16, 2, dst[:])
	for j := 0; j < 16; j++ {
		if dst[j*16+3] != p.Pix[p.idx(15, 16+j)] {
			t.Fatal("horizontal")
		}
	}
	predictIntra(p, 16, 16, 16, 3, dst[:]) // true-motion is exact on a plane
	for j := 0; j < 16; j++ {
		for i := 0; i < 16; i++ {
			if dst[j*16+i] != p.Pix[p.idx(16+i, 16+j)] {
				t.Fatalf("TM not exact on a plane at %d,%d", i, j)
			}
		}
	}
	predictIntra(p, 0, 0, 16, 0, dst[:])
	if dst[0] != 128 {
		t.Fatal("DC with no neighbours must be 128")
	}
}

// The loop filter must smooth a blocking step but leave a genuine strong edge alone.
func TestDeblockSmoothsStepKeepsEdge(t *testing.T) {
	mk := func(step int) []uint8 {
		s := make([]uint8, 8)
		for i := range s {
			if i < 4 {
				s[i] = 100
			} else {
				s[i] = uint8(100 + step)
			}
		}
		return s
	}
	idx := clampi(30, 0, 51)
	s := mk(6) // small step: blocking artefact
	filterLine(s, 4, 1, alphaTab[idx], betaTab[idx], tc0Tab[2][idx], true)
	if !(s[3] > 100 && s[4] < 106) {
		t.Errorf("step not smoothed: %v", s)
	}
	e := mk(120) // real edge
	filterLine(e, 4, 1, alphaTab[idx], betaTab[idx], tc0Tab[2][idx], true)
	if !bytes.Equal(e, mk(120)) {
		t.Errorf("strong edge was blurred: %v", e)
	}
}

// ---- whole-codec properties ------------------------------------------------------------

func TestEncodeDeterministic(t *testing.T) {
	v := gen(t, "mixed", 64, 48, 6)
	p := DefaultParams()
	p.BFrames = 1
	a, _ := Encode(v, p)
	b, _ := Encode(v, p)
	if !bytes.Equal(a.Stream, b.Stream) {
		t.Fatal("two identical encodes produced different streams")
	}
}

func TestRateDistortionMonotonic(t *testing.T) {
	v := gen(t, "objects", 96, 80, 8)
	var prevBytes int
	var prevPSNR float64
	for i, qp := range []int{44, 36, 28, 20, 12} {
		p := DefaultParams()
		p.QP = qp
		r, err := Encode(v, p)
		if err != nil {
			t.Fatal(err)
		}
		rec := &Video{Width: v.Width, Height: v.Height, FPSNum: 30, FPSDen: 1, Frames: r.Recon}
		m, _ := Compare(v, rec)
		if i > 0 && (r.Bytes <= prevBytes || m.PSNR <= prevPSNR) {
			t.Errorf("qp %d: bytes %d (prev %d), psnr %.2f (prev %.2f) not monotonic", qp, r.Bytes, prevBytes, m.PSNR, prevPSNR)
		}
		prevBytes, prevPSNR = r.Bytes, m.PSNR
	}
}

func TestIntraModesAllUsed(t *testing.T) {
	v := gen(t, "objects", 128, 96, 2)
	p := DefaultParams()
	p.GOP = 1
	p.QP = 24
	r, _ := Encode(v, p)
	var tot [4]int
	for _, s := range r.Stats {
		for i, c := range s.IModes {
			tot[i] += c
		}
	}
	for m, c := range tot {
		if c == 0 {
			t.Errorf("intra mode %d never chosen: %v", m, tot)
		}
	}
}

func TestRejectsBadInputs(t *testing.T) {
	v := gen(t, "pan", 32, 32, 2)
	for _, p := range []EncParams{
		func() EncParams { p := DefaultParams(); p.QP = 52; return p }(),
		func() EncParams { p := DefaultParams(); p.Range = 41; return p }(),
		func() EncParams { p := DefaultParams(); p.BFrames = 9; return p }(),
		func() EncParams { p := DefaultParams(); p.SubPel = 3; return p }(),
	} {
		if _, err := Encode(v, p); err == nil {
			t.Errorf("params %+v should be rejected", p)
		}
	}
	if _, err := Encode(&Video{Width: 32, Height: 32, FPSNum: 30, FPSDen: 1}, DefaultParams()); err == nil {
		t.Error("empty video should be rejected")
	}
	bad := gen(t, "pan", 32, 32, 2)
	bad.Frames[1] = NewFrame(48, 32)
	if _, err := Encode(bad, DefaultParams()); err == nil {
		t.Error("mixed frame sizes should be rejected")
	}
}

// Rate control hits its target within a few percent on content where the target is reachable.
func TestRateControlAccuracy(t *testing.T) {
	v := gen(t, "mixed", 176, 144, 24)
	for _, kbps := range []int{80, 200, 600} {
		p := DefaultParams()
		p.Bitrate = kbps
		p.BFrames = 2
		r, err := Encode(v, p)
		if err != nil {
			t.Fatal(err)
		}
		got := float64(r.Bytes) * 8 / (float64(len(v.Frames)) / v.FPS()) / 1000
		if math.Abs(got-float64(kbps))/float64(kbps) > 0.08 {
			t.Errorf("target %d kbit/s, got %.1f (>8%% off)", kbps, got)
		}
	}
}
