package sat

import (
	"math/rand"
	"testing"
)

func bruteForce(n int, cls [][]Lit) bool {
	for m := 0; m < 1<<n; m++ {
		all := true
		for _, c := range cls {
			ok := false
			for _, l := range c {
				bit := m>>l.Var()&1 == 1
				if bit != l.Neg() {
					ok = true
					break
				}
			}
			if !ok {
				all = false
				break
			}
		}
		if all {
			return true
		}
	}
	return false
}

func TestRandom3SATAgainstBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for iter := 0; iter < 600; iter++ {
		n := 4 + rng.Intn(9)
		m := int(float64(n) * (3.0 + rng.Float64()*2.5))
		var cls [][]Lit
		s := New()
		for i := 0; i < n; i++ {
			s.NewVar()
		}
		for i := 0; i < m; i++ {
			k := 1 + rng.Intn(3)
			if rng.Intn(3) > 0 {
				k = 3
			}
			var c []Lit
			for j := 0; j < k; j++ {
				c = append(c, MkLit(rng.Intn(n), rng.Intn(2) == 0))
			}
			cls = append(cls, c)
			s.AddClause(c...)
		}
		want := bruteForce(n, cls)
		got := s.Solve()
		if (got == Sat) != want {
			t.Fatalf("iter %d: solver=%v brute=%v", iter, got, want)
		}
		if got == Sat {
			for _, c := range cls {
				ok := false
				for _, l := range c {
					if s.LitValue(l) {
						ok = true
					}
				}
				if !ok {
					t.Fatalf("iter %d: model violates clause %v", iter, c)
				}
			}
		}
	}
}

func TestAssumptionsAndIncremental(t *testing.T) {
	s := New()
	a, b, c := s.NewVar(), s.NewVar(), s.NewVar()
	s.AddClause(MkLit(a, true), MkLit(b, false)) // a -> b
	s.AddClause(MkLit(b, true), MkLit(c, false)) // b -> c
	if s.Solve(MkLit(a, false), MkLit(c, true)) != Unsat {
		t.Fatal("a & !c must be UNSAT")
	}
	if !s.Okay() {
		t.Fatal("solver must stay usable after assumption-UNSAT")
	}
	if s.Solve(MkLit(a, false)) != Sat || !s.Value(c) {
		t.Fatal("a should force c")
	}
	if s.Solve(MkLit(c, true)) != Sat || s.Value(a) {
		t.Fatal("!c should force !a")
	}
	s.AddClause(MkLit(a, false))
	s.AddClause(MkLit(c, true))
	if s.Solve() != Unsat {
		t.Fatal("now globally UNSAT")
	}
}

// Pigeonhole PHP(n+1, n) is UNSAT and forces real conflict analysis.
func TestPigeonhole(t *testing.T) {
	for n := 3; n <= 7; n++ {
		s := New()
		v := make([][]int, n+1)
		for i := range v {
			v[i] = make([]int, n)
			for j := range v[i] {
				v[i][j] = s.NewVar()
			}
			var c []Lit
			for j := 0; j < n; j++ {
				c = append(c, MkLit(v[i][j], false))
			}
			s.AddClause(c...)
		}
		for j := 0; j < n; j++ {
			for i := 0; i <= n; i++ {
				for k := i + 1; k <= n; k++ {
					s.AddClause(MkLit(v[i][j], true), MkLit(v[k][j], true))
				}
			}
		}
		if s.Solve() != Unsat {
			t.Fatalf("PHP(%d,%d) must be UNSAT", n+1, n)
		}
	}
}

func TestLargerRandomSat(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	n := 200
	s := New()
	for i := 0; i < n; i++ {
		s.NewVar()
	}
	var cls [][]Lit
	// planted solution => guaranteed SAT
	plant := make([]bool, n)
	for i := range plant {
		plant[i] = rng.Intn(2) == 0
	}
	for len(cls) < 800 {
		var c []Lit
		sat := false
		for j := 0; j < 3; j++ {
			v := rng.Intn(n)
			neg := rng.Intn(2) == 0
			c = append(c, MkLit(v, neg))
			if plant[v] != neg {
				sat = true
			}
		}
		if sat {
			cls = append(cls, c)
			s.AddClause(c...)
		}
	}
	if s.Solve() != Sat {
		t.Fatal("planted instance must be SAT")
	}
	for _, c := range cls {
		ok := false
		for _, l := range c {
			ok = ok || s.LitValue(l)
		}
		if !ok {
			t.Fatal("model violates a clause")
		}
	}
}
