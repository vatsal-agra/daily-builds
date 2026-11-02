package mat

import (
	"math"
	"math/rand"
	"testing"
)

func randSPD(r *rand.Rand, n int) *M {
	a := New(n, n)
	for i := range a.D {
		a.D[i] = r.NormFloat64()
	}
	return a.Mul(a.T()).Add(Eye(n).Scale(0.5))
}

func TestInvSolveDetChol(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	for n := 1; n <= 8; n++ {
		a := randSPD(r, n)
		inv, err := a.Inv()
		if err != nil {
			t.Fatal(err)
		}
		id := a.Mul(inv)
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				want := 0.0
				if i == j {
					want = 1
				}
				if math.Abs(id.At(i, j)-want) > 1e-8 {
					t.Fatalf("n=%d A·A⁻¹ off at %d,%d: %v", n, i, j, id.At(i, j))
				}
			}
		}
		l, err := a.Chol()
		if err != nil {
			t.Fatal(err)
		}
		rec := l.Mul(l.T())
		for i := range rec.D {
			if math.Abs(rec.D[i]-a.D[i]) > 1e-8 {
				t.Fatal("L·Lᵀ != A")
			}
		}
		det, _ := a.Det()
		ld, _ := a.LogDetSPD()
		if math.Abs(math.Log(det)-ld) > 1e-8 {
			t.Fatalf("logdet mismatch %v %v", math.Log(det), ld)
		}
	}
}

func TestDetKnownAndSingular(t *testing.T) {
	d, _ := From(2, 2, 1, 2, 3, 4).Det()
	if math.Abs(d+2) > 1e-12 {
		t.Fatalf("det = %v want -2", d)
	}
	if _, err := From(2, 2, 1, 2, 2, 4).Inv(); err != ErrSingular {
		t.Fatalf("want ErrSingular, got %v", err)
	}
	if _, err := From(2, 2, 1, 2, 2, 1).Chol(); err != ErrSingular {
		t.Fatalf("indefinite matrix must fail Cholesky, got %v", err)
	}
}

func TestShapePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("mismatched Mul must panic")
		}
	}()
	New(2, 3).Mul(New(2, 3))
}
