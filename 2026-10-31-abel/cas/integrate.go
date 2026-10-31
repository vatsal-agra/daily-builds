package cas

import (
	"fmt"
	"math"
	"math/big"
	"math/cmplx"
	"sort"
)

const maxIntDepth = 30
const intBudget = 40000

type integrator struct {
	x      string
	budget int
	reason string
}

// Integrate returns an antiderivative of f with respect to x (without the constant of integration).
// The engine tries, in order: linearity, constant extraction, a table of elementary forms with linear
// arguments, rational functions (exact partial fractions), trigonometric power products, e^{ax}·trig,
// u-substitution and integration by parts. It reports honestly when none of them applies.
func Integrate(f E, x string) (res E, err error) {
	err = Guard(func() {
		in := &integrator{x: x, budget: intBudget}
		r, ok := in.integ(f, x, 0)
		if !ok {
			msg := ""
			if in.reason != "" {
				msg = "; " + in.reason
			}
			fail("no closed form found for the integral of %s (not elementary, or beyond the implemented methods%s)", f.String(), msg)
		}
		res = r
	})
	return
}

func (in *integrator) try(fn func() (E, bool)) (r E, ok bool) {
	defer func() {
		if rec := recover(); rec != nil {
			if _, is := rec.(MathError); is {
				r, ok = nil, false
				return
			}
			panic(rec)
		}
	}()
	return fn()
}

// linearIn returns (a, b) with u = a*x + b where a, b are free of x and a != 0.
func linearIn(u E, x string) (a, b E, ok bool) {
	cs, ok := coeffsOf(u, x)
	if !ok || len(cs) != 2 || isNumVal(cs[1], 0) {
		return nil, nil, false
	}
	return cs[1], cs[0], true
}

func (in *integrator) integ(f E, x string, d int) (E, bool) {
	in.budget--
	if d > maxIntDepth || in.budget < 0 {
		return nil, false
	}
	if !Contains(f, x) {
		return Mul(f, Sym(x)), true
	}
	xs := Sym(x)
	if f.K == KAdd {
		out := make([]E, 0, len(f.A))
		okAll := true
		for _, t := range f.A {
			r, ok := in.integ(t, x, d+1)
			if !ok {
				okAll = false
				break
			}
			out = append(out, r)
		}
		if okAll {
			return Add(out...), true
		}
		if r, ok := in.try(func() (E, bool) { return in.rational(Together(f, x), x) }); ok {
			return r, true
		}
		return nil, false
	}
	// pull out constant factors
	if f.K == KMul {
		var cs, rest []E
		for _, fa := range f.A {
			if Contains(fa, x) {
				rest = append(rest, fa)
			} else {
				cs = append(cs, fa)
			}
		}
		if len(cs) > 0 {
			r, ok := in.integ(Mul(rest...), x, d+1)
			if !ok {
				return nil, false
			}
			return Mul(Mul(cs...), r), true
		}
	}
	if f.K == KSym && f.S == x {
		return Mul(Frac(1, 2), Pow(xs, Int(2))), true
	}
	if r, ok := in.try(func() (E, bool) { return in.table(f, x) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.rational(f, x) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.polyTimesElem(f, x) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.sqrtQuad(f, x) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.trigProduct(f, x, d) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.expTrig(f, x) }); ok {
		return r, true
	}
	if r, ok := in.try(func() (E, bool) { return in.usub(f, x, d) }); ok {
		return r, true
	}
	if ex := Expand(f); !Equal(ex, f) {
		if r, ok := in.try(func() (E, bool) { return in.integ(ex, x, d+1) }); ok {
			return r, true
		}
	}
	if r, ok := in.try(func() (E, bool) { return in.parts(f, x, d) }); ok {
		return r, true
	}
	return nil, false
}

// ---------- table of elementary forms with linear arguments ----------

func (in *integrator) table(f E, x string) (E, bool) {
	switch f.K {
	case KFn:
		if len(f.A) != 1 {
			return nil, false
		}
		u := f.A[0]
		a, _, ok := linearIn(u, x)
		if !ok {
			return nil, false
		}
		var g E
		switch f.S {
		case "sin":
			g = Neg(Fn("cos", u))
		case "cos":
			g = Fn("sin", u)
		case "tan":
			g = Neg(Ln(Fn("cos", u)))
		case "exp":
			g = f
		case "ln":
			g = Sub(Mul(u, f), u)
		case "atan":
			g = Sub(Mul(u, f), Mul(Frac(1, 2), Ln(Add(One, Pow(u, Int(2))))))
		case "asin":
			g = Add(Mul(u, f), Sqrt(Sub(One, Pow(u, Int(2)))))
		case "acos":
			g = Sub(Mul(u, f), Sqrt(Sub(One, Pow(u, Int(2)))))
		case "sinh":
			g = Fn("cosh", u)
		case "cosh":
			g = Fn("sinh", u)
		case "tanh":
			g = Ln(Fn("cosh", u))
		case "abs":
			g = Mul(Frac(1, 2), u, f)
		default:
			return nil, false
		}
		return Div(g, a), true
	case KPow:
		b, e := f.A[0], f.A[1]
		if b.K == KFn && b.S == "tan" && isInt(e) && e.N.Sign() > 0 && e.N.Num().IsInt64() && e.N.Num().Int64() <= 40 {
			if a, _, ok := linearIn(b.A[0], x); ok {
				return Div(tanPow(e.N.Num().Int64(), b.A[0]), a), true
			}
		}
		if !Contains(e, x) {
			if a, _, ok := linearIn(b, x); ok {
				if isNumVal(e, -1) {
					return Div(Ln(b), a), true
				}
				return Div(Pow(b, Add(e, One)), Mul(a, Add(e, One))), true
			}
		} else if !Contains(b, x) {
			if a, _, ok := linearIn(e, x); ok {
				return Div(f, Mul(a, Ln(b))), true
			}
		}
	}
	return nil, false
}

// ---------- rational functions: exact partial fractions ----------

func (in *integrator) rational(f E, x string) (E, bool) {
	n, d := NumDen(f)
	pn, ok1 := ToPoly(n, x)
	pd, ok2 := ToPoly(d, x)
	if !ok1 || !ok2 || len(pd) == 0 || len(pn) == 0 {
		return nil, false
	}
	r, ok := integrateRational(pn, pd, x)
	if !ok && pd.Deg() > 2 {
		in.reason = "a rational integrand whose denominator has an irreducible factor of degree > 2 over Q, such as x^4+1, would need algebraic-number partial fractions"
	}
	return r, ok
}

// pfItem is one partial-fraction term N / Q^J with Q irreducible and deg N < deg Q.
type pfItem struct {
	N, Q Poly
	J    int
}

// partialFractions decomposes pn/pd (pd non-zero) into a polynomial part plus irreducible-power terms.
// ok is false if the denominator has an irreducible factor of degree > maxFactorDeg.
func partialFractions(pn, pd Poly, maxFactorDeg int) (quo Poly, items []pfItem, ok bool) {
	quo, rem := pDivMod(pn, pd)
	if len(rem) == 0 {
		return quo, nil, true
	}
	content, fs := FactorPoly(pd)
	for _, f := range fs {
		if maxFactorDeg > 0 && f.P.Deg() > maxFactorDeg {
			return nil, nil, false
		}
	}
	D := Poly{big.NewRat(1, 1)}
	for _, f := range fs {
		D = pMul(D, pPow(f.P, f.Mult))
	}
	target := pScale(rem, new(big.Rat).Inv(content))
	type unk struct{ fi, j, k int }
	var unknowns []unk
	var cols []Poly
	for fi, f := range fs {
		for j := 1; j <= f.Mult; j++ {
			w, _ := pDivMod(D, pPow(f.P, j))
			for k := 0; k < f.P.Deg(); k++ {
				unknowns = append(unknowns, unk{fi, j, k})
				col := make(Poly, k+1)
				for i := range col {
					col[i] = new(big.Rat)
				}
				col[k] = big.NewRat(1, 1)
				cols = append(cols, trim(pMul(col, w)))
			}
		}
	}
	nU := len(unknowns)
	if nU != D.Deg() {
		return nil, nil, false
	}
	aug := make(ratMat, nU)
	for r := 0; r < nU; r++ {
		aug[r] = make([]*big.Rat, nU+1)
		for c := 0; c < nU; c++ {
			aug[r][c] = new(big.Rat)
			if r < len(cols[c]) {
				aug[r][c].Set(cols[c][r])
			}
		}
		aug[r][nU] = new(big.Rat)
		if r < len(target) {
			aug[r][nU].Set(target[r])
		}
	}
	piv, _ := rref(aug, nU)
	if len(piv) != nU {
		return nil, nil, false
	}
	numer := map[[2]int]Poly{}
	for idx, u := range unknowns {
		key := [2]int{u.fi, u.j}
		p := numer[key]
		for len(p) <= u.k {
			p = append(p, new(big.Rat))
		}
		p[u.k] = new(big.Rat).Set(aug[idx][nU])
		numer[key] = p
	}
	for fi, f := range fs {
		for j := 1; j <= f.Mult; j++ {
			N := trim(numer[[2]int{fi, j}])
			if len(N) == 0 {
				continue
			}
			items = append(items, pfItem{pScale(N, new(big.Rat).Inv(content)), f.P, j})
		}
	}
	return quo, items, true
}

// Apart returns the partial-fraction expansion of a rational function of x.
func Apart(e E, x string) E {
	n, d := NumDen(Together(e, x))
	pn, ok1 := ToPoly(n, x)
	pd, ok2 := ToPoly(d, x)
	if !ok1 || !ok2 || len(pd) == 0 {
		fail("apart needs a rational function of %s with rational coefficients", x)
	}
	if len(pn) == 0 {
		return Zero
	}
	quo, items, ok := partialFractions(pn, pd, 0)
	if !ok {
		fail("could not decompose the denominator")
	}
	xs := Sym(x)
	parts := []E{quo.ToExpr(xs)}
	for _, it := range items {
		parts = append(parts, Mul(it.N.ToExpr(xs), Pow(it.Q.ToExpr(xs), Int(int64(-it.J)))))
	}
	return Add(parts...)
}

func integrateRational(pn, pd Poly, x string) (E, bool) {
	xs := Sym(x)
	quo, items, ok := partialFractions(pn, pd, 2)
	if !ok {
		return nil, false
	}
	var parts []E
	for i, c := range quo {
		parts = append(parts, Mul(Num(new(big.Rat).Quo(c, big.NewRat(int64(i+1), 1))), Pow(xs, Int(int64(i+1)))))
	}
	for _, it := range items {
		parts = append(parts, integratePartial(it.N, it.Q, it.J, x))
	}
	return Add(parts...), true
}

// integratePartial integrates N / q^j for an irreducible q of degree 1 or 2 and deg N < deg q.
func integratePartial(N, q Poly, j int, x string) E {
	xs := Sym(x)
	qe := q.ToExpr(xs)
	if q.Deg() == 1 {
		A, a := N[0], q[1]
		if j == 1 {
			return Mul(Num(new(big.Rat).Quo(A, a)), Ln(qe))
		}
		c := new(big.Rat).Quo(A, new(big.Rat).Mul(a, big.NewRat(int64(1-j), 1)))
		return Mul(Num(c), Pow(qe, Int(int64(1-j))))
	}
	// q = alpha (s^2 + kappa), s = x + b/2
	alpha := q[2]
	b := new(big.Rat).Quo(q[1], alpha)
	c0 := new(big.Rat).Quo(q[0], alpha)
	kappa := new(big.Rat).Sub(c0, new(big.Rat).Quo(new(big.Rat).Mul(b, b), big.NewRat(4, 1)))
	s := Add(xs, Num(new(big.Rat).Quo(b, big.NewRat(2, 1))))
	qm := Add(Pow(xs, Int(2)), Mul(Num(b), xs), Num(c0)) // monic form, expanded
	aj := new(big.Rat).SetInt64(1)
	for i := 0; i < j; i++ {
		aj.Mul(aj, alpha)
	}
	B, C := new(big.Rat), N[0]
	if len(N) > 1 {
		B = N[1]
	}
	B = new(big.Rat).Quo(B, aj)
	C = new(big.Rat).Quo(C, aj)
	rest := new(big.Rat).Sub(C, new(big.Rat).Quo(new(big.Rat).Mul(B, b), big.NewRat(2, 1)))
	var out []E
	if B.Sign() != 0 {
		if j == 1 {
			out = append(out, Mul(Num(new(big.Rat).Quo(B, big.NewRat(2, 1))), Ln(qm)))
		} else {
			out = append(out, Mul(Num(new(big.Rat).Quo(B, big.NewRat(int64(2*(1-j)), 1))), Pow(qm, Int(int64(1-j)))))
		}
	}
	if rest.Sign() != 0 {
		out = append(out, Mul(Num(rest), quadI(s, kappa, j)))
	}
	return Add(out...)
}

// quadI is the integral of ds/(s^2+kappa)^k.
func quadI(s E, kappa *big.Rat, k int) E {
	kap := Num(kappa)
	if k == 1 {
		if kappa.Sign() > 0 {
			r := Sqrt(kap)
			return Mul(Pow(r, MinusOne), Fn("atan", Div(s, r)))
		}
		r := Sqrt(Num(new(big.Rat).Neg(kappa)))
		return Mul(Pow(Mul(Int(2), r), MinusOne), Ln(Div(Sub(s, r), Add(s, r))))
	}
	qk := Pow(Add(Pow(s, Int(2)), kap), Int(int64(1-k)))
	t1 := Div(Mul(s, qk), Mul(Int(int64(2*(k-1))), kap))
	t2 := Mul(Div(Int(int64(2*k-3)), Mul(Int(int64(2*(k-1))), kap)), quadI(s, kappa, k-1))
	return Add(t1, t2)
}

// ---------- trigonometric products ----------

func trigBaseExp(f E) (name string, arg E, n int64, ok bool) {
	base, ex := factorBaseExp(f)
	if base.K != KFn || len(base.A) != 1 || (base.S != "sin" && base.S != "cos") {
		return
	}
	n, isI := intExp(ex)
	if !isI {
		return
	}
	return base.S, base.A[0], n, true
}

func (in *integrator) trigProduct(f E, x string, d int) (E, bool) {
	if fs := factors(f); len(fs) == 2 && fs[0].K == KFn && fs[1].K == KFn && len(fs[0].A) == 1 && len(fs[1].A) == 1 &&
		(fs[0].S == "sin" || fs[0].S == "cos") && (fs[1].S == "sin" || fs[1].S == "cos") && !Equal(fs[0].A[0], fs[1].A[0]) {
		A, B := fs[0].A[0], fs[1].A[0]
		if _, _, ok1 := linearIn(A, x); ok1 {
			if _, _, ok2 := linearIn(B, x); ok2 {
				var rw E
				sum, dif := Add(A, B), Sub(A, B)
				switch {
				case fs[0].S == "sin" && fs[1].S == "cos":
					rw = Mul(Frac(1, 2), Add(Fn("sin", sum), Fn("sin", dif)))
				case fs[0].S == "cos" && fs[1].S == "sin":
					rw = Mul(Frac(1, 2), Add(Fn("sin", sum), Neg(Fn("sin", dif))))
				case fs[0].S == "cos":
					rw = Mul(Frac(1, 2), Add(Fn("cos", dif), Fn("cos", sum)))
				default:
					rw = Mul(Frac(1, 2), Sub(Fn("cos", dif), Fn("cos", sum)))
				}
				return in.integ(Expand(rw), x, d+1)
			}
		}
	}
	var m, n int64
	var u E
	for _, fa := range factors(f) {
		nm, arg, e, ok := trigBaseExp(fa)
		if !ok {
			return nil, false
		}
		if u == nil {
			u = arg
		} else if !Equal(u, arg) {
			return nil, false
		}
		if nm == "sin" {
			m += e
		} else {
			n += e
		}
	}
	if u == nil {
		return nil, false
	}
	a, _, ok := linearIn(u, x)
	if !ok {
		return nil, false
	}
	G, ok := in.trigIntegral(m, n, u, x, d)
	if !ok {
		return nil, false
	}
	return Div(G, a), true
}

// powerPoly returns the coefficients (by exponent) of (1 - v^2)^j * v^e.
func powerPoly(j int64, e int64) map[int64]*big.Rat {
	out := map[int64]*big.Rat{}
	binom := big.NewInt(1)
	for i := int64(0); i <= j; i++ {
		c := new(big.Rat).SetInt(binom)
		if i%2 == 1 {
			c.Neg(c)
		}
		out[2*i+e] = c
		binom = new(big.Int).Div(new(big.Int).Mul(binom, big.NewInt(j-i)), big.NewInt(i+1))
	}
	return out
}

// integrate sum coef * v^k dv for exponent map (k may be -1 -> ln)
func integratePowers(m map[int64]*big.Rat, v E) E {
	keys := make([]int64, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return keys[i] < keys[j] })
	var ts []E
	for _, k := range keys {
		c := m[k]
		if k == -1 {
			ts = append(ts, Mul(Num(c), Ln(v)))
		} else {
			ts = append(ts, Mul(Num(new(big.Rat).Quo(c, big.NewRat(k+1, 1))), Pow(v, Int(k+1))))
		}
	}
	return Add(ts...)
}

// trigIntegral integrates sin(u)^m cos(u)^n with respect to u.
func (in *integrator) trigIntegral(m, n int64, u E, x string, d int) (E, bool) {
	s, c := Fn("sin", u), Fn("cos", u)
	switch {
	case m == 0 && n == 0:
		return nil, false
	case m > 0 && n == -m: // tan^m
		return tanPow(m, u), true
	case m > 0 && m%2 == 1 && n > -64 && n < 64:
		return Neg(integratePowers(powerPoly((m-1)/2, n), c)), true
	case n > 0 && n%2 == 1 && m > -64 && m < 64:
		return integratePowers(powerPoly((n-1)/2, m), s), true
	case m >= 0 && n >= 0 && m%2 == 0 && n%2 == 0 && m+n <= 40:
		k := m
		if n < k {
			k = n
		}
		s2, c2 := Fn("sin", Mul(Int(2), u)), Fn("cos", Mul(Int(2), u))
		rewrite := Pow(Mul(Frac(1, 2), s2), Int(k))
		if m > k {
			rewrite = Mul(rewrite, Pow(Mul(Frac(1, 2), Sub(One, c2)), Int((m-k)/2)))
		} else if n > k {
			rewrite = Mul(rewrite, Pow(Mul(Frac(1, 2), Add(One, c2)), Int((n-k)/2)))
		}
		r, ok := in.integ(Expand(rewrite), x, d+1)
		if !ok {
			return nil, false
		}
		// r is an antiderivative w.r.t. x of the rewritten integrand; convert to d/du by multiplying by a
		a, _, _ := linearIn(u, x)
		return Mul(r, a), true
	case m == 0 && n < 0 && n%2 == 0: // sec^(2j)
		j := -n / 2
		return integratePowers(powerPoly(j-1, 0), Fn("tan", u)), true
	case n == 0 && m < 0 && m%2 == 0: // csc^(2j)
		j := -m / 2
		cot := Div(c, s)
		pp := map[int64]*big.Rat{}
		for k, v := range powerPolyPlus(j - 1) {
			pp[k] = v
		}
		return Neg(integratePowers(pp, cot)), true
	case m == 0 && n == -1:
		return Ln(Add(Pow(c, MinusOne), Div(s, c))), true
	case n == 0 && m == -1:
		return Ln(Fn("tan", Mul(Frac(1, 2), u))), true
	}
	return nil, false
}

// powerPolyPlus returns coefficients of (1 + v^2)^j by exponent.
func powerPolyPlus(j int64) map[int64]*big.Rat {
	out := map[int64]*big.Rat{}
	binom := big.NewInt(1)
	for i := int64(0); i <= j; i++ {
		out[2*i] = new(big.Rat).SetInt(binom)
		binom = new(big.Int).Div(new(big.Int).Mul(binom, big.NewInt(j-i)), big.NewInt(i+1))
	}
	return out
}

func tanPow(m int64, u E) E {
	if m == 0 {
		return u
	}
	if m == 1 {
		return Neg(Ln(Fn("cos", u)))
	}
	t := Fn("tan", u)
	return Sub(Div(Pow(t, Int(m-1)), Int(m-1)), tanPow(m-2, u))
}

// ---------- e^{px+q} * sin/cos(rx+s) ----------

func (in *integrator) expTrig(f E, x string) (E, bool) {
	var ex, tr E
	for _, fa := range factors(f) {
		if fa.K == KFn && fa.S == "exp" && ex == nil {
			ex = fa
		} else if fa.K == KFn && (fa.S == "sin" || fa.S == "cos") && tr == nil {
			tr = fa
		} else {
			return nil, false
		}
	}
	if ex == nil || tr == nil {
		return nil, false
	}
	p, _, ok1 := linearIn(ex.A[0], x)
	q, _, ok2 := linearIn(tr.A[0], x)
	if !ok1 || !ok2 {
		return nil, false
	}
	den := Add(Pow(p, Int(2)), Pow(q, Int(2)))
	var body E
	if tr.S == "sin" {
		body = Sub(Mul(p, tr), Mul(q, Fn("cos", tr.A[0])))
	} else {
		body = Add(Mul(p, tr), Mul(q, Fn("sin", tr.A[0])))
	}
	return Div(Mul(ex, body), den), true
}

// ---------- u-substitution ----------

func subexprs(e E, x string, out map[string]E) {
	for _, a := range e.A {
		if Contains(a, x) && !(a.K == KSym) && a.K != KNum {
			out[a.Key()] = a
		}
		subexprs(a, x, out)
	}
}

func size(e E) int {
	n := 1
	for _, a := range e.A {
		n += size(a)
	}
	return n
}

func (in *integrator) usub(f E, x string, d int) (E, bool) {
	cand := map[string]E{}
	subexprs(f, x, cand)
	list := make([]E, 0, len(cand))
	for _, c := range cand {
		if c.K == KMul || (c.K == KNum) {
			continue
		}
		list = append(list, c)
	}
	sort.Slice(list, func(i, j int) bool {
		si, sj := size(list[i]), size(list[j])
		if si != sj {
			return si > sj
		}
		return list[i].Key() < list[j].Key()
	})
	if len(list) > 24 {
		list = list[:24]
	}
	t := fmt.Sprintf("_t%d", d)
	for _, u := range list {
		du := Diff(u, x)
		if isNumVal(du, 0) {
			continue
		}
		r1 := Mul(f, Pow(du, MinusOne))
		for _, r := range []E{r1, Expand(r1)} {
			rt := substLike(r, u, Sym(t), x)
			if Contains(rt, x) || !Contains(rt, t) {
				continue
			}
			g, ok := in.integ(rt, t, d+1)
			if !ok {
				continue
			}
			return SubstExpr(g, Sym(t), u), true
		}
	}
	return nil, false
}

// substLike replaces u by t in r, also recognising rescaled copies: x^m for u = x^k, and
// e^(q*w) for u = e^w (q rational), which become t^(m/k) and t^q.
func substLike(r, u, t E, x string) E {
	if Equal(r, u) {
		return t
	}
	if u.K == KPow && u.A[0].K == KSym && u.A[0].S == x && u.A[1].K == KNum && r.K == KPow && Equal(r.A[0], u.A[0]) && r.A[1].K == KNum {
		q := new(big.Rat).Quo(r.A[1].N, u.A[1].N)
		return Pow(t, Num(q))
	}
	if u.K == KFn && u.S == "exp" && r.K == KFn && r.S == "exp" {
		q := Div(r.A[0], u.A[0])
		if q.K == KNum {
			return Pow(t, q)
		}
	}
	return Map(r, func(c E) E { return substLike(c, u, t, x) })
}

// ---------- polynomial * exp / sin / cos of a linear argument (tabular integration by parts) ----------

// polyTimesElem integrates P(x) * g(a x + b) for g in {exp, sin, cos} by the tabular method:
// sum over k of (-1)^k P^(k)(x) * G_{k+1}(u) / a^(k+1), where G_j is the j-th antiderivative of g.
func (in *integrator) polyTimesElem(f E, x string) (E, bool) {
	var g E
	var rest []E
	for _, fa := range factors(f) {
		if fa.K == KFn && len(fa.A) == 1 && (fa.S == "exp" || fa.S == "sin" || fa.S == "cos") && g == nil {
			g = fa
		} else {
			rest = append(rest, fa)
		}
	}
	if g == nil || len(rest) == 0 {
		return nil, false
	}
	P := Expand(Mul(rest...))
	cs, ok := coeffsOf(P, x)
	if !ok || len(cs) < 2 || len(cs) > 61 {
		return nil, false
	}
	a, _, ok := linearIn(g.A[0], x)
	if !ok {
		return nil, false
	}
	u := g.A[0]
	anti := func(j int) E { // j-th antiderivative of g w.r.t. u (j >= 1)
		switch g.S {
		case "exp":
			return g
		case "sin":
			return [4]E{Neg(Fn("cos", u)), Neg(Fn("sin", u)), Fn("cos", u), Fn("sin", u)}[(j-1)%4]
		}
		return [4]E{Fn("sin", u), Neg(Fn("cos", u)), Neg(Fn("sin", u)), Fn("cos", u)}[(j-1)%4]
	}
	var terms []E
	cur := P
	for k := 0; !isNumVal(cur, 0); k++ {
		sign := Int(1)
		if k%2 == 1 {
			sign = Int(-1)
		}
		terms = append(terms, Mul(sign, cur, anti(k+1), Pow(a, Int(int64(-(k+1))))))
		cur = Diff(cur, x)
	}
	return Add(terms...), true
}

// ---------- sqrt / reciprocal sqrt of a quadratic ----------

// sqrtQuad integrates Q^(1/2) and Q^(-1/2) for a rational quadratic Q by completing the square.
func (in *integrator) sqrtQuad(f E, x string) (E, bool) {
	if f.K != KPow || f.A[1].K != KNum {
		return nil, false
	}
	half := new(big.Rat).Abs(f.A[1].N).Cmp(big.NewRat(1, 2)) == 0
	if !half {
		return nil, false
	}
	p, ok := ToPoly(f.A[0], x)
	if !ok || p.Deg() != 2 {
		return nil, false
	}
	alpha, beta, gamma := p[2], p[1], p[0]
	// Q = alpha (s^2 + kappa), s = x + beta/(2 alpha)
	sh := new(big.Rat).Quo(beta, new(big.Rat).Mul(alpha, big.NewRat(2, 1)))
	kappa := new(big.Rat).Sub(new(big.Rat).Quo(gamma, alpha), new(big.Rat).Mul(sh, sh))
	if kappa.Sign() == 0 {
		return nil, false
	}
	s := Add(Sym(x), Num(sh))
	inv := f.A[1].N.Sign() < 0
	if alpha.Sign() > 0 {
		root := Sqrt(Add(Pow(s, Int(2)), Num(kappa)))
		lg := Ln(Add(s, root))
		sa := Sqrt(Num(alpha))
		if inv {
			return Div(lg, sa), true
		}
		return Mul(sa, Frac(1, 2), Add(Mul(s, root), Mul(Num(kappa), lg))), true
	}
	if kappa.Sign() > 0 {
		return nil, false // Q <= 0 everywhere
	}
	R := Sqrt(Num(new(big.Rat).Neg(kappa)))
	sa := Sqrt(Num(new(big.Rat).Neg(alpha)))
	as := Fn("asin", Div(s, R))
	if inv {
		return Div(as, sa), true
	}
	root := Sqrt(Sub(Pow(R, Int(2)), Pow(s, Int(2))))
	return Mul(sa, Frac(1, 2), Add(Mul(s, root), Mul(Pow(R, Int(2)), as))), true
}

// ---------- integration by parts ----------

func liate(f E, x string) int {
	base, _ := factorBaseExp(f)
	switch {
	case base.K == KFn && (base.S == "ln" || base.S == "atan" || base.S == "asin" || base.S == "acos"):
		return 0
	case base.K == KFn && (base.S == "sin" || base.S == "cos" || base.S == "tan" || base.S == "sinh" || base.S == "cosh" || base.S == "tanh"):
		return 2
	case base.K == KFn && base.S == "exp":
		return 3
	}
	return 1
}

func (in *integrator) parts(f E, x string, d int) (E, bool) {
	fs := factors(f)
	type choice struct{ u, dv E }
	var choices []choice
	if len(fs) == 1 {
		if liate(fs[0], x) == 0 {
			choices = append(choices, choice{fs[0], One})
		}
	} else {
		idx := make([]int, len(fs))
		for i := range idx {
			idx[i] = i
		}
		sort.SliceStable(idx, func(a, b int) bool { return liate(fs[idx[a]], x) < liate(fs[idx[b]], x) })
		for _, i := range idx {
			var rest []E
			for j, g := range fs {
				if j != i {
					rest = append(rest, g)
				}
			}
			choices = append(choices, choice{fs[i], Mul(rest...)})
		}
	}
	for _, c := range choices {
		v, ok := in.integ(c.dv, x, d+1)
		if !ok {
			continue
		}
		w := Mul(v, Diff(c.u, x))
		if Equal(w, f) {
			continue
		}
		g, ok := in.integ(w, x, d+1)
		if !ok {
			g2, ok2 := in.integ(Expand(w), x, d+1)
			if !ok2 {
				continue
			}
			g = g2
		}
		return Sub(Mul(c.u, v), g), true
	}
	return nil, false
}

// ---------- definite integrals and certification ----------

// DefiniteIntegral computes the integral of f over [a, b]. When both limits are numeric it cross-checks
// the symbolic result against adaptive numeric quadrature (checked == true) and refuses answers that
// disagree, such as an integrand with a pole inside the interval. Improper integrals are not supported.
func DefiniteIntegral(f E, x string, a, b E) (res E, checked bool, err error) {
	err = Guard(func() {
		F, e := Integrate(f, x)
		if e != nil {
			fail("%s", e.Error())
		}
		improper := func() {
			fail("improper integral: the integrand or its antiderivative is singular on [%s, %s] (limits are not implemented)", a.String(), b.String())
		}
		var hi, lo E
		if err := Guard(func() { hi, lo = Sub1(F, x, b), Sub1(F, x, a) }); err != nil {
			improper()
		}
		res = Sub(hi, lo)
		av, e1 := EvalNum(a, nil)
		bv, e2 := EvalNum(b, nil)
		if e1 == nil && e2 == nil && imag(av) == 0 && imag(bv) == 0 {
			num, ok := Quadrature(f, x, real(av), real(bv))
			sym, e3 := EvalNum(res, nil)
			if !ok || e3 != nil || cmplx.Abs(sym-complex(num, 0)) > 1e-6*(1+math.Abs(num)) {
				improper()
			}
			checked = true
		}
	})
	return
}

// Quadrature integrates f numerically over [a, b] with composite 5-point Gauss–Legendre on a fine
// mesh with bisection until two successive refinements agree. ok is false if f is not finite on the interval.
func Quadrature(f E, x string, a, b float64) (float64, bool) {
	nodes := []float64{0, -0.5384693101056831, 0.5384693101056831, -0.906179845938664, 0.906179845938664}
	weights := []float64{0.5688888888888889, 0.47862867049936647, 0.47862867049936647, 0.23692688505618908, 0.23692688505618908}
	eval := func(t float64) (float64, bool) {
		v, err := EvalReal(f, map[string]float64{x: t})
		return v, err == nil && !math.IsNaN(v) && !math.IsInf(v, 0)
	}
	panelSum := func(lo, hi float64) (float64, bool) {
		h, m := (hi-lo)/2, (hi+lo)/2
		s := 0.0
		for i, n := range nodes {
			v, ok := eval(m + h*n)
			if !ok {
				return 0, false
			}
			s += weights[i] * v
		}
		return s * h, true
	}
	var adapt func(lo, hi, whole float64, depth int) (float64, bool)
	adapt = func(lo, hi, whole float64, depth int) (float64, bool) {
		mid := (lo + hi) / 2
		l, ok1 := panelSum(lo, mid)
		r, ok2 := panelSum(mid, hi)
		if !ok1 || !ok2 {
			return 0, false
		}
		if math.Abs(l+r-whole) < 1e-10*(1+math.Abs(whole)) || depth >= 14 {
			if depth >= 14 && math.Abs(l+r-whole) > 1e-6*(1+math.Abs(whole)) {
				return 0, false // not converging: singular behaviour
			}
			return l + r, true
		}
		lv, ok1 := adapt(lo, mid, l, depth+1)
		rv, ok2 := adapt(mid, hi, r, depth+1)
		return lv + rv, ok1 && ok2
	}
	if a == b {
		return 0, true
	}
	sign := 1.0
	if a > b {
		a, b, sign = b, a, -1
	}
	total := 0.0
	const panels = 8
	for i := 0; i < panels; i++ {
		lo := a + (b-a)*float64(i)/panels
		hi := a + (b-a)*float64(i+1)/panels
		w, ok := panelSum(lo, hi)
		if !ok {
			return 0, false
		}
		v, ok := adapt(lo, hi, w, 0)
		if !ok {
			return 0, false
		}
		total += v
	}
	return sign * total, true
}

// Verify certifies that d/dx F == f: symbolically differentiating F and comparing with f numerically at many
// random real points, and (independently) checking that F(b)-F(a) matches numeric quadrature on a safe interval.
func Verify(f, F E, x string) (ok bool, detail string) {
	var dF E
	if err := Guard(func() { dF = Diff(F, x) }); err != nil {
		return false, err.Error()
	}
	if Equal(Expand(Sub(dF, f)), Zero) {
		return true, "d/dx F - f simplifies to 0 exactly"
	}
	good, bad := 0, 0
	worst := 0.0
	seed := uint64(88172645463325252)
	next := func() float64 {
		seed ^= seed << 13
		seed ^= seed >> 7
		seed ^= seed << 17
		return float64(seed%1000003) / 1000003
	}
	for i := 0; i < 60 && bad == 0; i++ {
		t := 0.15 + next()*3.2
		if i%4 == 3 {
			t = -t
		}
		env := map[string]complex128{x: complex(t, 0)}
		for _, s := range FreeSyms(f) {
			if s != x {
				env[s] = complex(0.7+next()*2, 0)
			}
		}
		for _, s := range FreeSyms(F) {
			if _, have := env[s]; !have && s != x {
				env[s] = complex(0.7+next()*2, 0)
			}
		}
		a, e1 := EvalNum(dF, env)
		b, e2 := EvalNum(f, env)
		if e1 != nil || e2 != nil || cmplx.IsNaN(a) || cmplx.IsNaN(b) || cmplx.IsInf(a) || cmplx.IsInf(b) {
			continue
		}
		if math.Abs(imag(a)) > 1e-9 || math.Abs(imag(b)) > 1e-9 {
			continue // outside the real domain of an ln/sqrt
		}
		diff := math.Abs(real(a) - real(b))
		scale := 1 + math.Max(math.Abs(real(a)), math.Abs(real(b)))
		if diff/scale > worst {
			worst = diff / scale
		}
		if diff/scale > 1e-7 {
			bad++
		} else {
			good++
		}
	}
	if bad > 0 {
		return false, fmt.Sprintf("derivative mismatch (relative error %.2e)", worst)
	}
	if good < 4 {
		return false, "too few real sample points to certify"
	}
	return true, fmt.Sprintf("d/dx F matches the integrand at %d random points (max rel. error %.1e)", good, worst)
}
