package cas

import (
	"fmt"
	"math"
	"math/big"
	"math/cmplx"
	"sort"
)

// Root is one solution of an equation. Exact is nil when only a numeric value is known
// (irreducible factors of degree >= 3, where radicals are not attempted).
type Root struct {
	Exact  E
	Approx complex128
	Mult   int
	Poly   E // the irreducible factor this root belongs to (for numeric-only roots)
}

func (r Root) String() string {
	if r.Exact != nil {
		return r.Exact.String()
	}
	return fmt.Sprintf("%s  (root of %s)", fmtComplex(r.Approx), r.Poly.String())
}

func fmtComplex(c complex128) string {
	re, im := real(c)+0, imag(c)+0
	if re == 0 {
		re = 0 // normalise -0
	}
	if math.Abs(im) < 1e-12*(1+math.Abs(re)) {
		return fmt.Sprintf("%.10g", re)
	}
	sign := "+"
	if im < 0 {
		sign = "-"
	}
	return fmt.Sprintf("%.10g %s %.10g*i", re, sign, math.Abs(im))
}

// Solve finds the roots of an equation (or expression = 0) in x. It handles polynomial and
// rational equations: exact answers through quadratics (with rational factorisation first),
// and numeric roots for higher-degree irreducible factors.
func Solve(eq E, x string) []Root {
	e := eq
	if eq.K == KFn && eq.S == "eq" {
		e = Sub(eq.A[0], eq.A[1])
	}
	if !Contains(e, x) {
		if isNumVal(e, 0) {
			fail("every value of %s is a solution (the equation is an identity)", x)
		}
		if e.K != KNum {
			fail("the equation does not involve %s", x)
		}
		return nil
	}
	cs, ok := coeffsOf(e, x)
	var den E = One
	if !ok {
		n, d := NumDen(Together(e, x))
		cs, ok = coeffsOf(n, x)
		den = d
		if !ok {
			fail("solve handles polynomial and rational equations in %s", x)
		}
	}
	var roots []Root
	allRat := true
	for _, c := range cs {
		if c.K != KNum {
			allRat = false
		}
	}
	switch {
	case len(cs) == 0:
		fail("every value of %s is a solution (the equation is an identity)", x)
	case len(cs) == 1:
		return nil
	case !allRat:
		roots = symbolicRoots(cs, x)
	default:
		p := make(Poly, len(cs))
		for i, c := range cs {
			p[i] = new(big.Rat).Set(c.N)
		}
		_, fs := FactorPoly(p)
		for _, f := range fs {
			roots = append(roots, rootsOfIrreducible(f.P, f.Mult, x)...)
		}
	}
	if !isNumVal(den, 1) { // discard roots that are poles
		var keep []Root
		for _, r := range roots {
			v := r.Approx
			if r.Exact != nil {
				if val, err := EvalNum(Sub1(den, x, r.Exact), nil); err == nil {
					if cmplx.Abs(val) < 1e-9 {
						continue
					}
				}
			} else if cmplx.Abs(evalAt(den, x, v)) < 1e-9 {
				continue
			}
			keep = append(keep, r)
		}
		roots = keep
	}
	for i := range roots {
		if roots[i].Exact != nil {
			roots[i].Approx, _ = EvalNum(roots[i].Exact, nil)
		}
	}
	sort.SliceStable(roots, func(i, j int) bool {
		a, b := roots[i].Approx, roots[j].Approx
		if math.Abs(real(a)-real(b)) > 1e-9 {
			return real(a) < real(b)
		}
		return imag(a) < imag(b)
	})
	return roots
}

func evalAt(e E, x string, v complex128) complex128 {
	r, err := EvalNum(e, map[string]complex128{x: v})
	if err != nil {
		return 1
	}
	return r
}

func symbolicRoots(cs []E, x string) []Root {
	switch len(cs) {
	case 2: // c1 x + c0
		return []Root{{Exact: Div(Neg(cs[0]), cs[1]), Mult: 1}}
	case 3:
		a, b, c := cs[2], cs[1], cs[0]
		disc := Expand(Sub(Mul(b, b), Mul(Int(4), a, c)))
		sq := Sqrt(disc)
		twoA := Mul(Int(2), a)
		r1 := Div(Add(Neg(b), sq), twoA)
		r2 := Div(Sub(Neg(b), sq), twoA)
		if isNumVal(disc, 0) {
			return []Root{{Exact: r1, Mult: 2}}
		}
		return []Root{{Exact: r1, Mult: 1}, {Exact: r2, Mult: 1}}
	}
	fail("symbolic coefficients are supported up to degree 2")
	return nil
}

func rootsOfIrreducible(p Poly, mult int, x string) []Root {
	switch p.Deg() {
	case 1: // a x + b
		r := new(big.Rat).Neg(new(big.Rat).Quo(p[0], p[1]))
		return []Root{{Exact: Num(r), Mult: mult}}
	case 2:
		a, b, c := Num(p[2]), Num(p[1]), Num(p[0])
		disc := Sub(Mul(b, b), Mul(Int(4), a, c))
		sq := Sqrt(disc)
		twoA := Mul(Int(2), a)
		return []Root{
			{Exact: Div(Add(Neg(b), sq), twoA), Mult: mult},
			{Exact: Div(Sub(Neg(b), sq), twoA), Mult: mult},
		}
	}
	if r := powerSubstRoots(p, mult); r != nil {
		return r
	}
	var out []Root
	pe := p.ToExpr(Sym(x))
	for _, z := range NumericRoots(p) {
		out = append(out, Root{Approx: z, Mult: mult, Poly: pe})
	}
	return out
}

// NumericRoots finds all complex roots of p with the Durand–Kerner iteration, polished by Newton.
func NumericRoots(p Poly) []complex128 {
	n := p.Deg()
	if n < 1 {
		return nil
	}
	co := make([]complex128, n+1)
	lead, _ := p.lc().Float64()
	for i := range p {
		f, _ := p[i].Float64()
		co[i] = complex(f/lead, 0)
	}
	eval := func(z complex128) (complex128, complex128) {
		v, d := complex(0, 0), complex(0, 0)
		for i := n; i >= 0; i-- {
			d = d*z + v
			v = v*z + co[i]
		}
		return v, d
	}
	bound := 1.0
	for i := 0; i < n; i++ {
		bound = math.Max(bound, 1+cmplx.Abs(co[i]))
	}
	z := make([]complex128, n)
	for i := range z {
		z[i] = cmplx.Rect(bound/2, 2*math.Pi*float64(i)/float64(n)+0.4)
	}
	for iter := 0; iter < 2000; iter++ {
		moved := 0.0
		for i := range z {
			v, _ := eval(z[i])
			den := complex(1, 0)
			for j := range z {
				if j != i {
					den *= z[i] - z[j]
				}
			}
			if den == 0 {
				den = 1e-12
			}
			dz := v / den
			z[i] -= dz
			moved = math.Max(moved, cmplx.Abs(dz))
		}
		if moved < 1e-15 {
			break
		}
	}
	for i := range z {
		for k := 0; k < 5; k++ {
			v, d := eval(z[i])
			if d == 0 {
				break
			}
			z[i] -= v / d
		}
		if math.Abs(imag(z[i])) < 1e-10*(1+math.Abs(real(z[i]))) {
			z[i] = complex(real(z[i]), 0)
		}
	}
	sort.Slice(z, func(i, j int) bool {
		if math.Abs(real(z[i])-real(z[j])) > 1e-9 {
			return real(z[i]) < real(z[j])
		}
		return imag(z[i]) < imag(z[j])
	})
	return z
}

// powerSubstRoots solves p(x) = q(x^k) with deg q <= 2 exactly: x = y^(1/k) * (k-th roots of unity),
// where y runs over the roots of q. It returns nil when the pattern or the exact unity roots are unavailable.
func powerSubstRoots(p Poly, mult int) []Root {
	g := 0
	for i, c := range p {
		if c.Sign() != 0 && i > 0 {
			g = gcdInt(g, i)
		}
	}
	if g < 2 || p.Deg()/g > 2 {
		return nil
	}
	q := make(Poly, p.Deg()/g+1)
	for i := range q {
		q[i] = new(big.Rat).Set(p[i*g])
	}
	var out []Root
	for _, yr := range rootsOfIrreducible(q, mult, "y") {
		if yr.Exact == nil {
			return nil
		}
		base := Pow(yr.Exact, Frac(1, int64(g)))
		for j := 0; j < g; j++ {
			w := Exp(Mul(Frac(2*int64(j), int64(g)), I, Pi))
			if w.K == KFn { // unity root not expressible exactly
				return nil
			}
			out = append(out, Root{Exact: Mul(base, w), Mult: yr.Mult})
		}
	}
	return out
}

func gcdInt(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}
