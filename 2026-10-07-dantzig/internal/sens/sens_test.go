package sens

import (
	"math/big"
	"math/rand"
	"testing"

	"dantzig/internal/lp"
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

// objective of a certified LP optimum in the model's own sense.
func solveObj(t *testing.T, m *model.Model) (*big.Rat, bool) {
	t.Helper()
	s := lp.Solve(m)
	if !s.Certified {
		t.Fatalf("uncertified: %v %s\n%s", s.Status, s.Note, model.Format(m))
	}
	if s.Status != lp.Optimal {
		return nil, false
	}
	o := new(big.Rat).Set(s.Obj)
	if m.Maximize {
		o.Neg(o)
	}
	return o.Add(o, m.ObjConst), true
}

func TestTextbookNumbers(t *testing.T) {
	// Wyndor Glass: max 3x+5y, x<=4, 2y<=12, 3x+2y<=18 -> 36 at (2,6)
	m := parse(t, "Maximize\n o: 3 x + 5 y\nSubject To\n a: x <= 4\n b: 2 y <= 12\n c: 3 x + 2 y <= 18\nEnd")
	rep, err := Analyze(m)
	if err != nil {
		t.Fatal(err)
	}
	if rep.Objective.Cmp(rat(36, 1)) != 0 {
		t.Fatalf("objective %s", rep.Objective.RatString())
	}
	// known shadow prices: 0, 3/2, 1
	want := []*big.Rat{rat(0, 1), rat(3, 2), rat(1, 1)}
	for i, w := range want {
		if rep.Rows[i].Dual.Cmp(w) != 0 {
			t.Errorf("dual of %s = %s want %s", rep.Rows[i].Name, rep.Rows[i].Dual.RatString(), w.RatString())
		}
	}
	// cost ranging of x: stays optimal for c_x in [0, 7.5]; of y: [2, inf)
	x, y := rep.Vars[0], rep.Vars[1]
	if x.CostRange.Lo.Cmp(rat(0, 1)) != 0 || x.CostRange.Hi.Cmp(rat(15, 2)) != 0 {
		t.Errorf("x cost range %v %v", x.CostRange.Lo, x.CostRange.Hi)
	}
	if y.CostRange.Lo.Cmp(rat(2, 1)) != 0 || y.CostRange.Hi != nil {
		t.Errorf("y cost range %v %v", y.CostRange.Lo, y.CostRange.Hi)
	}
	// rhs ranging of the binding row b: 2y <= 12 keeps its shadow price for b in [6, 18]
	if rep.Rows[1].LimitRange.Lo.Cmp(rat(6, 1)) != 0 || rep.Rows[1].LimitRange.Hi.Cmp(rat(18, 1)) != 0 {
		t.Errorf("row b range %v %v", rep.Rows[1].LimitRange.Lo, rep.Rows[1].LimitRange.Hi)
	}
}

// interior picks a rational strictly inside [lo, hi] (nil = infinite), or ok=false for a point interval.
func interior(lo, hi *big.Rat, cur *big.Rat, r *rand.Rand) (*big.Rat, bool) {
	switch {
	case lo != nil && hi != nil:
		if lo.Cmp(hi) == 0 {
			return nil, false
		}
		f := big.NewRat(int64(1+r.Intn(3)), 4) // 1/4..3/4 of the way
		d := new(big.Rat).Sub(hi, lo)
		return new(big.Rat).Add(lo, d.Mul(d, f)), true
	case lo != nil:
		return new(big.Rat).Add(lo, big.NewRat(int64(1+r.Intn(5)), 2)), true
	case hi != nil:
		return new(big.Rat).Sub(hi, big.NewRat(int64(1+r.Intn(5)), 2)), true
	}
	return new(big.Rat).Add(cur, big.NewRat(int64(r.Intn(9)-4), 1)), true
}

// Re-solving with perturbed data inside the reported ranges must follow the
// exact linear predictions of the analysis.
func TestRangesPredictResolves(t *testing.T) {
	r := rand.New(rand.NewSource(31))
	costChecks, rhsChecks := 0, 0
	for it := 0; it < 600; it++ {
		m := randomLP(r)
		rep, err := Analyze(m)
		if err != nil {
			continue
		}
		base := rep.Objective
		// cost ranging
		for j, v := range rep.Vars {
			c, ok := interior(v.CostRange.Lo, v.CostRange.Hi, v.Cost, r)
			if !ok {
				continue
			}
			m2 := m.Clone()
			m2.Vars[j].Obj = c
			got, ok := solveObj(t, m2)
			if !ok {
				t.Fatalf("it %d: perturbed cost of %s to %s inside range %v..%v made the LP non-optimal\n%s", it, v.Name, c.RatString(), v.CostRange.Lo, v.CostRange.Hi, model.Format(m))
			}
			want := new(big.Rat).Add(base, new(big.Rat).Mul(new(big.Rat).Sub(c, v.Cost), v.Value))
			if got.Cmp(want) != 0 {
				t.Fatalf("it %d: cost of %s %s->%s: objective %s want %s (range %v..%v)\n%s", it, v.Name, v.Cost.RatString(), c.RatString(), got.RatString(), want.RatString(), v.CostRange.Lo, v.CostRange.Hi, model.Format(m))
			}
			costChecks++
		}
		// rhs ranging on binding rows
		for i, row := range rep.Rows {
			if row.Binding == "" {
				continue
			}
			var cur *big.Rat
			switch row.Binding {
			case "lower":
				cur = m.Rows[i].Lo
			case "upper":
				cur = m.Rows[i].Hi
			default:
				cur = m.Rows[i].Lo
			}
			lim, ok := interior(row.LimitRange.Lo, row.LimitRange.Hi, cur, r)
			if !ok {
				continue
			}
			m2 := m.Clone()
			switch row.Binding {
			case "lower":
				m2.Rows[i].Lo = lim
			case "upper":
				m2.Rows[i].Hi = lim
			default:
				m2.Rows[i].Lo, m2.Rows[i].Hi = lim, new(big.Rat).Set(lim)
			}
			if m2.Validate() != nil {
				continue
			}
			got, ok := solveObj(t, m2)
			if !ok {
				t.Fatalf("it %d: moving the %s limit of %s to %s (range %v..%v) made the LP non-optimal\n%s", it, row.Binding, row.Name, lim.RatString(), row.LimitRange.Lo, row.LimitRange.Hi, model.Format(m))
			}
			want := new(big.Rat).Add(base, new(big.Rat).Mul(row.Dual, new(big.Rat).Sub(lim, cur)))
			if got.Cmp(want) != 0 {
				t.Fatalf("it %d: limit of %s %s->%s: objective %s want %s (dual %s)\n%s", it, row.Name, cur.RatString(), lim.RatString(), got.RatString(), want.RatString(), row.Dual.RatString(), model.Format(m))
			}
			rhsChecks++
		}
	}
	t.Logf("cost checks %d, rhs checks %d", costChecks, rhsChecks)
	if costChecks < 500 || rhsChecks < 300 {
		t.Fatalf("too few checks: %d/%d", costChecks, rhsChecks)
	}
}

func randomLP(r *rand.Rand) *model.Model {
	n, mm := 2+r.Intn(4), 2+r.Intn(4)
	m := model.New()
	m.Maximize = r.Intn(2) == 0
	for j := 0; j < n; j++ {
		v := m.AddVar("x" + string(rune('a'+j)))
		m.Vars[v].Obj = rat(int64(r.Intn(13)-3), 1)
		m.Vars[v].Hi = rat(int64(2+r.Intn(8)), 1)
	}
	m.ObjConst = rat(int64(r.Intn(5)), 1)
	for i := 0; i < mm; i++ {
		row := model.Row{Name: "r" + string(rune('a'+i))}
		for j := 0; j < n; j++ {
			if c := r.Intn(7) - 2; c != 0 {
				row.Entries = append(row.Entries, model.Entry{J: j, V: rat(int64(c), int64(1+r.Intn(2)))})
			}
		}
		if len(row.Entries) == 0 {
			row.Entries = []model.Entry{{J: 0, V: rat(1, 1)}}
		}
		b := rat(int64(r.Intn(14)), 1)
		switch r.Intn(4) {
		case 0:
			row.Hi = b
		case 1:
			row.Lo = b
		case 2:
			row.Lo, row.Hi = b, new(big.Rat).Set(b)
		default:
			row.Lo, row.Hi = b, new(big.Rat).Add(b, rat(int64(1+r.Intn(8)), 1))
		}
		m.Rows = append(m.Rows, row)
	}
	return m
}

func TestFixIntsAnalysis(t *testing.T) {
	m := parse(t, "Maximize\n o: 5 a + 4 b + 3 c\nSubject To\n w: 2 a + 3 b + c <= 5\n v: 4 a + b + 2 c <= 11\nInteger\n a\nEnd")
	x := []*big.Rat{rat(2, 1), rat(0, 1), rat(0, 1)}
	fixed := FixInts(m, x)
	if fixed.HasInts() {
		t.Fatal("ints not fixed")
	}
	rep, err := Analyze(fixed)
	if err != nil {
		t.Fatal(err)
	}
	if rep.Vars[0].Status == "" || rep.Objective.Sign() <= 0 {
		t.Fatalf("bad report %+v", rep.Vars[0])
	}
}

func TestRefusesNonOptimal(t *testing.T) {
	m := parse(t, "Maximize\n o: x\nSubject To\n c: x - y <= 1\nEnd")
	if _, err := Analyze(m); err == nil {
		t.Fatal("analysed an unbounded LP")
	}
}
