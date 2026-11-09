package codec

import (
	"math"
	"math/rand"
	"testing"
)

func directMDCT(x []float64, m int) []float64 {
	out := make([]float64, m)
	s := math.Sqrt(2 / float64(m))
	for k := 0; k < m; k++ {
		var a float64
		for n := 0; n < 2*m; n++ {
			a += x[n] * math.Cos(math.Pi/float64(m)*(float64(n)+0.5+float64(m)/2)*(float64(k)+0.5))
		}
		out[k] = a * s
	}
	return out
}

func TestMDCTMatchesDefinition(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	for _, m := range []int{8, 16, 128, 1024} {
		x := make([]float64, 2*m)
		for i := range x {
			x[i] = r.NormFloat64()
		}
		got := make([]float64, m)
		NewMDCT(m).Forward(x, got)
		want := directMDCT(x, m)
		for k := range want {
			if math.Abs(got[k]-want[k]) > 1e-9 {
				t.Fatalf("M=%d k=%d got %g want %g", m, k, got[k], want[k])
			}
		}
	}
}

func TestIMDCTIsTranspose(t *testing.T) {
	r := rand.New(rand.NewSource(2))
	m := 64
	X := make([]float64, m)
	for i := range X {
		X[i] = r.NormFloat64()
	}
	got := make([]float64, 2*m)
	NewMDCT(m).Inverse(X, got)
	s := math.Sqrt(2 / float64(m))
	for n := 0; n < 2*m; n++ {
		var a float64
		for k := 0; k < m; k++ {
			a += X[k] * math.Cos(math.Pi/float64(m)*(float64(n)+0.5+float64(m)/2)*(float64(k)+0.5))
		}
		if math.Abs(a*s-got[n]) > 1e-9 {
			t.Fatalf("n=%d got %g want %g", n, got[n], a*s)
		}
	}
}
