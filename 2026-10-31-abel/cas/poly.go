package cas

import (
	"math/big"
	"sort"
)

// Poly is a dense univariate polynomial over Q; p[i] is the coefficient of x^i.
// It is always trimmed: the zero polynomial is the empty slice.
type Poly []*big.Rat

func trim(p Poly) Poly {
	for len(p) > 0 && p[len(p)-1].Sign() == 0 {
		p = p[:len(p)-1]
	}
	return p
}

func (p Poly) Deg() int { return len(p) - 1 }

func (p Poly) lc() *big.Rat {
	if len(p) == 0 {
		return new(big.Rat)
	}
	return p[len(p)-1]
}

func pconst(r *big.Rat) Poly { return trim(Poly{new(big.Rat).Set(r)}) }

func pcopy(p Poly) Poly {
	out := make(Poly, len(p))
	for i, c := range p {
		out[i] = new(big.Rat).Set(c)
	}
	return out
}

func pAdd(a, b Poly) Poly {
	n := len(a)
	if len(b) > n {
		n = len(b)
	}
	out := make(Poly, n)
	for i := range out {
		out[i] = new(big.Rat)
		if i < len(a) {
			out[i].Add(out[i], a[i])
		}
		if i < len(b) {
			out[i].Add(out[i], b[i])
		}
	}
	return trim(out)
}

func pScale(a Poly, c *big.Rat) Poly {
	out := make(Poly, len(a))
	for i := range a {
		out[i] = new(big.Rat).Mul(a[i], c)
	}
	return trim(out)
}

func pSub(a, b Poly) Poly { return pAdd(a, pScale(b, big.NewRat(-1, 1))) }

func pMul(a, b Poly) Poly {
	if len(a) == 0 || len(b) == 0 {
		return nil
	}
	out := make(Poly, len(a)+len(b)-1)
	for i := range out {
		out[i] = new(big.Rat)
	}
	for i := range a {
		for j := range b {
			out[i+j].Add(out[i+j], new(big.Rat).Mul(a[i], b[j]))
		}
	}
	return trim(out)
}

func pDivMod(a, b Poly) (q, r Poly) {
	if len(b) == 0 {
		fail("polynomial division by zero")
	}
	r = pcopy(a)
	if len(a) < len(b) {
		return nil, r
	}
	q = make(Poly, len(a)-len(b)+1)
	for i := range q {
		q[i] = new(big.Rat)
	}
	inv := new(big.Rat).Inv(b.lc())
	for len(r) >= len(b) {
		shift := len(r) - len(b)
		f := new(big.Rat).Mul(r.lc(), inv)
		q[shift] = f
		for i := range b {
			r[i+shift] = new(big.Rat).Sub(r[i+shift], new(big.Rat).Mul(f, b[i]))
		}
		r = trim(r[:len(r)-1])
	}
	return trim(q), r
}

func pDeriv(a Poly) Poly {
	if len(a) <= 1 {
		return nil
	}
	out := make(Poly, len(a)-1)
	for i := 1; i < len(a); i++ {
		out[i-1] = new(big.Rat).Mul(a[i], big.NewRat(int64(i), 1))
	}
	return trim(out)
}

func pMonic(a Poly) Poly {
	if len(a) == 0 {
		return a
	}
	return pScale(a, new(big.Rat).Inv(a.lc()))
}

func pGcd(a, b Poly) Poly {
	a, b = pcopy(a), pcopy(b)
	for len(b) > 0 {
		_, r := pDivMod(a, b)
		a, b = b, r
	}
	return pMonic(a)
}

func pEval(p Poly, x *big.Rat) *big.Rat {
	acc := new(big.Rat)
	for i := len(p) - 1; i >= 0; i-- {
		acc.Mul(acc, x)
		acc.Add(acc, p[i])
	}
	return acc
}

func pEqual(a, b Poly) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i].Cmp(b[i]) != 0 {
			return false
		}
	}
	return true
}

func pPow(a Poly, n int) Poly {
	res := Poly{big.NewRat(1, 1)}
	for i := 0; i < n; i++ {
		res = pMul(res, a)
	}
	return res
}

// primitiveInt scales p to a primitive integer polynomial with positive leading
// coefficient and returns the scale factor: p = content * prim.
func primitiveInt(p Poly) (*big.Rat, Poly) {
	if len(p) == 0 {
		return new(big.Rat), nil
	}
	l := big.NewInt(1)
	for _, c := range p {
		d := c.Denom()
		g := new(big.Int).GCD(nil, nil, l, d)
		l.Mul(l, new(big.Int).Quo(d, g))
	}
	g := new(big.Int)
	ints := make([]*big.Int, len(p))
	for i, c := range p {
		ints[i] = new(big.Int).Mul(c.Num(), new(big.Int).Quo(l, c.Denom()))
		g.GCD(nil, nil, g, new(big.Int).Abs(ints[i]))
	}
	if p.lc().Sign() < 0 {
		g.Neg(g)
	}
	out := make(Poly, len(p))
	for i := range ints {
		out[i] = new(big.Rat).SetInt(new(big.Int).Quo(ints[i], g))
	}
	return new(big.Rat).SetFrac(g, l), out
}

// ToExpr renders the polynomial in variable x.
func (p Poly) ToExpr(x E) E {
	var ts []E
	for i, c := range p {
		ts = append(ts, Mul(Num(c), Pow(x, Int(int64(i)))))
	}
	return Add(ts...)
}

// coeffsOf returns the coefficient expressions of e as a polynomial in x
// (coefficients may contain other symbols); ok is false if e is not a polynomial in x.
func coeffsOf(e E, x string) ([]E, bool) {
	ex := Expand(e)
	var cs []E
	for _, t := range terms(ex) {
		deg := 0
		var rest []E
		for _, f := range factors(t) {
			switch {
			case !Contains(f, x):
				rest = append(rest, f)
			case f.K == KSym && f.S == x:
				deg++
			case f.K == KPow && f.A[0].K == KSym && f.A[0].S == x && isInt(f.A[1]) && f.A[1].N.Sign() > 0 && f.A[1].N.Num().IsInt64() && f.A[1].N.Num().Int64() < 100000:
				deg += int(f.A[1].N.Num().Int64())
			default:
				return nil, false
			}
		}
		for len(cs) <= deg {
			cs = append(cs, Zero)
		}
		cs[deg] = Add(cs[deg], Mul(rest...))
	}
	for len(cs) > 0 && isNumVal(cs[len(cs)-1], 0) {
		cs = cs[:len(cs)-1]
	}
	return cs, true
}

// ToPoly converts e to a rational polynomial in x if possible.
func ToPoly(e E, x string) (Poly, bool) {
	cs, ok := coeffsOf(e, x)
	if !ok {
		return nil, false
	}
	p := make(Poly, len(cs))
	for i, c := range cs {
		if c.K != KNum {
			return nil, false
		}
		p[i] = new(big.Rat).Set(c.N)
	}
	return trim(p), true
}

// ---------- square-free decomposition & factoring ----------

// PolyFactor is an irreducible factor with multiplicity (primitive, positive leading coefficient).
type PolyFactor struct {
	P    Poly
	Mult int
}

func squareFree(f Poly) []PolyFactor {
	if f.Deg() < 1 {
		return nil
	}
	d := pDeriv(f)
	c := pGcd(f, d)
	w, _ := pDivMod(f, c)
	y, _ := pDivMod(d, c)
	var out []PolyFactor
	for i := 1; w.Deg() >= 1; i++ {
		z := pSub(y, pDeriv(w))
		g := pGcd(w, z)
		if g.Deg() >= 1 {
			out = append(out, PolyFactor{g, i})
		}
		w, _ = pDivMod(w, g)
		if len(z) == 0 {
			break
		}
		y, _ = pDivMod(z, g)
	}
	return out
}

func divisors(n *big.Int) []*big.Int {
	n = new(big.Int).Abs(n)
	fs := factorSmall(n)
	divs := []*big.Int{big.NewInt(1)}
	for _, pp := range fs {
		var next []*big.Int
		pw := big.NewInt(1)
		for k := 0; k <= pp.k; k++ {
			for _, d := range divs {
				next = append(next, new(big.Int).Mul(d, pw))
			}
			pw = new(big.Int).Mul(pw, pp.p)
		}
		divs = next
		if len(divs) > 200000 {
			fail("number has too many divisors for the factoring search")
		}
	}
	return divs
}

// rationalRoots strips all rational roots of the primitive integer polynomial f.
func stripRationalRoots(f Poly) (linear []Poly, rest Poly) {
	rest = f
	for len(rest) > 1 && rest[0].Sign() == 0 {
		linear = append(linear, Poly{new(big.Rat), big.NewRat(1, 1)})
		rest = rest[1:]
	}
	if len(rest) <= 1 {
		return
	}
	for {
		found := false
		a0, an := rest[0].Num(), rest.lc().Num()
		ps, qs := divisors(a0), divisors(an)
		for _, p := range ps {
			for _, q := range qs {
				for _, sg := range []int64{1, -1} {
					r := new(big.Rat).SetFrac(new(big.Int).Mul(p, big.NewInt(sg)), q)
					if pEval(rest, r).Sign() == 0 {
						lin := Poly{new(big.Rat).Neg(new(big.Rat).SetInt(new(big.Int).Mul(p, big.NewInt(sg)))), new(big.Rat).SetInt(q)}
						_, lin = primitiveInt(lin)
						quo, rem := pDivMod(rest, lin)
						if len(rem) != 0 {
							continue
						}
						_, quo = primitiveInt(quo)
						linear = append(linear, lin)
						rest = quo
						found = true
						break
					}
				}
				if found {
					break
				}
			}
			if found {
				break
			}
		}
		if !found || len(rest) <= 1 {
			return
		}
	}
}

// kronecker finds one proper factor of degree 2..deg/2 of a primitive integer polynomial
// with no rational roots, or nil if it is irreducible.
func kronecker(f Poly) Poly {
	n := f.Deg()
	for d := 2; d <= n/2; d++ {
		pts := make([]*big.Rat, 0, d+1)
		vals := make([]*big.Int, 0, d+1)
		for k := int64(0); len(pts) < d+1; k++ {
			cands := []int64{k, -k}
			if k == 0 {
				cands = cands[:1]
			}
			for _, x := range cands {
				if len(pts) == d+1 {
					break
				}
				r := big.NewRat(x, 1)
				v := pEval(f, r)
				if v.Sign() == 0 {
					continue
				}
				pts = append(pts, r)
				vals = append(vals, new(big.Int).Set(v.Num()))
			}
		}
		divLists := make([][]*big.Int, len(vals))
		total := 1.0
		for i, v := range vals {
			ds := divisors(v)
			var signed []*big.Int
			for _, dv := range ds {
				signed = append(signed, dv, new(big.Int).Neg(dv))
			}
			divLists[i] = signed
			total *= float64(len(signed))
		}
		if total > 4e6 {
			fail("polynomial too large for the Kronecker factoring search (degree %d)", n)
		}
		choice := make([]int, len(vals))
		var rec func(int) Poly
		rec = func(i int) Poly {
			if i == len(vals) {
				ys := make([]*big.Rat, len(vals))
				for j := range ys {
					ys[j] = new(big.Rat).SetInt(divLists[j][choice[j]])
				}
				h := interpolate(pts, ys)
				if h.Deg() != d {
					return nil
				}
				for _, c := range h {
					if !c.IsInt() {
						return nil
					}
				}
				_, h = primitiveInt(h)
				if _, rem := pDivMod(f, h); len(rem) == 0 {
					return h
				}
				return nil
			}
			start := 0
			for c := start; c < len(divLists[i]); c++ {
				if i == 0 && divLists[0][c].Sign() < 0 {
					continue // h and -h are the same factor; fix the sign at the first point
				}
				choice[i] = c
				if h := rec(i + 1); h != nil {
					return h
				}
			}
			return nil
		}
		if h := rec(0); h != nil {
			return h
		}
	}
	return nil
}

// interpolate returns the Lagrange interpolating polynomial through (xs, ys).
func interpolate(xs, ys []*big.Rat) Poly {
	var res Poly
	for i := range xs {
		term := Poly{new(big.Rat).Set(ys[i])}
		den := big.NewRat(1, 1)
		for j := range xs {
			if i == j {
				continue
			}
			term = pMul(term, Poly{new(big.Rat).Neg(xs[j]), big.NewRat(1, 1)})
			den.Mul(den, new(big.Rat).Sub(xs[i], xs[j]))
		}
		res = pAdd(res, pScale(term, new(big.Rat).Inv(den)))
	}
	return res
}

func factorSquarefreePrimitive(f Poly) []Poly {
	if f.Deg() <= 1 {
		return []Poly{f}
	}
	lin, rest := stripRationalRoots(f)
	out := append([]Poly{}, lin...)
	var work []Poly
	if rest.Deg() >= 1 {
		work = []Poly{rest}
	}
	for len(work) > 0 {
		g := work[len(work)-1]
		work = work[:len(work)-1]
		if g.Deg() <= 3 { // no rational roots left (checked above): irreducible
			out = append(out, g)
			continue
		}
		for _, irr := range zassenhaus(g) {
			out = append(out, irr)
		}
	}
	return out
}

// FactorPoly factors p over Q into content * prod(irreducible^mult).
func FactorPoly(p Poly) (*big.Rat, []PolyFactor) {
	content, prim := primitiveInt(p)
	if len(prim) == 0 {
		return new(big.Rat), nil
	}
	var out []PolyFactor
	if prim.Deg() == 0 {
		return content, nil
	}
	for _, sf := range squareFree(prim) {
		_, g := primitiveInt(sf.P)
		for _, irr := range factorSquarefreePrimitive(g) {
			out = append(out, PolyFactor{irr, sf.Mult})
		}
	}
	// merge identical factors (possible after splitting) and order by degree then value
	merged := map[string]*PolyFactor{}
	var keys []string
	for i := range out {
		k := polyKey(out[i].P)
		if m, ok := merged[k]; ok {
			m.Mult += out[i].Mult
		} else {
			cp := out[i]
			merged[k] = &cp
			keys = append(keys, k)
		}
	}
	res := make([]PolyFactor, 0, len(keys))
	for _, k := range keys {
		res = append(res, *merged[k])
	}
	sort.SliceStable(res, func(i, j int) bool {
		if res[i].P.Deg() != res[j].P.Deg() {
			return res[i].P.Deg() < res[j].P.Deg()
		}
		for k := res[i].P.Deg(); k >= 0; k-- {
			if c := res[i].P[k].Cmp(res[j].P[k]); c != 0 {
				return c < 0
			}
		}
		return false
	})
	return content, res
}

func polyKey(p Poly) string {
	s := ""
	for _, c := range p {
		s += c.RatString() + ","
	}
	return s
}

// Factor factors a polynomial expression over Q in variable x and returns the product form.
func Factor(e E, x string) E {
	if e.K == KMat {
		fail("cannot factor a matrix")
	}
	p, ok := ToPoly(e, x)
	if !ok {
		// try factoring a rational function: factor numerator and denominator separately
		n, d := NumDen(e)
		if !isNumVal(d, 1) {
			return Div(Factor(n, x), Factor(d, x))
		}
		fail("cannot factor %s: it is not a polynomial in %s with rational coefficients (multivariate factoring is not implemented)", e.String(), x)
	}
	if len(p) == 0 {
		return Zero
	}
	content, fs := FactorPoly(p)
	xe := Sym(x)
	parts := []E{Num(content)}
	for _, f := range fs {
		parts = append(parts, Pow(f.P.ToExpr(xe), Int(int64(f.Mult))))
	}
	return mulNoDistribute(parts)
}

// mulNoDistribute builds a product but keeps a lone sum factor undistributed.
func mulNoDistribute(parts []E) E {
	var c = big.NewRat(1, 1)
	var rest []E
	for _, p := range parts {
		if p.K == KNum {
			c.Mul(c, p.N)
		} else {
			rest = append(rest, p)
		}
	}
	if len(rest) == 1 && rest[0].K == KAdd && c.Cmp(big.NewRat(1, 1)) != 0 {
		return &Expr{K: KMul, A: []E{Num(c), rest[0]}}
	}
	return Mul(parts...)
}

// NumDen splits an expression into numerator and denominator by negative-exponent factors.
func NumDen(e E) (E, E) {
	var n, d []E
	for _, f := range factors(e) {
		if f.K == KPow && f.A[1].K == KNum && f.A[1].N.Sign() < 0 {
			d = append(d, Pow(f.A[0], Num(new(big.Rat).Neg(f.A[1].N))))
		} else {
			n = append(n, f)
		}
	}
	return Mul(n...), Mul(d...)
}

// PolyGCD returns the monic gcd of two polynomial expressions in x.
func PolyGCD(a, b E, x string) E {
	pa, ok1 := ToPoly(a, x)
	pb, ok2 := ToPoly(b, x)
	if !ok1 || !ok2 {
		fail("gcd needs polynomials in %s with rational coefficients", x)
	}
	return pGcd(pa, pb).ToExpr(Sym(x))
}

// Together puts a sum of rational functions over a single denominator (polynomial case), cancelling common factors.
func Together(e E, x string) E {
	var nums, dens []E
	for _, t := range terms(Expand(e)) {
		n, d := NumDen(t)
		nums, dens = append(nums, n), append(dens, d)
	}
	den := One
	for _, d := range dens {
		den = Mul(den, d)
	}
	num := make([]E, len(nums))
	for i := range nums {
		o := One
		for j := range dens {
			if i != j {
				o = Mul(o, dens[j])
			}
		}
		num[i] = Mul(nums[i], o)
	}
	return Cancel(Add(num...), den, x)
}

// Cancel returns num/den with the polynomial gcd (in x) divided out.
func Cancel(num, den E, x string) E {
	pn, ok1 := ToPoly(num, x)
	pd, ok2 := ToPoly(den, x)
	if !ok1 || !ok2 || len(pd) == 0 {
		return Div(num, den)
	}
	g := pGcd(pn, pd)
	if len(pn) == 0 {
		return Zero
	}
	qn, _ := pDivMod(pn, g)
	qd, _ := pDivMod(pd, g)
	lc := qd.lc()
	qn, qd = pScale(qn, new(big.Rat).Inv(lc)), pScale(qd, new(big.Rat).Inv(lc))
	xe := Sym(x)
	if qd.Deg() == 0 {
		return qn.ToExpr(xe)
	}
	return Mul(qn.ToExpr(xe), Pow(qd.ToExpr(xe), MinusOne))
}
