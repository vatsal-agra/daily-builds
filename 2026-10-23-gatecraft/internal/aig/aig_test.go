package aig_test

import (
	"math/rand"
	"testing"

	"gatecraft/internal/aig"
)

// truth table of a literal over the first n inputs (n <= 6), as a 64-bit word.
func truth(g *aig.AIG, l aig.Lit, n int) uint64 {
	s := aig.NewSimulator(g)
	for i := 0; i < n; i++ {
		var w uint64
		for m := 0; m < 64; m++ {
			if m>>uint(i)&1 == 1 {
				w |= 1 << uint(m)
			}
		}
		s.SetPI(i, w)
	}
	s.Eval()
	return s.Lit(l)
}

func inputs(g *aig.AIG, n int) []aig.Lit {
	var ls []aig.Lit
	for i := 0; i < n; i++ {
		ls = append(ls, g.AddInput("x", i))
	}
	return ls
}

func TestStrashAndConstantFolding(t *testing.T) {
	g := aig.New()
	a, b := g.AddInput("a", 0), g.AddInput("b", 0)
	if g.And(a, b) != g.And(b, a) {
		t.Fatal("And must be commutative under structural hashing")
	}
	if g.And(a, aig.True) != a || g.And(a, aig.False) != aig.False || g.And(a, a) != a || g.And(a, a.Not()) != aig.False {
		t.Fatal("constant / idempotence / contradiction rules")
	}
	n := len(g.Nodes)
	g.And(a, b)
	if len(g.Nodes) != n {
		t.Fatal("re-building an existing gate must not allocate")
	}
	if g.Xor(a, b) != g.Xor(b, a) || g.Mux(aig.True, a, b) != a || g.Mux(aig.False, a, b) != b || g.Mux(a, b, b) != b {
		t.Fatal("xor / mux simplifications")
	}
}

// Two-level rewriting rules must never change the function: compare against plain construction.
func TestTwoLevelRewriteRulesPreserveFunctions(t *testing.T) {
	for seed := int64(0); seed < 300; seed++ {
		rng := rand.New(rand.NewSource(seed))
		plain, rw := aig.New(), aig.New()
		rw.Rewrite = true
		const n = 5
		pp, rr := inputs(plain, n), inputs(rw, n)
		var ps, rs []aig.Lit
		ps, rs = append(ps, pp...), append(rs, rr...)
		for i := 0; i < 40; i++ {
			x, y := rng.Intn(len(ps)), rng.Intn(len(ps))
			nx, ny := rng.Intn(2) == 0, rng.Intn(2) == 0
			ps = append(ps, plain.And(ps[x].NotIf(nx), ps[y].NotIf(ny)))
			rs = append(rs, rw.And(rs[x].NotIf(nx), rs[y].NotIf(ny)))
		}
		for i := range ps {
			if truth(plain, ps[i], n) != truth(rw, rs[i], n) {
				t.Fatalf("seed %d: rewriting changed node %d", seed, i)
			}
		}
	}
}

func TestBitVectorHelpersMatchIntegerArithmetic(t *testing.T) {
	g := aig.New()
	const w = 4
	var av, bv []aig.Lit
	for i := 0; i < w; i++ {
		av = append(av, g.AddInput("a", i))
	}
	for i := 0; i < w; i++ {
		bv = append(bv, g.AddInput("b", i))
	}
	sum, carry := g.AddC(av, bv, aig.False)
	diff, noBorrow := g.SubV(av, bv)
	prod := g.MulV(av, bv)
	q, r := g.DivModV(av, bv)
	lt, eq := g.LtV(av, bv), g.EqV(av, bv)
	shl, shr := g.ShiftV(av, bv, true), g.ShiftV(av, bv, false)
	s := aig.NewSimulator(g)
	for m := 0; m < 256; m++ {
		for i := 0; i < 8; i++ {
			if m>>uint(i)&1 == 1 {
				s.SetPI(i, ^uint64(0))
			} else {
				s.SetPI(i, 0)
			}
		}
		s.Eval()
		val := func(ls []aig.Lit) int {
			v := 0
			for i, l := range ls {
				if s.Lit(l)&1 == 1 {
					v |= 1 << uint(i)
				}
			}
			return v
		}
		a, b := m&15, m>>4
		check := func(name string, got, want int) {
			if got != want {
				t.Fatalf("a=%d b=%d: %s = %d, want %d", a, b, name, got, want)
			}
		}
		check("add", val(sum), (a+b)&15)
		check("carry", int(s.Lit(carry)&1), (a+b)>>4)
		check("sub", val(diff), (a-b)&15)
		check("noborrow", int(s.Lit(noBorrow)&1), map[bool]int{true: 1, false: 0}[a >= b])
		check("mul", val(prod), (a*b)&15)
		if b == 0 {
			check("div0 quotient", val(q), 15)
			check("div0 remainder", val(r), a)
		} else {
			check("div", val(q), a/b)
			check("rem", val(r), a%b)
		}
		check("lt", int(s.Lit(lt)&1), map[bool]int{true: 1, false: 0}[a < b])
		check("eq", int(s.Lit(eq)&1), map[bool]int{true: 1, false: 0}[a == b])
		wantShl, wantShr := 0, 0
		if b < 4 {
			wantShl, wantShr = (a<<uint(b))&15, a>>uint(b)
		}
		check("shl", val(shl), wantShl)
		check("shr", val(shr), wantShr)
	}
}

func TestSequentialSimulation(t *testing.T) {
	g := aig.New()
	en := g.AddInput("en", 0)
	q := g.AddLatch("t", false)
	g.Latches[0].Clock = "clk"
	g.Latches[0].D = g.Xor(q, en) // toggle flop
	g.Inputs = []aig.Port{{Name: "en", Bits: []aig.Lit{en}}}
	g.Outputs = []aig.Port{{Name: "q", Bits: []aig.Lit{q}}}
	s := aig.NewSimulator(g)
	var seq []uint64
	for i, e := range []uint64{1, 1, 0, 1, 1, 1} {
		s.SetPI(0, e*^uint64(0))
		s.Eval()
		seq = append(seq, s.Lit(q)&1)
		s.Clock(nil)
		_ = i
	}
	want := []uint64{0, 1, 0, 0, 1, 0}
	for i := range want {
		if seq[i] != want[i] {
			t.Fatalf("toggle sequence %v, want %v", seq, want)
		}
	}
	s.Reset()
	s.Eval()
	if s.Lit(q)&1 != 0 {
		t.Fatal("Reset must restore init values")
	}
}

func TestBalanceFlattensAndChains(t *testing.T) {
	g := aig.New()
	var xs []aig.Lit
	for i := 0; i < 16; i++ {
		xs = append(xs, g.AddInput("x", i))
	}
	acc := xs[0]
	for _, x := range xs[1:] {
		acc = g.And(acc, x) // a 15-deep chain
	}
	g.Inputs = []aig.Port{{Name: "x", Bits: xs}}
	g.Outputs = []aig.Port{{Name: "y", Bits: []aig.Lit{acc}}}
	if g.Depth() != 15 {
		t.Fatalf("chain depth %d", g.Depth())
	}
	b := aig.Balance(g)
	if b.Depth() != 4 || b.NumAnds() != 15 {
		t.Fatalf("balanced: depth %d ands %d, want 4 / 15", b.Depth(), b.NumAnds())
	}
}

func TestSweepDropsDeadLogicAndRegisters(t *testing.T) {
	g := aig.New()
	a, b := g.AddInput("a", 0), g.AddInput("b", 0)
	g.Inputs = []aig.Port{{Name: "a", Bits: []aig.Lit{a}}, {Name: "b", Bits: []aig.Lit{b}}}
	live := g.AddLatch("live", false)
	dead := g.AddLatch("dead", false)
	g.Latches[0].D, g.Latches[1].D = g.Xor(live, a), g.Xor(dead, b)
	g.Latches[0].Clock, g.Latches[1].Clock = "clk", "clk"
	g.And(a, b) // unused logic
	g.Outputs = []aig.Port{{Name: "y", Bits: []aig.Lit{live}}}
	s := aig.Sweep(g)
	if len(s.Latches) != 1 || s.Latches[0].Name != "live" || s.Removed["dead"] != "dead" {
		t.Fatalf("latches %v removed %v", s.Latches, s.Removed)
	}
	if s.NumAnds() != 3 { // only the xor feeding the live register
		t.Fatalf("expected 3 ANDs (one xor), got %d", s.NumAnds())
	}
}

func TestFraigMergesDifferentlyBuiltEquivalents(t *testing.T) {
	g := aig.New()
	xs := inputs(g, 4)
	// f = (a&b)&(c&d), h = ((a&c)&b)&d  — same function, different structure; plus !(!f)
	f := g.And(g.And(xs[0], xs[1]), g.And(xs[2], xs[3]))
	h := g.And(g.And(g.And(xs[0], xs[2]), xs[1]), xs[3])
	x := g.Xor(f, h) // identically 0 once f and h merge
	g.Inputs = []aig.Port{{Name: "x", Bits: xs}}
	g.Outputs = []aig.Port{{Name: "y", Bits: []aig.Lit{x, f}}}
	o, st := aig.Fraig(g, 1)
	if st.Proved == 0 {
		t.Fatalf("no merge proved: %+v", st)
	}
	if o.Outputs[0].Bits[0] != aig.False {
		t.Fatalf("xor of equal functions should fold to constant 0, got %v", o.Outputs[0].Bits[0])
	}
	if o.NumAnds() >= g.NumAnds() {
		t.Fatalf("%d -> %d", g.NumAnds(), o.NumAnds())
	}
}

func TestSeqCleanConstantDuplicateAndChains(t *testing.T) {
	g := aig.New()
	x := g.AddInput("x", 0)
	g.Inputs = []aig.Port{{Name: "x", Bits: []aig.Lit{x}}}
	mk := func(name string, init bool) aig.Lit {
		q := g.AddLatch(name, init)
		g.Latches[len(g.Latches)-1].Clock = "clk"
		return q
	}
	c0 := mk("stuck0", false) // D = Q & x  -> stays 0
	c1 := mk("stuck1", true)  // D = Q | x  -> stays 1
	a := mk("a", false)
	b := mk("b", false) // twin of a
	c := mk("c", false) // twin of b (chain of duplicates)
	g.Latches[0].D = g.And(c0, x)
	g.Latches[1].D = g.Or(c1, x)
	g.Latches[2].D = g.Xor(a, x)
	g.Latches[3].D = g.Xor(b, x)
	g.Latches[4].D = g.Xor(c, x)
	g.Outputs = []aig.Port{{Name: "y", Bits: []aig.Lit{g.Xor(a, g.Xor(b, g.Xor(c, g.And(c0, c1)))), c1}}}
	o, removed := aig.SeqClean(g)
	if removed != 4 || len(o.Latches) != 1 {
		t.Fatalf("want only register a left (removed 4), got %d latches, removed=%d %v", len(o.Latches), removed, o.Removed)
	}
	if o.Removed["stuck0"] != "0" || o.Removed["stuck1"] != "1" || o.Removed["b"] != "a" || o.Removed["c"] != "a" {
		t.Fatalf("removal record %v", o.Removed)
	}
}

func TestStatsAndCriticalPath(t *testing.T) {
	g := aig.New()
	xs := inputs(g, 4)
	g.Inputs = []aig.Port{{Name: "x", Bits: xs}}
	y := g.And(g.And(g.And(xs[0], xs[1]), xs[2]), xs[3])
	g.Outputs = []aig.Port{{Name: "y", Bits: []aig.Lit{y}}}
	st := g.Stats()
	if st.Ands != 3 || st.Depth != 3 || st.InputBits != 4 || st.OutputBits != 1 {
		t.Fatalf("%+v", st)
	}
	p := g.CriticalPath()
	if p.Depth != 3 || len(p.Steps) != 4 || p.Steps[0].Label != "x[0]" && p.Steps[0].Label != "x[1]" {
		t.Fatalf("%+v", p)
	}
}
