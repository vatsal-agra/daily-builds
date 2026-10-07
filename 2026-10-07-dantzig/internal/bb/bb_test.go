package bb

import (
	"math/big"
	"math/rand"
	"strings"
	"testing"

	"dantzig/internal/exact"
	"dantzig/internal/model"
)

func parse(t *testing.T, s string) *model.Model {
	t.Helper()
	m, err := model.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

// randomIP builds a small bounded integer program (some continuous vars).
func randomIP(r *rand.Rand, n, mm int) *model.Model {
	m := model.New()
	for j := 0; j < n; j++ {
		v := m.AddVar("x" + string(rune('a'+j)))
		m.Vars[v].Int = r.Intn(5) > 0
		m.Vars[v].Lo = big.NewRat(int64(-2+r.Intn(3)), 1)
		m.Vars[v].Hi = new(big.Rat).Add(m.Vars[v].Lo, big.NewRat(int64(1+r.Intn(4)), 1))
		m.Vars[v].Obj = big.NewRat(int64(r.Intn(15)-5), 1)
	}
	m.Maximize = r.Intn(2) == 0
	for i := 0; i < mm; i++ {
		row := model.Row{Name: "r" + string(rune('a'+i))}
		for j := 0; j < n; j++ {
			if c := r.Intn(9) - 3; c != 0 && r.Intn(3) > 0 {
				row.Entries = append(row.Entries, model.Entry{J: j, V: big.NewRat(int64(c), 1)})
			}
		}
		if len(row.Entries) == 0 {
			row.Entries = []model.Entry{{J: 0, V: big.NewRat(1, 1)}}
		}
		b := big.NewRat(int64(r.Intn(15)-3), 1)
		switch r.Intn(3) {
		case 0:
			row.Hi = b
		case 1:
			row.Lo = b
		default:
			row.Lo = b
			row.Hi = new(big.Rat).Add(b, big.NewRat(int64(r.Intn(6)), 1))
		}
		m.Rows = append(m.Rows, row)
	}
	return m
}

// brute enumerates integer vars; continuous vars are optimised by an exact LP
// with the integers fixed (via the same machinery on a fixed copy).
func brute(t *testing.T, m *model.Model) (best *big.Rat, feasible bool) {
	var ints []int
	for j, v := range m.Vars {
		if v.Int {
			ints = append(ints, j)
		}
	}
	cur := make([]int64, len(ints))
	var rec func(k int)
	rec = func(k int) {
		if k == len(ints) {
			c := m.Clone()
			for i, j := range ints {
				c.Vars[j].Lo = big.NewRat(cur[i], 1)
				c.Vars[j].Hi = big.NewRat(cur[i], 1)
				c.Vars[j].Int = false
			}
			// continuous remainder: solve with plain LP (certified inside)
			res := Solve(c, Options{NoDive: true})
			if res.Status == Optimal {
				v := new(big.Rat).Sub(res.Obj, c.ObjConst)
				v.Mul(v, big.NewRat(1, 1))
				if m.Maximize {
					v.Neg(v)
				}
				if best == nil || v.Cmp(best) < 0 {
					best = v
				}
			}
			return
		}
		j := ints[k]
		lo, hi := m.Vars[j].Lo, m.Vars[j].Hi
		for v := lo.Num().Int64(); v <= hi.Num().Int64(); v++ {
			cur[k] = v
			rec(k + 1)
		}
	}
	rec(0)
	return best, best != nil
}

func TestRandomMIPAgainstBruteForce(t *testing.T) {
	r := rand.New(rand.NewSource(2024))
	opt, inf := 0, 0
	for it := 0; it < 400; it++ {
		m := randomIP(r, 2+r.Intn(4), 1+r.Intn(4))
		want, feas := brute(t, m)
		for _, rule := range []string{"pseudo", "mostfrac"} {
			res := Solve(m, Options{Branch: rule})
			if !res.Certified {
				t.Fatalf("it %d rule %s: not certified (%s / %s)\n%s", it, rule, res.Status, res.Note, model.Format(m))
			}
			rep, err := Check(m, res.Proof)
			if err != nil || !rep.Complete {
				t.Fatalf("it %d: independent check failed: %v\n%s", it, err, model.Format(m))
			}
			if feas != (res.Status == Optimal) {
				t.Fatalf("it %d rule %s: feasibility mismatch brute=%v solver=%s\n%s", it, rule, feas, res.Status, model.Format(m))
			}
			if feas {
				if res.Status != Optimal {
					t.Fatal("status")
				}
				got := new(big.Rat).Sub(res.Obj, m.ObjConst)
				if m.Maximize {
					got.Neg(got)
				}
				if got.Cmp(want) != 0 {
					t.Fatalf("it %d rule %s: objective %s want %s\n%s", it, rule, got.RatString(), want.RatString(), model.Format(m))
				}
			}
		}
		if feas {
			opt++
		} else {
			inf++
		}
	}
	t.Logf("optimal %d, infeasible %d", opt, inf)
	if opt < 150 || inf < 20 {
		t.Fatalf("generator unbalanced: %d/%d", opt, inf)
	}
}

func TestProofTamperingIsRejected(t *testing.T) {
	m := parse(t, `
Maximize
 v: 10 a + 13 b + 7 c + 8 d + 12 e + 4 f
Subject To
 w: 5 a + 8 b + 3 c + 4 d + 7 e + 2 f <= 15
Binary
 a b c d e f
End`)
	res := Solve(m, Options{})
	if res.Status != Optimal || !res.Certified {
		t.Fatal("setup")
	}
	good, _ := MarshalProof(res.Proof)
	if _, err := Check(m, mustUnmarshal(t, good)); err != nil {
		t.Fatal(err)
	}
	// 1. a worse "optimal" solution must be rejected (a leaf bound exceeds it)
	p := mustUnmarshal(t, good)
	p.X = []string{"1", "0", "0", "0", "0", "0"}
	p.Objective = "10"
	if _, err := Check(m, p); err == nil {
		t.Fatal("accepted a suboptimal incumbent")
	}
	// 2. an infeasible incumbent
	p = mustUnmarshal(t, good)
	p.X = []string{"1", "1", "1", "1", "1", "1"}
	p.Objective = "54"
	if _, err := Check(m, p); err == nil {
		t.Fatal("accepted an infeasible incumbent")
	}
	// 3. a wrong claimed objective
	p = mustUnmarshal(t, good)
	p.Objective = "30"
	if _, err := Check(m, p); err == nil {
		t.Fatal("accepted a wrong objective claim")
	}
	// 4. perturbed multipliers in a leaf
	p = mustUnmarshal(t, good)
	if !corruptFirstLeaf(p) {
		t.Fatal("no leaf to corrupt")
	}
	if _, err := Check(m, p); err == nil {
		t.Fatal("accepted corrupted leaf multipliers")
	}
	// 5. dropping a subtree (pruning without proof)
	p = mustUnmarshal(t, good)
	if p.Nodes[0].Var != nil {
		d := p.Nodes[0].Down
		p.Nodes[d] = FlatNode{Leaf: "bound", Y: []string{"0"}}
		if _, err := Check(m, p); err == nil {
			t.Fatal("accepted a replaced subtree")
		}
	}
	// 6. different model
	other := parse(t, strings.Replace(model.Format(m), "<= 15", "<= 16", 1))
	if _, err := Check(other, mustUnmarshal(t, good)); err == nil {
		t.Fatal("accepted a proof for a different model")
	}
}

func mustUnmarshal(t *testing.T, b []byte) *Proof {
	p, err := UnmarshalProof(b)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func corruptFirstLeaf(p *Proof) bool {
	for i := range p.Nodes {
		n := &p.Nodes[i]
		if n.Var == nil && n.Leaf == "bound" && len(n.Y) > 0 {
			n.Y[0] = "1000"
			return true
		}
	}
	return false
}

func TestInfeasibleAndUnboundedMIP(t *testing.T) {
	// LP feasible but no integer point: 2x = 1
	m := parse(t, "Minimize\n o: x\nSubject To\n c: 2 x = 1\nInteger\n x\nEnd")
	res := Solve(m, Options{})
	if res.Status != Infeasible || !res.Certified {
		t.Fatalf("%s %v %s", res.Status, res.Certified, res.Note)
	}
	if _, err := Check(m, res.Proof); err != nil {
		t.Fatal(err)
	}
	m = parse(t, "Maximize\n o: x + y\nSubject To\n c: x - y <= 2\nInteger\n x\nEnd")
	res = Solve(m, Options{})
	if res.Status != Unbounded || !res.Certified {
		t.Fatalf("%s %v %s", res.Status, res.Certified, res.Note)
	}
	if _, err := Check(m, res.Proof); err != nil {
		t.Fatal(err)
	}
	// relaxation unbounded but no integer point exists: 3x - 3y = 1 over free integers
	m = parse(t, "Minimize\n o: x\nSubject To\n c: 3 x - 3 y = 1\nBounds\n x free\n y free\nInteger\n x y\nEnd")
	res = Solve(m, Options{})
	if res.Status != Infeasible || !res.Certified {
		t.Fatalf("%s %v %s", res.Status, res.Certified, res.Note)
	}
	if _, err := Check(m, res.Proof); err != nil {
		t.Fatal(err)
	}
	// tampering: a fractional ray must be rejected for a MIP
	m = parse(t, "Maximize\n o: x + y\nSubject To\n c: x - y <= 2\nInteger\n x\nEnd")
	res = Solve(m, Options{})
	p := mustUnmarshal(t, mustMarshal(t, res.Proof))
	p.Ray[0] = "1/2"
	p.Ray[1] = "1/2"
	if _, err := Check(m, p); err == nil {
		t.Fatal("accepted fractional ray on an integer variable")
	}
}

func mustMarshal(t *testing.T, p *Proof) []byte {
	b, err := MarshalProof(p)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestNodeLimitProofIsPartial(t *testing.T) {
	m := parse(t, `
Maximize
 v: 10 a + 13 b + 7 c + 8 d + 12 e + 4 f
Subject To
 w: 5 a + 8 b + 3 c + 4 d + 7 e + 2 f <= 15
Binary
 a b c d e f
End`)
	res := Solve(m, Options{NodeLimit: 1, NoDive: true})
	if res.Status != Limit {
		t.Fatalf("status %s", res.Status)
	}
	rep, err := Check(m, res.Proof)
	if err != nil {
		t.Fatal(err)
	}
	if rep.Complete || rep.OpenLeaves == 0 {
		t.Fatal("expected open leaves")
	}
	if rep.GlobalBound == nil {
		t.Fatal("open leaves should still carry a proven bound")
	}
	// the proven bound must be >= the true optimum 29 (max problem) and <= root LP 30.71
	if rep.GlobalBound.Cmp(big.NewRat(29, 1)) < 0 || rep.GlobalBound.Cmp(big.NewRat(31, 1)) > 0 {
		t.Fatalf("bound %s", rep.GlobalBound.RatString())
	}
	_ = exact.Basic
}
