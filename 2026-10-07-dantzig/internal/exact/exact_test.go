package exact

import (
	"math/big"
	"math/rand"
	"testing"

	"dantzig/internal/model"
)

func rat(a, b int64) *big.Rat { return big.NewRat(a, b) }

func parse(t *testing.T, s string) *model.Model {
	t.Helper()
	m, err := model.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestSolveAndInvertRandom(t *testing.T) {
	r := rand.New(rand.NewSource(3))
	for it := 0; it < 200; it++ {
		n := 1 + r.Intn(7)
		a := make([][]*big.Rat, n)
		keep := make([][]*big.Rat, n)
		for i := range a {
			a[i] = make([]*big.Rat, n)
			keep[i] = make([]*big.Rat, n)
			for j := range a[i] {
				if r.Intn(3) > 0 {
					v := rat(int64(r.Intn(9)-4), int64(1+r.Intn(3)))
					a[i][j] = v
					keep[i][j] = new(big.Rat).Set(v)
				}
			}
		}
		b := make([]*big.Rat, n)
		bk := make([]*big.Rat, n)
		for i := range b {
			b[i] = rat(int64(r.Intn(11)-5), 1)
			bk[i] = new(big.Rat).Set(b[i])
		}
		x, err := Solve(a, b)
		inv, err2 := Invert(keep)
		if (err == nil) != (err2 == nil) {
			t.Fatalf("Solve and Invert disagree on singularity (%v vs %v)", err, err2)
		}
		if err != nil {
			continue
		}
		for i := 0; i < n; i++ { // residual of A x = b must be exactly zero
			s := new(big.Rat)
			for j := 0; j < n; j++ {
				if keep[i][j] != nil {
					s.Add(s, new(big.Rat).Mul(keep[i][j], x[j]))
				}
			}
			if s.Cmp(bk[i]) != 0 {
				t.Fatalf("residual row %d: %s != %s", i, s.RatString(), bk[i].RatString())
			}
		}
		// inverse * b == x
		for i := 0; i < n; i++ {
			s := new(big.Rat)
			for j := 0; j < n; j++ {
				s.Add(s, new(big.Rat).Mul(inv[i][j], bk[j]))
			}
			if s.Cmp(x[i]) != 0 {
				t.Fatalf("inverse disagrees with solve")
			}
		}
	}
}

func TestSingular(t *testing.T) {
	a := [][]*big.Rat{{rat(1, 1), rat(2, 1)}, {rat(2, 1), rat(4, 1)}}
	if _, err := Solve(a, []*big.Rat{rat(1, 1), rat(2, 1)}); err != ErrSingular {
		t.Fatalf("want ErrSingular, got %v", err)
	}
	if _, err := Invert([][]*big.Rat{{rat(0, 1), nil}, {nil, nil}}); err != ErrSingular {
		t.Fatalf("want ErrSingular, got %v", err)
	}
}

func TestLagrangeBoundIsWeakDuality(t *testing.T) {
	m := parse(t, "Minimize\n o: 2 x + 3 y\nSubject To\n a: x + y >= 4\n b: x - y <= 2\nBounds\n x <= 10\n y <= 10\nEnd")
	cost := m.MinCost()
	box := BoxOf(m)
	// optimum is x=3,y=1 -> 9; any y gives a valid lower bound <= 9, and y=(2,0) is tight
	best, ok := LagrangeBound(m, box, cost, []*big.Rat{rat(2, 1), rat(0, 1)})
	if !ok || best.Cmp(rat(8, 1)) != 0 { // d=(0,1): y>=0 bound 8
		t.Fatalf("bound %v %v", best, ok)
	}
	r := rand.New(rand.NewSource(1))
	for i := 0; i < 500; i++ {
		y := []*big.Rat{rat(int64(r.Intn(13)-6), int64(1+r.Intn(3))), rat(int64(r.Intn(13)-6), int64(1+r.Intn(3)))}
		b, ok := LagrangeBound(m, box, cost, y)
		if ok && b.Cmp(rat(9, 1)) > 0 {
			t.Fatalf("bound %s exceeds the optimum 9 for y=%v", b.RatString(), y)
		}
	}
	// a multiplier that needs an infinite side is rejected
	if _, ok := LagrangeBound(m, box, cost, []*big.Rat{rat(-1, 1), rat(0, 1)}); ok {
		t.Fatal("y_a<0 needs a finite upper limit on row a")
	}
}

func TestCheckFarkasAndRay(t *testing.T) {
	m := parse(t, "Minimize\n o: x\nSubject To\n a: x + y >= 5\n b: x + y <= 3\nEnd")
	// y = (1, -1): (x+y) >= 5 and (x+y) <= 3 contradict; d = -(1-1)=0
	if err := CheckFarkas(m, BoxOf(m), []*big.Rat{rat(1, 1), rat(-1, 1)}); err != nil {
		t.Fatalf("valid Farkas rejected: %v", err)
	}
	if err := CheckFarkas(m, BoxOf(m), []*big.Rat{rat(1, 1), rat(0, 1)}); err == nil {
		t.Fatal("accepted a non-certificate")
	}
	m2 := parse(t, "Maximize\n o: x + y\nSubject To\n a: x - y <= 3\nEnd")
	x0 := []*big.Rat{rat(0, 1), rat(0, 1)}
	if err := CheckRay(m2, m2.MinCost(), x0, []*big.Rat{rat(1, 1), rat(1, 1)}); err != nil {
		t.Fatalf("valid ray rejected: %v", err)
	}
	if err := CheckRay(m2, m2.MinCost(), x0, []*big.Rat{rat(1, 1), rat(0, 1)}); err == nil {
		t.Fatal("accepted a ray that violates row a")
	}
	if err := CheckRay(m2, m2.MinCost(), x0, []*big.Rat{rat(-1, 1), rat(-1, 1)}); err == nil {
		t.Fatal("accepted a ray through a variable lower bound")
	}
}

func TestGCDRows(t *testing.T) {
	cases := []struct {
		src string
		bad bool
	}{
		{"Minimize\n o: x\nSubject To\n c: 2 x + 4 y = 3\nInteger\n x y\nEnd", true},
		{"Minimize\n o: x\nSubject To\n c: 2 x + 4 y = 6\nInteger\n x y\nEnd", false},
		{"Minimize\n o: x\nSubject To\n c: 3 x - 3 y = 1\nBounds\n x free\n y free\nInteger\n x y\nEnd", true},
		{"Minimize\n o: x\nSubject To\n c: 5 <= 2 x + 2 y <= 5.5\nInteger\n x y\nEnd", true},
		{"Minimize\n o: x\nSubject To\n c: 5 <= 2 x + 2 y <= 6\nInteger\n x y\nEnd", false},
		{"Minimize\n o: x\nSubject To\n c: 2 x + 2 y = 3\nInteger\n x\nEnd", false}, // y continuous
		{"Minimize\n o: x\nSubject To\n c: 1/2 x + 1/3 y = 1/7\nInteger\n x y\nEnd", true},
		{"Minimize\n o: x\nSubject To\n c: 2 x + 2 y >= 3\nInteger\n x y\nEnd", false},
	}
	for i, c := range cases {
		m := parse(t, c.src)
		got := FindGCDInfeasibleRow(m) >= 0
		if got != c.bad {
			t.Errorf("case %d: gcd infeasible=%v want %v", i, got, c.bad)
		}
	}
}

func TestBasisVertex(t *testing.T) {
	m := parse(t, "Maximize\n o: 3 x + 5 y\nSubject To\n a: x <= 4\n b: 2 y <= 12\n c: 3 x + 2 y <= 18\nEnd")
	// basis {x, y, logical a}: columns 0,1 and n+0; nonbasic logical b at upper, c at upper
	st := []byte{Basic, Basic, Basic, AtUpper, AtUpper}
	x, r, err := PrimalFromBasis(m, BoxOf(m), st)
	if err != nil {
		t.Fatal(err)
	}
	if x[0].Cmp(rat(2, 1)) != 0 || x[1].Cmp(rat(6, 1)) != 0 || r[0].Cmp(rat(2, 1)) != 0 {
		t.Fatalf("vertex %v %v", x, r)
	}
	y, err := DualsFromBasis(m, st, m.MinCost())
	if err != nil {
		t.Fatal(err)
	}
	b, ok := LagrangeBound(m, BoxOf(m), m.MinCost(), y)
	if !ok || b.Cmp(rat(-36, 1)) != 0 {
		t.Fatalf("dual bound %v", b)
	}
}
