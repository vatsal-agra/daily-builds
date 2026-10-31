package cas

import (
	"fmt"
	"math"
	"math/big"
	"math/rand"
	"testing"
)

func randExpr(r *rand.Rand, depth int, fns bool) E {
	if depth == 0 || r.Intn(5) == 0 {
		switch r.Intn(4) {
		case 0:
			return Sym("x")
		case 1:
			return Sym("y")
		default:
			return Int(int64(r.Intn(9) - 4))
		}
	}
	a := randExpr(r, depth-1, fns)
	b := randExpr(r, depth-1, fns)
	switch r.Intn(7) {
	case 0, 1:
		return Add(a, b)
	case 2, 3:
		return Mul(a, b)
	case 4:
		return Pow(a, Int(int64(r.Intn(3)+2)))
	case 5:
		if fns {
			return Fn([]string{"sin", "cos", "exp", "atan"}[r.Intn(4)], a)
		}
		return Sub(a, b)
	default:
		if fns {
			return Div(a, Add(Mul(b, b), One))
		}
		return Neg(a)
	}
}

func TestPrintParseRoundTrip(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	for i := 0; i < 3000; i++ {
		e := randExpr(r, 4, true)
		s := e.String()
		p, err := Parse(s)
		if err != nil {
			t.Fatalf("cannot re-parse %q: %v", s, err)
		}
		if !Equal(p, e) {
			t.Fatalf("round trip changed %q\n  key before %s\n  key after  %s", s, e.Key(), p.Key())
		}
	}
}

func TestCommutativityAndIdempotence(t *testing.T) {
	r := rand.New(rand.NewSource(2))
	for i := 0; i < 2000; i++ {
		a, b := randExpr(r, 3, true), randExpr(r, 3, true)
		if !Equal(Add(a, b), Add(b, a)) || !Equal(Mul(a, b), Mul(b, a)) {
			t.Fatalf("not commutative: %s , %s", a, b)
		}
		e := Add(a, Mul(b, b))
		if !Equal(rebuild(e, e.A), e) {
			t.Fatalf("rebuild is not idempotent for %s", e)
		}
	}
}

func numEq(t *testing.T, a, b E, vars map[string]float64, what string) bool {
	t.Helper()
	x, e1 := EvalReal(a, vars)
	y, e2 := EvalReal(b, vars)
	if e1 != nil || e2 != nil || math.IsNaN(x) || math.IsNaN(y) || math.IsInf(x, 0) || math.IsInf(y, 0) {
		return true // outside the real domain: nothing to compare
	}
	if math.Abs(x-y) > 1e-8*(1+math.Abs(x)+math.Abs(y)) {
		t.Errorf("%s: %s = %g but %s = %g at %v", what, a, x, b, y, vars)
		return false
	}
	return true
}

func TestExpandPreservesValue(t *testing.T) {
	r := rand.New(rand.NewSource(3))
	for i := 0; i < 1500; i++ {
		e := randExpr(r, 4, false)
		ex := Expand(e)
		env := map[string]float64{"x": 0.5 + r.Float64()*2, "y": 0.5 + r.Float64()*2}
		if !numEq(t, e, ex, env, "expand") {
			return
		}
		if !Equal(Expand(ex), ex) {
			t.Fatalf("expand not idempotent on %s", e)
		}
	}
}

func TestSubstitutionMatchesEvaluation(t *testing.T) {
	r := rand.New(rand.NewSource(4))
	for i := 0; i < 1500; i++ {
		e := randExpr(r, 4, true)
		xv := math.Round((0.3+r.Float64()*2)*8) / 8
		sub := Sub1(e, "x", Num(new(big.Rat).SetFloat64(xv)))
		env := map[string]float64{"x": xv, "y": 1.3}
		if !numEq(t, e, sub, env, "subst") {
			return
		}
	}
}

func TestDiffAgainstFiniteDifferences(t *testing.T) {
	r := rand.New(rand.NewSource(5))
	checked := 0
	for i := 0; i < 2500; i++ {
		e := randExpr(r, 4, true)
		d := Diff(e, "x")
		x0 := 0.4 + r.Float64()*1.2
		h := 1e-5
		f := func(x float64) (float64, bool) {
			v, err := EvalReal(e, map[string]float64{"x": x, "y": 0.9})
			return v, err == nil && !math.IsNaN(v) && !math.IsInf(v, 0)
		}
		p, ok1 := f(x0 + h)
		m, ok2 := f(x0 - h)
		dv, err := EvalReal(d, map[string]float64{"x": x0, "y": 0.9})
		if !ok1 || !ok2 || err != nil {
			continue
		}
		num := (p - m) / (2 * h)
		if v0, ok0 := f(x0); !ok0 || math.Abs(num) > 1e3 || math.Abs(v0) > 1e5 {
			continue
		}
		checked++
		if math.Abs(num-dv) > 1e-4*(1+math.Abs(num)) {
			t.Fatalf("d/dx %s: symbolic %g vs numeric %g at x=%g\n  derivative: %s", e, dv, num, x0, d)
		}
	}
	if checked < 1500 {
		t.Fatalf("only %d usable samples", checked)
	}
}

func TestMatrixLaws(t *testing.T) {
	r := rand.New(rand.NewSource(6))
	for i := 0; i < 200; i++ {
		n := 2 + r.Intn(3)
		cells := make([]E, n*n)
		for k := range cells {
			cells[k] = Int(int64(r.Intn(9) - 4))
		}
		m := NewMat(n, n, cells)
		// det against cofactor expansion
		if !Equal(Det(m), Expand(cofactorDet(m))) {
			t.Fatalf("det mismatch for %s", m)
		}
		if !isNumVal(Det(m), 0) {
			inv := Inverse(m)
			if !Equal(matMul2(m, inv), Identity(n)) || !Equal(matMul2(inv, m), Identity(n)) {
				t.Fatalf("inverse is wrong for %s", m)
			}
		} else if Rank(m) == n {
			t.Fatalf("rank should drop for singular %s", m)
		}
		// Cayley–Hamilton: the characteristic polynomial annihilates the matrix
		cp := CharPoly(m, "t")
		cs, _ := coeffsOf(cp, "t")
		acc := mapMat(Identity(n), func(E) E { return Zero })
		pw := Identity(n)
		for k := 0; k < len(cs); k++ {
			acc = matAddAll([]E{acc, matMul2(cs[k], pw)})
			pw = matMul2(pw, m)
		}
		if !Equal(acc, mapMat(Identity(n), func(E) E { return Zero })) {
			t.Fatalf("Cayley–Hamilton fails for %s: %s", m, acc)
		}
		// null space vectors are annihilated
		for _, v := range Nullspace(m) {
			if !Equal(matMul2(m, v), mapMat(v, func(E) E { return Zero })) {
				t.Fatalf("nullspace vector wrong for %s", m)
			}
		}
	}
}

func TestLinearSolveRandom(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	for i := 0; i < 100; i++ {
		n := 2 + r.Intn(3)
		cells := make([]E, n*n)
		for k := range cells {
			cells[k] = Int(int64(r.Intn(11) - 5))
		}
		A := NewMat(n, n, cells)
		if isNumVal(Det(A), 0) {
			continue
		}
		xs := make([]E, n)
		for k := range xs {
			xs[k] = Frac(int64(r.Intn(9)-4), int64(1+r.Intn(3)))
		}
		x := NewMat(n, 1, xs)
		b := matMul2(A, x)
		got := SolveLinear(A, b)
		if !Equal(got, x) {
			t.Fatalf("solve returned %s, want %s", got, x)
		}
	}
}

func TestSolveRootsSatisfyEquation(t *testing.T) {
	r := rand.New(rand.NewSource(8))
	for i := 0; i < 300; i++ {
		deg := 1 + r.Intn(6)
		cs := make([]E, deg+1)
		for k := range cs {
			cs[k] = Int(int64(r.Intn(13) - 6))
		}
		if isNumVal(cs[deg], 0) {
			cs[deg] = One
		}
		var ts []E
		for k, c := range cs {
			ts = append(ts, Mul(c, Pow(Sym("x"), Int(int64(k)))))
		}
		p := Add(ts...)
		roots := Solve(p, "x")
		total := 0
		for _, rt := range roots {
			total += rt.Mult
			v, err := EvalNum(p, map[string]complex128{"x": rt.Approx})
			if err != nil || abs2(v) > 1e-6*float64(1+10*deg) {
				t.Fatalf("root %s of %s gives p = %v", rt, p, v)
			}
		}
		if total != deg {
			t.Fatalf("%s: found %d roots with multiplicity, want %d", p, total, deg)
		}
	}
}

func abs2(c complex128) float64 { return math.Hypot(real(c), imag(c)) }

func TestApartRecombines(t *testing.T) {
	cases := []string{"1/(x^2-1)", "(x^3+2x)/(x^2+1)^2", "(x+5)/(x*(x+1)*(x-2))", "1/(x^2*(x+1)^2)", "x^4/(x^2+x+1)", "(2x+3)/(x^2+4x+5)^2", "7/(x^3-x)"}
	for _, c := range cases {
		e := MustParse(c)
		ap := Apart(e, "x")
		if !numericallyEqual(e, ap) {
			t.Errorf("apart(%s) = %s does not recombine", c, ap)
		}
	}
}

func TestCyclotomicFactorDegrees(t *testing.T) {
	phi := func(n int) int {
		c := 0
		for k := 1; k <= n; k++ {
			if gcdInt(k, n) == 1 {
				c++
			}
		}
		return c
	}
	for n := 2; n <= 40; n++ {
		p := make(Poly, n+1)
		for i := range p {
			p[i] = new(big.Rat)
		}
		p[0].SetInt64(-1)
		p[n].SetInt64(1)
		_, fs := FactorPoly(p)
		var got []int
		for _, f := range fs {
			if f.Mult != 1 {
				t.Fatalf("x^%d-1 has repeated factor", n)
			}
			got = append(got, f.P.Deg())
		}
		var want []int
		for d := 1; d <= n; d++ {
			if n%d == 0 {
				want = append(want, phi(d))
			}
		}
		if fmt.Sprint(sortedInts(got)) != fmt.Sprint(sortedInts(want)) {
			t.Fatalf("x^%d-1: factor degrees %v, want %v", n, got, want)
		}
	}
}

func sortedInts(a []int) []int {
	b := append([]int{}, a...)
	for i := range b {
		for j := i + 1; j < len(b); j++ {
			if b[j] < b[i] {
				b[i], b[j] = b[j], b[i]
			}
		}
	}
	return b
}

func randPoly(r *rand.Rand, deg, span int) Poly {
	p := make(Poly, deg+1)
	for i := range p {
		p[i] = big.NewRat(int64(r.Intn(2*span+1)-span), 1)
	}
	if p[deg].Sign() == 0 {
		p[deg].SetInt64(1)
	}
	return trim(p)
}

func TestFactorMultipliesBackAndMatchesKronecker(t *testing.T) {
	r := rand.New(rand.NewSource(9))
	for i := 0; i < 400; i++ {
		// product of 1..3 random polynomials, so reducibility is guaranteed to vary
		p := Poly{big.NewRat(1, 1)}
		for k := 0; k < 1+r.Intn(3); k++ {
			p = pMul(p, randPoly(r, 1+r.Intn(3), 4))
		}
		content, fs := FactorPoly(p)
		back := pconst(content)
		for _, f := range fs {
			if f.P.Deg() < 1 {
				t.Fatalf("degenerate factor in %v", fs)
			}
			back = pMul(back, pPow(f.P, f.Mult))
		}
		if !pEqual(back, p) {
			t.Fatalf("factors do not multiply back for %s", p.ToExpr(Sym("x")))
		}
		// independence: every reported factor must be irreducible according to the Kronecker oracle
		for _, f := range fs {
			if f.P.Deg() >= 4 {
				lin, _ := stripRationalRoots(f.P)
				if len(lin) > 0 || kronecker(f.P) != nil {
					t.Fatalf("factor %s of %s is reducible", f.P.ToExpr(Sym("x")), p.ToExpr(Sym("x")))
				}
			}
		}
	}
}

func TestZassenhausMatchesKroneckerOnHardOnes(t *testing.T) {
	r := rand.New(rand.NewSource(10))
	for i := 0; i < 60; i++ {
		deg := 4 + r.Intn(4)
		p := randPoly(r, deg, 3)
		_, prim := primitiveInt(p)
		if len(squareFree(prim)) != 1 || squareFree(prim)[0].Mult != 1 {
			continue
		}
		if lin, rest := stripRationalRoots(prim); len(lin) > 0 {
			prim = rest
			if prim.Deg() < 4 {
				continue
			}
		}
		z := zassenhaus(prim)
		prod := Poly{big.NewRat(1, 1)}
		for _, f := range z {
			prod = pMul(prod, f)
		}
		if !pEqual(prod, prim) {
			t.Fatalf("zassenhaus factors do not multiply back: %s", prim.ToExpr(Sym("x")))
		}
		// brute force: Kronecker must find no further split of any piece
		for _, f := range z {
			if f.Deg() >= 4 && f.Deg() <= 6 && kronecker(f) != nil {
				t.Fatalf("zassenhaus left %s reducible", f.ToExpr(Sym("x")))
			}
		}
	}
}
