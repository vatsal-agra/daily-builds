package opt

import (
	"math"
	"testing"
)

func TestRosenbrock(t *testing.T) {
	f := func(x []float64) float64 {
		return 100*math.Pow(x[1]-x[0]*x[0], 2) + math.Pow(1-x[0], 2)
	}
	x, v := NelderMead(f, []float64{-1.2, 1}, 4000)
	if v > 1e-8 || math.Abs(x[0]-1) > 1e-3 || math.Abs(x[1]-1) > 1e-3 {
		t.Fatalf("got %v value %v", x, v)
	}
}

func TestQuadraticND(t *testing.T) {
	f := func(x []float64) float64 {
		s := 0.0
		for i, v := range x {
			s += float64(i+1) * (v - float64(i)) * (v - float64(i))
		}
		return s
	}
	x, v := NelderMead(f, make([]float64, 4), 5000)
	if v > 1e-6 {
		t.Fatalf("got %v value %v", x, v)
	}
}

func TestNaNRegionAndEmpty(t *testing.T) {
	f := func(x []float64) float64 {
		if x[0] < 0 {
			return math.NaN()
		}
		return (x[0] - 2) * (x[0] - 2)
	}
	x, v := NelderMead(f, []float64{5}, 500)
	if v > 1e-8 || math.Abs(x[0]-2) > 1e-3 {
		t.Fatalf("got %v %v", x, v)
	}
	if _, v := NelderMead(func([]float64) float64 { return 7 }, nil, 10); v != 7 {
		t.Fatal("empty problem")
	}
}
