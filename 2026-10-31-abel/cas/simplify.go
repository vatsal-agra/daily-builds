package cas

import (
	"math/big"
	"sort"
)

// ---------- convenience builders ----------

func Neg(a E) E    { return Mul(MinusOne, a) }
func Sub(a, b E) E { return Add(a, Neg(b)) }
func Div(a, b E) E { return Mul(a, Pow(b, MinusOne)) }
func Sqrt(a E) E   { return Pow(a, Frac(1, 2)) }
func Exp(a E) E    { return Fn("exp", a) }
func Ln(a E) E     { return Fn("ln", a) }

func terms(e E) []E {
	if e.K == KAdd {
		return e.A
	}
	return []E{e}
}

func factors(e E) []E {
	if e.K == KMul {
		return e.A
	}
	return []E{e}
}

// splitCoeff splits a term into numeric coefficient and the rest.
func splitCoeff(t E) (*big.Rat, E) {
	if t.K == KMul && t.A[0].K == KNum {
		if len(t.A) == 2 {
			return t.A[0].N, t.A[1]
		}
		return t.A[0].N, &Expr{K: KMul, A: t.A[1:]}
	}
	if t.K == KNum {
		return t.N, One
	}
	return big.NewRat(1, 1), t
}

func scale(c *big.Rat, rest E) E {
	if c.Cmp(big.NewRat(1, 1)) == 0 {
		return rest
	}
	if rest.K == KMul {
		return &Expr{K: KMul, A: append([]E{Num(c)}, rest.A...)}
	}
	return &Expr{K: KMul, A: []E{Num(c), rest}}
}

func anyMat(es []E) bool {
	for _, e := range es {
		if e.K == KMat {
			return true
		}
	}
	return false
}

// Add builds the canonical sum.
func Add(ts ...E) E {
	if anyMat(ts) {
		return matAddAll(ts)
	}
	c := new(big.Rat)
	type acc struct {
		coef *big.Rat
		rest E
	}
	var order []string
	m := map[string]*acc{}
	var visit func(E)
	visit = func(t E) {
		switch t.K {
		case KAdd:
			for _, a := range t.A {
				visit(a)
			}
		case KNum:
			c.Add(c, t.N)
		default:
			coef, rest := splitCoeff(t)
			k := rest.Key()
			if a, ok := m[k]; ok {
				a.coef.Add(a.coef, coef)
			} else {
				m[k] = &acc{new(big.Rat).Set(coef), rest}
				order = append(order, k)
			}
		}
	}
	for _, t := range ts {
		visit(t)
	}
	var out []E
	for _, k := range order {
		a := m[k]
		if a.coef.Sign() != 0 {
			out = append(out, scale(a.coef, a.rest))
		}
	}
	sortTerms(out)
	if c.Sign() != 0 {
		out = append(out, Num(c))
	}
	switch len(out) {
	case 0:
		return Zero
	case 1:
		return out[0]
	}
	return &Expr{K: KAdd, A: out}
}

// ---------- prime factoring helpers for exact surds ----------

type primePow struct {
	p *big.Int
	k int
}

func factorSmall(n *big.Int) []primePow {
	var out []primePow
	x := new(big.Int).Set(n)
	two := big.NewInt(2)
	add := func(p *big.Int) {
		k := 0
		for {
			q, r := new(big.Int).QuoRem(x, p, new(big.Int))
			if r.Sign() != 0 {
				break
			}
			x = q
			k++
		}
		if k > 0 {
			out = append(out, primePow{new(big.Int).Set(p), k})
		}
	}
	add(two)
	limit := int64(1 << 20)
	for d := int64(3); d <= limit; d += 2 {
		dd := big.NewInt(d)
		if new(big.Int).Mul(dd, dd).Cmp(x) > 0 {
			break
		}
		add(dd)
	}
	if x.Cmp(big.NewInt(1)) > 0 {
		out = append(out, primePow{x, 1}) // prime, or cofactor beyond the trial limit
	}
	return out
}

// rootAcc accumulates a product of positive-rational powers as prime -> rational exponent.
type rootAcc struct {
	exps   map[string]*big.Rat
	primes map[string]*big.Int
}

func newRootAcc() *rootAcc { return &rootAcc{map[string]*big.Rat{}, map[string]*big.Int{}} }

func (ra *rootAcc) add(base *big.Rat, r *big.Rat) {
	for _, part := range []struct {
		n *big.Int
		s int
	}{{base.Num(), 1}, {base.Denom(), -1}} {
		for _, pp := range factorSmall(part.n) {
			k := pp.p.String()
			ra.primes[k] = pp.p
			if ra.exps[k] == nil {
				ra.exps[k] = new(big.Rat)
			}
			t := new(big.Rat).Mul(r, big.NewRat(int64(pp.k*part.s), 1))
			ra.exps[k].Add(ra.exps[k], t)
		}
	}
}

func bigPow(b *big.Int, k int64) *big.Int {
	if k > 200000 {
		fail("exponent too large")
	}
	return new(big.Int).Exp(b, big.NewInt(k), nil)
}

// finish returns the rational coefficient and the canonical radical factors.
func (ra *rootAcc) finish() (*big.Rat, []E) {
	coef := big.NewRat(1, 1)
	byQ := map[int64]*big.Int{}
	var qs []int64
	for k, e := range ra.exps {
		p := ra.primes[k]
		fl := new(big.Int).Div(e.Num(), e.Denom()) // floor (denom > 0)
		f := new(big.Rat).Sub(e, new(big.Rat).SetInt(fl))
		if fl.Sign() != 0 {
			if !fl.IsInt64() || fl.Int64() > 100000 || fl.Int64() < -100000 {
				fail("exponent too large")
			}
			pw := new(big.Rat).SetInt(bigPow(p, abs64(fl.Int64())))
			if fl.Sign() < 0 {
				pw.Inv(pw)
			}
			coef.Mul(coef, pw)
		}
		if f.Sign() != 0 {
			q := f.Denom().Int64()
			if byQ[q] == nil {
				byQ[q] = big.NewInt(1)
				qs = append(qs, q)
			}
			byQ[q].Mul(byQ[q], bigPow(p, new(big.Int).Mul(f.Num(), big.NewInt(1)).Int64()))
		}
	}
	sort.Slice(qs, func(i, j int) bool { return qs[i] < qs[j] })
	var out []E
	for _, q := range qs {
		out = append(out, &Expr{K: KPow, A: []E{Num(new(big.Rat).SetInt(byQ[q])), Frac(1, q)}})
	}
	return coef, out
}

func abs64(x int64) int64 {
	if x < 0 {
		return -x
	}
	return x
}

func isRootFactor(f E) bool {
	return f.K == KPow && f.A[0].K == KNum && f.A[0].N.Sign() > 0 && f.A[1].K == KNum && !f.A[1].N.IsInt()
}

// Mul builds the canonical product.
func Mul(fs ...E) E {
	if anyMat(fs) {
		return matMulAll(fs)
	}
	c := big.NewRat(1, 1)
	type grp struct {
		base E
		exps []E
		orig E
	}
	var order []string
	groups := map[string]*grp{}
	roots := newRootAcc()
	haveRoots := false
	var visit func(E)
	visit = func(f E) {
		switch {
		case f.K == KMul:
			for _, a := range f.A {
				visit(a)
			}
		case f.K == KNum:
			c.Mul(c, f.N)
		case isRootFactor(f):
			roots.add(f.A[0].N, f.A[1].N)
			haveRoots = true
		default:
			b, ex := factorBaseExp(f)
			if f.K == KFn && f.S == "exp" {
				b, ex = EulerE, f.A[0]
			}
			k := b.Key()
			if g, ok := groups[k]; ok {
				g.exps = append(g.exps, ex)
			} else {
				groups[k] = &grp{b, []E{ex}, f}
				order = append(order, k)
			}
		}
	}
	for _, f := range fs {
		visit(f)
	}
	if c.Sign() == 0 {
		return Zero
	}
	var pieces []E
	again := false
	if haveRoots {
		rc, rs := roots.finish()
		c.Mul(c, rc)
		pieces = append(pieces, rs...)
	}
	for _, k := range order {
		g := groups[k]
		var p E
		if len(g.exps) == 1 {
			p = g.orig
		} else {
			p = Pow(g.base, Add(g.exps...))
		}
		if p.K == KNum || p.K == KMul {
			again = true
		}
		pieces = append(pieces, p)
	}
	if again {
		return Mul(append(pieces, Num(c))...)
	}
	if c.Cmp(big.NewRat(1, 1)) != 0 && len(pieces) == 1 && pieces[0].K == KAdd {
		sum := make([]E, len(pieces[0].A))
		for i, t := range pieces[0].A {
			sum[i] = Mul(Num(c), t)
		}
		return Add(sum...)
	}
	sort.SliceStable(pieces, func(i, j int) bool { return cmpFactor(pieces[i], pieces[j]) })
	if c.Cmp(big.NewRat(1, 1)) != 0 {
		pieces = append([]E{Num(c)}, pieces...)
	}
	switch len(pieces) {
	case 0:
		return One
	case 1:
		return pieces[0]
	}
	return &Expr{K: KMul, A: pieces}
}

// Pow builds the canonical power.
func Pow(b, e E) E {
	if b.K == KMat || e.K == KMat {
		return matPow(b, e)
	}
	if e.K == KNum {
		if e.N.Sign() == 0 {
			return One
		}
		if e.N.Cmp(big.NewRat(1, 1)) == 0 {
			return b
		}
	}
	if b.K == KNum {
		if b.N.Cmp(big.NewRat(1, 1)) == 0 {
			return One
		}
		if b.N.Sign() == 0 {
			if e.K == KNum {
				if e.N.Sign() > 0 {
					return Zero
				}
				fail("division by zero")
			}
			return &Expr{K: KPow, A: []E{b, e}}
		}
		if e.K == KNum {
			if e.N.IsInt() {
				n, ok := ratInt64(e.N)
				if !ok || abs64(n) > 100000 {
					fail("exponent too large")
				}
				num := bigPow(b.N.Num(), abs64(n))
				den := bigPow(b.N.Denom(), abs64(n))
				r := new(big.Rat).SetFrac(num, den)
				if n < 0 {
					r.Inv(r)
				}
				return Num(r)
			}
			if b.N.Sign() > 0 {
				ra := newRootAcc()
				ra.add(b.N, e.N)
				c, rs := ra.finish()
				return Mul(append([]E{Num(c)}, rs...)...)
			}
			if e.N.Denom().Cmp(big.NewInt(2)) == 0 {
				pos := Num(new(big.Rat).Neg(b.N))
				return Mul(Pow(I, Num(new(big.Rat).SetInt(e.N.Num()))), Pow(pos, e))
			}
		}
	}
	if b.K == KSym && b.S == "e" {
		return Fn("exp", e)
	}
	if b.K == KSym && b.S == "i" && e.K == KNum && e.N.IsInt() {
		n, _ := ratInt64(new(big.Rat).SetInt(new(big.Int).Mod(e.N.Num(), big.NewInt(4))))
		switch n {
		case 0:
			return One
		case 1:
			return I
		case 2:
			return MinusOne
		}
		return Neg(I)
	}
	if e.K == KNum && e.N.IsInt() {
		switch b.K {
		case KPow:
			return Pow(b.A[0], Mul(b.A[1], e))
		case KMul:
			fs := make([]E, len(b.A))
			for i, f := range b.A {
				fs[i] = Pow(f, e)
			}
			return Mul(fs...)
		}
	}
	if e.K == KNum {
		if b.K == KFn && b.S == "exp" {
			return Fn("exp", Mul(b.A[0], e))
		}
		if b.K == KMul && b.A[0].K == KNum && b.A[0].N.Sign() > 0 {
			return Mul(Pow(b.A[0], e), Pow(Mul(b.A[1:]...), e))
		}
	}
	return &Expr{K: KPow, A: []E{b, e}}
}

// ---------- functions ----------

var oneArgFns = map[string]bool{"sin": true, "cos": true, "tan": true, "exp": true, "ln": true,
	"atan": true, "asin": true, "acos": true, "sinh": true, "cosh": true, "tanh": true}

var oddFns = map[string]bool{"sin": true, "tan": true, "atan": true, "asin": true, "sinh": true, "tanh": true}
var evenFns = map[string]bool{"cos": true, "cosh": true}

// IsKnownFn reports whether name is a built-in mathematical function.
func IsKnownFn(name string) bool { return oneArgFns[name] }

func negativeLead(a E) (E, bool) {
	if a.K == KNum && a.N.Sign() < 0 {
		return Neg(a), true
	}
	if a.K == KMul && a.A[0].K == KNum && a.A[0].N.Sign() < 0 {
		return Neg(a), true
	}
	return nil, false
}

// piMultiple returns c if a == c*pi.
func piMultiple(a E) (*big.Rat, bool) {
	if a.K == KSym && a.S == "pi" {
		return big.NewRat(1, 1), true
	}
	if a.K == KMul && len(a.A) == 2 && a.A[0].K == KNum && a.A[1].K == KSym && a.A[1].S == "pi" {
		return a.A[0].N, true
	}
	return nil, false
}

// exactTrig returns sin and cos of c*pi when they are exact surds from the 30/45-degree table.
func exactTrig(c *big.Rat) (s, co E, ok bool) {
	deg := new(big.Rat).Mul(c, big.NewRat(180, 1))
	if !deg.IsInt() {
		return nil, nil, false
	}
	a := new(big.Int).Mod(deg.Num(), big.NewInt(360)).Int64()
	var ref int64
	sSign, cSign := int64(1), int64(1)
	switch {
	case a <= 90:
		ref = a
	case a <= 180:
		ref, cSign = 180-a, -1
	case a <= 270:
		ref, sSign, cSign = a-180, -1, -1
	default:
		ref, sSign = 360-a, -1
	}
	table := map[int64][2]E{
		0:  {Zero, One},
		30: {Frac(1, 2), Mul(Frac(1, 2), Sqrt(Int(3)))},
		45: {Mul(Frac(1, 2), Sqrt(Int(2))), Mul(Frac(1, 2), Sqrt(Int(2)))},
		60: {Mul(Frac(1, 2), Sqrt(Int(3))), Frac(1, 2)},
		90: {One, Zero},
	}
	v, found := table[ref]
	if !found {
		return nil, nil, false
	}
	return Mul(Int(sSign), v[0]), Mul(Int(cSign), v[1]), true
}

// Fn builds a function application, applying exact identities for built-ins.
func Fn(name string, args ...E) E {
	raw := &Expr{K: KFn, S: name, A: args}
	if !oneArgFns[name] || len(args) != 1 {
		return raw
	}
	a := args[0]
	if a.K == KMat {
		return raw
	}
	if neg, ok := negativeLead(a); ok {
		if oddFns[name] {
			return Neg(Fn(name, neg))
		}
		if evenFns[name] {
			return Fn(name, neg)
		}
	}
	switch name {
	case "sin", "cos", "tan":
		if a.K == KNum && a.N.Sign() == 0 {
			if name == "cos" {
				return One
			}
			return Zero
		}
		if c, ok := piMultiple(a); ok {
			if s, co, ok := exactTrig(c); ok {
				switch name {
				case "sin":
					return s
				case "cos":
					return co
				}
				if co.K == KNum && co.N.Sign() == 0 {
					fail("tan is undefined at %s", a.String())
				}
				return Div(s, co)
			}
		}
	case "exp":
		if a.K == KNum {
			if a.N.Sign() == 0 {
				return One
			}
			if a.N.Cmp(big.NewRat(1, 1)) == 0 {
				return EulerE
			}
		}
		if a.K == KFn && a.S == "ln" {
			return a.A[0]
		}
		if a.K == KMul && len(a.A) == 2 && a.A[0].K == KNum && a.A[0].N.IsInt() && a.A[1].K == KFn && a.A[1].S == "ln" {
			return Pow(a.A[1].A[0], a.A[0])
		}
	case "ln":
		if a.K == KNum {
			if a.N.Sign() == 0 {
				fail("ln(0) is undefined")
			}
			if a.N.Cmp(big.NewRat(1, 1)) == 0 {
				return Zero
			}
		}
		if a.K == KSym && a.S == "e" {
			return One
		}
		if a.K == KFn && a.S == "exp" {
			return a.A[0]
		}
	case "atan":
		if a.K == KNum {
			if a.N.Sign() == 0 {
				return Zero
			}
			if a.N.Cmp(big.NewRat(1, 1)) == 0 {
				return Mul(Frac(1, 4), Pi)
			}
		}
	case "asin":
		if a.K == KNum {
			switch {
			case a.N.Sign() == 0:
				return Zero
			case a.N.Cmp(big.NewRat(1, 1)) == 0:
				return Mul(Frac(1, 2), Pi)
			case a.N.Cmp(big.NewRat(1, 2)) == 0:
				return Mul(Frac(1, 6), Pi)
			}
		}
	case "acos":
		if a.K == KNum {
			switch {
			case a.N.Sign() == 0:
				return Mul(Frac(1, 2), Pi)
			case a.N.Cmp(big.NewRat(1, 1)) == 0:
				return Zero
			case a.N.Cmp(big.NewRat(1, 2)) == 0:
				return Mul(Frac(1, 3), Pi)
			case a.N.Cmp(big.NewRat(-1, 1)) == 0:
				return Pi
			}
		}
	case "sinh", "tanh":
		if a.K == KNum && a.N.Sign() == 0 {
			return Zero
		}
	case "cosh":
		if a.K == KNum && a.N.Sign() == 0 {
			return One
		}
	}
	return raw
}

// ---------- expansion ----------

func mulDistribute(a, b E) E {
	if a.K != KAdd && b.K != KAdd {
		return Mul(a, b)
	}
	as, bs := terms(a), terms(b)
	out := make([]E, 0, len(as)*len(bs))
	for _, x := range as {
		for _, y := range bs {
			out = append(out, Mul(x, y))
		}
	}
	return Add(out...)
}

// Expand distributes products over sums and expands positive integer powers of sums.
func Expand(e E) E {
	switch e.K {
	case KAdd:
		out := make([]E, len(e.A))
		for i, t := range e.A {
			out[i] = Expand(t)
		}
		return Add(out...)
	case KMul:
		res := One
		for _, f := range e.A {
			res = mulDistribute(res, Expand(f))
		}
		return res
	case KPow:
		b, ex := Expand(e.A[0]), Expand(e.A[1])
		if n, ok := intExp(ex); ok && n > 1 && n <= 256 && b.K == KAdd {
			result, sq := One, b
			for k := n; k > 0; k >>= 1 {
				if k&1 == 1 {
					result = mulDistribute(result, sq)
				}
				if k > 1 {
					sq = mulDistribute(sq, sq)
				}
			}
			return result
		}
		return Pow(b, ex)
	case KFn, KMat:
		return Map(e, Expand)
	}
	return e
}
