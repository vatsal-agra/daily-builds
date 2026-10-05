package synth

import (
	"math"
	"testing"
)

func TestDeterministicAndDistinct(t *testing.T) {
	ia, a := Generate(5, 8, 11025)
	ib, b := Generate(5, 8, 11025)
	if ia != ib || len(a) != len(b) {
		t.Fatal("info/len differ")
	}
	for i := range a {
		if a[i] != b[i] {
			t.Fatalf("sample %d differs", i)
		}
	}
	_, c := Generate(6, 8, 11025)
	diff := 0
	for i := range a {
		if a[i] != c[i] {
			diff++
		}
	}
	if diff < len(a)/2 {
		t.Fatal("different seeds produce near-identical audio")
	}
}

func TestLevelsSane(t *testing.T) {
	for seed := int64(1); seed <= 12; seed++ {
		_, x := Generate(seed, 10, 11025)
		peak, ss := 0.0, 0.0
		for _, v := range x {
			if math.IsNaN(v) {
				t.Fatal("NaN")
			}
			peak = math.Max(peak, math.Abs(v))
			ss += v * v
		}
		rms := math.Sqrt(ss / float64(len(x)))
		if peak > 0.91 || rms < 0.03 {
			t.Fatalf("seed %d peak %.2f rms %.3f", seed, peak, rms)
		}
	}
}
