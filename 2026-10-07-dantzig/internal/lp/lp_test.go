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

func TestCyclingExamples(t *testing.T) {
	// Beale's classic cycling LP (optimum -5/4)
	m := mustParse(t, `
Minimize
 o: - 3/4 x4 + 20 x5 - 1/2 x6 + 6 x7
Subject To
 c1: 1/4 x4 - 8 x5 - x6 + 9 x7 <= 0
 c2: 1/2 x4 - 12 x5 - 1/2 x6 + 3 x7 <= 0
 c3: x6 <= 1
End`)
	s := Solve(m)
	if s.Status != Optimal || !s.Certified || s.Obj.Cmp(big.NewRat(-5, 4)) != 0 {
		t.Fatalf("beale: %v %s %v", s.Status, s.Note, s.Obj)
	}
	// Kuhn's example
	m = mustParse(t, `
Minimize
 o: - 2 x1 - 3 x2 + x3 + 12 x4
Subject To
 c1: - 2 x1 - 9 x2 + x3 + 9 x4 <= 0
 c2: 1/3 x1 + x2 - 1/3 x3 - 2 x4 <= 0
End`)
	if s := Solve(m); !s.Certified {
		t.Fatalf("kuhn: %v %s", s.Status, s.Note)
	}
}

func kleeMinty(n int) (*model.Model, *big.Rat) {
	m := model.New()
	m.Maximize = true
	pow := func(b, e int) *big.Int { return new(big.Int).Exp(big.NewInt(int64(b)), big.NewInt(int64(e)), nil) }
	for j := 0; j < n; j++ {
		v := m.AddVar("x" + string(rune('a'+j)))
		m.Vars[v].Obj = new(big.Rat).SetInt(pow(2, n-1-j))
	}
	for i := 0; i < n; i++ {
		row := model.Row{Name: "c" + string(rune('a'+i))}
		for j := 0; j < i; j++ {
			row.Entries = append(row.Entries, model.Entry{J: j, V: new(big.Rat).SetInt(pow(2, i-j+1))})
		}
		row.Entries = append(row.Entries, model.Entry{J: i, V: big.NewRat(1, 1)})
		row.Hi = new(big.Rat).SetInt(pow(5, i+1))
		m.Rows = append(m.Rows, row)
	}
	return m, new(big.Rat).SetInt(pow(5, n))
}

func TestKleeMinty(t *testing.T) {
	for n := 2; n <= 14; n++ {
		m, opt := kleeMinty(n)
		s := Solve(m)
		if s.Status != Optimal || !s.Certified || new(big.Rat).Neg(s.Obj).Cmp(opt) != 0 {
			t.Fatalf("n=%d: %v %s obj=%v want -%s", n, s.Status, s.Note, s.Obj, opt.RatString())
		}
	}
}

func TestLargerFeasibleLPs(t *testing.T) {
	r := rand.New(rand.NewSource(5))
	for it := 0; it < 25; it++ {
		n, mm := 20+r.Intn(30), 10+r.Intn(25)
		m := model.New()
		m.Maximize = true
		for j := 0; j < n; j++ {
			v := m.AddVar("x" + string(rune('A'+j%26)) + string(rune('a'+j/26)))
			m.Vars[v].Obj = big.NewRat(int64(1+r.Intn(20)), 1)
		}
		for i := 0; i < mm; i++ {
			row := model.Row{Name: "r" + string(rune('A'+i%26)) + string(rune('a'+i/26))}
			for j := 0; j < n; j++ {
				if r.Intn(2) == 0 {
					row.Entries = append(row.Entries, model.Entry{J: j, V: big.NewRat(int64(1+r.Intn(9)), 1)})
				}
			}
			if len(row.Entries) == 0 {
				row.Entries = []model.Entry{{J: 0, V: big.NewRat(1, 1)}}
			}
			row.Hi = big.NewRat(int64(100+r.Intn(900)), 1)
			m.Rows = append(m.Rows, row)
		}
		s := Solve(m)
		if s.Status != Optimal || !s.Certified {
			t.Fatalf("it %d: %v %s", it, s.Status, s.Note)
		}
	}
}

func TestDegenerateAssignmentLPs(t *testing.T) {
	r := rand.New(rand.NewSource(8))
	for it := 0; it < 15; it++ {
		n := 3 + r.Intn(10)
		m := model.New()
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				v := m.AddVar("x" + string(rune('a'+i)) + string(rune('a'+j)))
				m.Vars[v].Obj = big.NewRat(int64(1+r.Intn(5)), 1) // many ties => degenerate
			}
		}
		for i := 0; i < n; i++ {
			rr := model.Row{Name: "w" + string(rune('a'+i)), Lo: big.NewRat(1, 1), Hi: big.NewRat(1, 1)}
			cc := model.Row{Name: "j" + string(rune('a'+i)), Lo: big.NewRat(1, 1), Hi: big.NewRat(1, 1)}
			for j := 0; j < n; j++ {
				rr.Entries = append(rr.Entries, model.Entry{J: i*n + j, V: big.NewRat(1, 1)})
				cc.Entries = append(cc.Entries, model.Entry{J: j*n + i, V: big.NewRat(1, 1)})
			}
			m.Rows = append(m.Rows, rr, cc)
		}
		s := Solve(m)
		if s.Status != Optimal || !s.Certified {
			t.Fatalf("n=%d: %v %s", n, s.Status, s.Note)
		}
		for _, v := range s.X {
			if !v.IsInt() {
				t.Fatalf("assignment LP vertex is fractional")
			}
		}
	}
}

// Highly degenerate 0/1 data: primal-only and the default (dual-first) path
// must agree on status and objective, and every verdict must be certified.
func TestDegenerateBinaryDataPrimalVsDual(t *testing.T) {
	r := rand.New(rand.NewSource(404))
	agree := 0
	for it := 0; it < 6000; it++ {
		n, mm := 3+r.Intn(6), 2+r.Intn(6)
		m := model.New()
		m.Maximize = r.Intn(2) == 0
		for j := 0; j < n; j++ {
			v := m.AddVar("x" + string(rune('a'+j)))
			m.Vars[v].Obj = big.NewRat(int64(r.Intn(3)-1), 1)
			m.Vars[v].Hi = big.NewRat(int64(1+r.Intn(2)), 1)
		}
		for i := 0; i < mm; i++ {
			row := model.Row{Name: "r" + string(rune('a'+i))}
			for j := 0; j < n; j++ {
				if c := r.Intn(3) - 1; c != 0 {
					row.Entries = append(row.Entries, model.Entry{J: j, V: big.NewRat(int64(c), 1)})
				}
			}
			if len(row.Entries) == 0 {
				row.Entries = []model.Entry{{J: 0, V: big.NewRat(1, 1)}}
			}
			b := big.NewRat(int64(r.Intn(3)), 1)
			switch r.Intn(3) {
			case 0:
				row.Hi = b
			case 1:
				row.Lo = b
			default:
				row.Lo, row.Hi = b, new(big.Rat).Set(b)
			}
			m.Rows = append(m.Rows, row)
		}
		def := Solve(m)
		if !def.Certified {
			t.Fatalf("it %d default path uncertified: %v %s\n%s", it, def.Status, def.Note, model.Format(m))
		}
		box := exact.BoxOf(m)
		sv := simplexNew(m, box)
		res := sv.SolvePrimal()
		switch def.Status {
		case Optimal:
			if res != 0 {
				t.Fatalf("it %d primal-only %v but default optimal\n%s", it, res, model.Format(m))
			}
			_, _, obj, err := OptimalCert(m, box, sv.Statuses())
			if err != nil || obj.Cmp(def.Obj) != 0 {
				t.Fatalf("it %d primal-only optimum differs: %v %v vs %v\n%s", it, obj, err, def.Obj, model.Format(m))
			}
		case Infeasible:
			if res != 1 {
				t.Fatalf("it %d primal-only %v but default infeasible\n%s", it, res, model.Format(m))
			}
		case Unbounded:
			if res != 2 {
				t.Fatalf("it %d primal-only %v but default unbounded\n%s", it, res, model.Format(m))
			}
		}
		agree++
	}
	t.Logf("%d agreeing cases", agree)
}
