package codec

import (
	"math/rand"
	"testing"
)

func TestRangeCoderRoundTrip(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	const n = 200000
	bits := make([]int, n)
	ctx := make([]int, n)
	for i := range bits {
		ctx[i] = r.Intn(4)
		pr := []float64{0.02, 0.5, 0.9, 0.995}[ctx[i]]
		if r.Float64() < pr {
			bits[i] = 1
		}
	}
	enc := NewEncoder()
	ps := make([]Prob, 4)
	for i := range ps {
		ps[i] = NewProb()
	}
	for i := range bits {
		enc.Bit(&ps[ctx[i]], bits[i])
		if i%97 == 0 {
			enc.Bypass(bits[i])
			enc.ExpGolomb(uint32(i))
		}
	}
	out := enc.Finish()
	dec := NewDecoder(out)
	for i := range ps {
		ps[i] = NewProb()
	}
	for i := range bits {
		if g := dec.Bit(&ps[ctx[i]], 0); g != bits[i] {
			t.Fatalf("bit %d: got %d want %d", i, g, bits[i])
		}
		if i%97 == 0 {
			if g := dec.Bypass(0); g != bits[i] {
				t.Fatalf("bypass %d", i)
			}
			if g := dec.ExpGolomb(0); g != uint32(i) {
				t.Fatalf("eg %d got %d", i, g)
			}
		}
	}
	// adaptive coding of skewed data must beat 1 bit/bit comfortably
	if len(out) > 20000 { // ideal ≈ 10.3 kB modelled + ~8 kB Exp-Golomb bypass
		t.Fatalf("poor compression: %d bytes for %d bits", len(out), n)
	}
}

func TestRangeDecoderTruncated(t *testing.T) {
	enc := NewEncoder()
	p := NewProb()
	for i := 0; i < 5000; i++ {
		enc.Bit(&p, i%3&1)
	}
	out := enc.Finish()
	dec := NewDecoder(out[:len(out)/2])
	p = NewProb()
	for i := 0; i < 5000; i++ {
		dec.Bit(&p, 0)
	}
	if dec.Err == nil {
		t.Fatal("truncation not detected")
	}
}
