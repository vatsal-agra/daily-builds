package lp

import (
	"math/big"
	"math/rand"
	"testing"

	"dantzig/internal/exact"
	"dantzig/internal/model"
)

func mustParse(t *testing.T, s string) *model.Model {
	t.Helper()
	m, err := model.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestTextbook(t *testing.T) {
	m := mustParse(t, `
Maximize
 obj: 3 x + 5 y
Subject To
 c1: x <= 4
 c2: 2 y <= 12
 c3: 3 x + 2 y <= 18
End`)
	s := Solve(m)
	if s.Status != Optimal || !s.Certified {
		t.Fatalf("%v %s", s.Status, s.Note)
	}
	// max = 36 at (2,6); min-sense obj = -36
	if s.Obj.Cmp(big.NewRat(-36, 1)) != 0 {
		t.Fatalf("obj %s", s.Obj.RatString())
	}
}

func TestInfeasibleUnbounded(t *testing.T) {
	m := mustParse(t, "Minimize\n obj: x + y\nSubject To\n a: x + y >= 5\n b: x + y <= 3\nEnd")
	if s := Solve(m); s.Status != Infeasible || !s.Certified {
		t.Fatalf("%v %v %s", s.Status, s.Certified, s.Note)
	}
	m = mustParse(t, "Maximize\n obj: x + y\nSubject To\n a: x - y <= 3\nEnd")
	if s := Solve(m); s.Status != Unbounded || !s.Certified {
		t.Fatalf("%v %v %s", s.Status, s.Certified, s.Note)
	}
}

// randomModel builds a random small LP with mixed row types and bounds.
func randomModel(r *rand.Rand, n, mm int) *model.Model {
	m := model.New()
	for j := 0; j < n; j++ {
		v := m.AddVar("x" + string(rune('a'+j)))
		switch r.Intn(5) {
		case 0:
			m.Vars[v].Hi = big.NewRat(int64(1+r.Intn(8)), 1)
		case 1:
			m.Vars[v].Lo, m.Vars[v].Hi = nil, nil
		case 2:
			m.Vars[v].Lo = big.NewRat(int64(-3+r.Intn(6)), 1)
			m.Vars[v].Hi = new(big.Rat).Add(m.Vars[v].Lo, big.NewRat(int64(r.Intn(7)), 1))
		}
		m.Vars[v].Obj = big.NewRat(int64(r.Intn(11)-5), int64(1+r.Intn(3)))
	}
	m.Maximize = r.Intn(2) == 0
	for i := 0; i < mm; i++ {
		row := model.Row{Name: "r" + string(rune('a'+i))}
		for j := 0; j < n; j++ {
			if r.Intn(3) > 0 {
				row.Entries = append(row.Entries, model.Entry{J: j, V: big.NewRat(int64(r.Intn(9)-4), int64(1+r.Intn(2)))})
			}
		}
		var ents []model.Entry
		for _, e := range row.Entries {
			if e.V.Sign() != 0 {
				ents = append(ents, e)
			}
		}
		if len(ents) == 0 {
			ents = []model.Entry{{J: 0, V: big.NewRat(1, 1)}}
		}
		row.Entries = ents
		b := big.NewRat(int64(r.Intn(21)-6), 1)
		switch r.Intn(4) {
		case 0:
			row.Hi = b
		case 1:
			row.Lo = b
		case 2:
			row.Lo, row.Hi = b, new(big.Rat).Set(b)
		case 3:
			row.Lo = b
			row.Hi = new(big.Rat).Add(b, big.NewRat(int64(r.Intn(8)), 1))
		}
		m.Rows = append(m.Rows, row)
	}
	return m
}

// Every outcome on random LPs must come with an exact certificate.
func TestRandomAllCertified(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	counts := map[Status]int{}
	for it := 0; it < 3000; it++ {
		m := randomModel(r, 2+r.Intn(5), 1+r.Intn(6))
		s := Solve(m)
		counts[s.Status]++
		if !s.Certified {
			t.Fatalf("iteration %d: status %v uncertified: %s\n%s", it, s.Status, s.Note, model.Format(m))
		}
	}
	t.Logf("outcomes: %v", counts)
	if counts[Optimal] < 300 || counts[Infeasible] < 100 || counts[Unbounded] < 30 {
		t.Fatalf("random generator not exercising all outcomes: %v", counts)
	}
}

// Brute-force vertex enumeration oracle for tiny bounded LPs.
func TestAgainstEnumeration(t *testing.T) {
	r := rand.New(rand.NewSource(11))
	checked := 0
	for it := 0; it < 400; it++ {
		m := randomModel(r, 2, 1+r.Intn(3))
		for j := range m.Vars { // bound everything so the optimum exists if feasible
			if m.Vars[j].Lo == nil {
				m.Vars[j].Lo = big.NewRat(-6, 1)
			}
			if m.Vars[j].Hi == nil {
				m.Vars[j].Hi = big.NewRat(9, 1)
			}
			if m.Vars[j].Lo.Cmp(m.Vars[j].Hi) > 0 {
				m.Vars[j].Hi = new(big.Rat).Add(m.Vars[j].Lo, big.NewRat(1, 1))
			}
		}
		best, feasible := bruteForce2D(m)
		s := Solve(m)
		if !s.Certified {
			t.Fatalf("uncertified %v %s", s.Status, s.Note)
		}
		if feasible != (s.Status == Optimal) {
			t.Fatalf("it %d feasibility mismatch brute=%v solver=%v\n%s", it, feasible, s.Status, model.Format(m))
		}
		if feasible {
			if best.Cmp(s.Obj) != 0 {
				t.Fatalf("it %d objective mismatch brute=%s solver=%s\n%s", it, best.RatString(), s.Obj.RatString(), model.Format(m))
			}
			checked++
		}
	}
	if checked < 100 {
		t.Fatalf("only %d feasible cases", checked)
	}
}

// bruteForce2D enumerates all intersections of pairs of constraint boundaries.
func bruteForce2D(m *model.Model) (*big.Rat, bool) {
	type line struct{ a, b, c *big.Rat } // a x + b y = c
	var lines []line
	one, zero := big.NewRat(1, 1), new(big.Rat)
	for j := 0; j < 2; j++ {
		for _, bd := range []*big.Rat{m.Vars[j].Lo, m.Vars[j].Hi} {
			if bd == nil {
				continue
			}
			if j == 0 {
				lines = append(lines, line{one, zero, bd})
			} else {
				lines = append(lines, line{zero, one, bd})
			}
		}
	}
	for _, r := range m.Rows {
		a, b := new(big.Rat), new(big.Rat)
		for _, e := range r.Entries {
			if e.J == 0 {
				a.Set(e.V)
			} else {
				b.Set(e.V)
			}
		}
		for _, bd := range []*big.Rat{r.Lo, r.Hi} {
			if bd != nil {
				lines = append(lines, line{a, b, bd})
			}
		}
	}
	cost := m.MinCost()
	var best *big.Rat
	for i := range lines {
		for k := i + 1; k < len(lines); k++ {
			l1, l2 := lines[i], lines[k]
			det := new(big.Rat).Sub(new(big.Rat).Mul(l1.a, l2.b), new(big.Rat).Mul(l2.a, l1.b))
			if det.Sign() == 0 {
				continue
			}
			x := new(big.Rat).Quo(new(big.Rat).Sub(new(big.Rat).Mul(l1.c, l2.b), new(big.Rat).Mul(l2.c, l1.b)), det)
			y := new(big.Rat).Quo(new(big.Rat).Sub(new(big.Rat).Mul(l1.a, l2.c), new(big.Rat).Mul(l2.a, l1.c)), det)
			pt := []*big.Rat{x, y}
			if exact.CheckPoint(m, exact.BoxOf(m), pt, false) != nil {
				continue
			}
			v := exact.Dot(cost, pt)
			if best == nil || v.Cmp(best) < 0 {
				best = v
			}
		}
	}
	return best, best != nil
}

// Warm-started re-solves (dual simplex) after bound changes must agree with
// cold solves, and be certified.
func TestWarmStartMatchesCold(t *testing.T) {
	r := rand.New(rand.NewSource(99))
	dualUsed := 0
	for it := 0; it < 1500; it++ {
		m := randomModel(r, 3+r.Intn(4), 2+r.Intn(5))
		for j := range m.Vars {
			if m.Vars[j].Lo == nil {
				m.Vars[j].Lo = big.NewRat(-5, 1)
			}
			if m.Vars[j].Hi == nil {
				m.Vars[j].Hi = big.NewRat(10, 1)
			}
			if m.Vars[j].Lo.Cmp(m.Vars[j].Hi) > 0 {
				m.Vars[j].Hi = new(big.Rat).Set(m.Vars[j].Lo)
			}
		}
		box := exact.BoxOf(m)
		sv := simplexNew(m, box)
		if sv.Solve(posInf) != 0 {
			continue
		}
		// tighten a random variable around its current value
		j := r.Intn(len(m.Vars))
		v := sv.X[j]
		box2 := box.Clone()
		if r.Intn(2) == 0 {
			hi := big.NewRat(int64(floorf(v)), 1)
			if box2.Lo[j].Cmp(hi) > 0 {
				continue
			}
			box2.Hi[j] = hi
		} else {
			lo := big.NewRat(int64(floorf(v))+1, 1)
			if box2.Hi[j].Cmp(lo) < 0 {
				continue
			}
			box2.Lo[j] = lo
		}
		lo, hi := model.Float(box2.Lo[j]), model.Float(box2.Hi[j])
		sv.SetBounds(j, lo, hi)
		dualUsed++
		res := sv.Solve(posInf)
		// cold reference on the same box
		m2 := m.Clone()
		m2.Vars[j].Lo, m2.Vars[j].Hi = box2.Lo[j], box2.Hi[j]
		cold := Solve(m2)
		if !cold.Certified {
			t.Fatalf("cold uncertified %s", cold.Note)
		}
		switch cold.Status {
		case Optimal:
			if res != 0 {
				t.Fatalf("it %d warm=%v cold optimal\n%s", it, res, model.Format(m2))
			}
			x, _, obj, err := OptimalCert(m2, box2, sv.Statuses())
			if err != nil {
				t.Fatalf("warm basis not exactly optimal: %v", err)
			}
			_ = x
			if obj.Cmp(cold.Obj) != 0 {
				t.Fatalf("warm obj %s cold %s", obj.RatString(), cold.Obj.RatString())
			}
		case Infeasible:
			if res != 1 {
				t.Fatalf("it %d warm=%v cold infeasible\n%s", it, res, model.Format(m2))
			}
			if _, err := FarkasCert(m2, box2, sv); err != nil {
				t.Fatalf("warm farkas: %v", err)
			}
		}
	}
	t.Logf("warm re-solves: %d", dualUsed)
	if dualUsed < 300 {
		t.Fatal("too few warm-start cases")
	}
}
