package cas

import (
	"math"
	"math/big"
)

// Inf is the symbol for positive infinity; negative infinity is -oo.
var Inf = Sym("oo")

func isPosInf(e E) bool { return e.K == KSym && e.S == "oo" }
func isNegInf(e E) bool {
	return e.K == KMul && len(e.A) == 2 && isNumVal(e.A[0], -1) && isPosInf(e.A[1])
}
func isInfinite(e E) bool { return isPosInf(e) || isNegInf(e) }

// Limit computes lim_{x -> a} e. dir is -1 (from the left), +1 (from the right) or 0 (two-sided);
// a may be oo or -oo. The result may be oo / -oo. It uses direct substitution, L'Hôpital's rule on
// 0/0 and oo/oo quotients (including products rewritten as quotients), the exp–log rewrite for
// powers, and numeric sign analysis at poles. It fails loudly when the limit does not exist or
// the form is beyond these rules.
func Limit(e E, x string, a E, dir int) E {
	if isPosInf(a) || isNegInf(a) {
		t := "_lim"
		sgn := 1
		if isNegInf(a) {
			sgn = -1
		}
		return limit(Sub1(e, x, Pow(Sym(t), MinusOne)), t, Zero, sgn, 0)
	}
	return limit(e, x, a, dir, 0)
}

func tryVal(f func() E) (v E, ok bool) {
	defer func() {
		if r := recover(); r != nil {
			if _, is := r.(MathError); is {
				v, ok = nil, false
				return
			}
			panic(r)
		}
	}()
	return f(), true
}

// signNear numerically determines the sign of e as x -> a (dir as in Limit); 0 means undetermined.
func signNear(e E, x string, a E, dir int) (int, bool) {
	av, err := EvalNum(a, nil)
	if err != nil || imag(av) != 0 {
		return 0, false
	}
	sides := []int{dir}
	if dir == 0 {
		sides = []int{-1, 1}
	}
	res := 0
	for _, s := range sides {
		votes := 0
		for _, h := range []float64{1e-4, 1e-5, 1e-6, 1e-7} {
			v, err := EvalReal(e, map[string]float64{x: real(av) + float64(s)*h})
			if err != nil || math.IsNaN(v) {
				continue
			}
			if v > 0 {
				votes++
			} else if v < 0 {
				votes--
			}
		}
		sg := 0
		if votes >= 3 {
			sg = 1
		} else if votes <= -3 {
			sg = -1
		}
		if sg == 0 || (res != 0 && sg != res) {
			return 0, false
		}
		res = sg
	}
	return res, true
}

func infOf(sign int) E {
	if sign > 0 {
		return Inf
	}
	return Neg(Inf)
}

func limit(e E, x string, a E, dir int, depth int) E {
	if depth > 9 {
		fail("limit: too many L'Hôpital steps")
	}
	if !Contains(e, x) {
		return e
	}
	if v, ok := tryVal(func() E { return Sub1(e, x, a) }); ok && !Contains(v, "oo") {
		if v.K != KFn || v.S != "eq" {
			return v
		}
	}
	switch e.K {
	case KAdd:
		if lq, ok := tryVal(func() E { return Together(e, x) }); ok && !Equal(lq, e) && lq.K != KAdd {
			return limit(lq, x, a, dir, depth+1)
		}
		var fin []E
		inf := 0
		if len(e.A) == 2 && (hasSqrt(e.A[0]) || hasSqrt(e.A[1])) {
			// oo - oo with a radical: multiply by the conjugate, (t1+t2) = (t1^2 - t2^2)/(t1 - t2)
			t1, t2 := e.A[0], e.A[1]
			num := Expand(Sub(Pow(t1, Int(2)), Pow(t2, Int(2))))
			l1, l2 := tryLimit(t1, x, a, dir, depth), tryLimit(t2, x, a, dir, depth)
			if l1 != nil && l2 != nil && isInfinite(l1) && isInfinite(l2) && isPosInf(l1) != isPosInf(l2) {
				return limit(Mul(num, Pow(Sub(t1, t2), MinusOne)), x, a, dir, depth+1)
			}
		}
		for _, t := range e.A {
			l := limit(t, x, a, dir, depth+1)
			switch {
			case isPosInf(l):
				if inf == -1 {
					fail("limit is an indeterminate form (oo - oo)")
				}
				inf = 1
			case isNegInf(l):
				if inf == 1 {
					fail("limit is an indeterminate form (oo - oo)")
				}
				inf = -1
			default:
				fin = append(fin, l)
			}
		}
		if inf != 0 {
			return infOf(inf)
		}
		return Add(fin...)
	case KFn:
		if len(e.A) == 1 {
			l := limit(e.A[0], x, a, dir, depth+1)
			if isInfinite(l) {
				return fnAtInfinity(e.S, isPosInf(l))
			}
			if v, ok := tryVal(func() E { return Fn(e.S, l) }); ok {
				return v
			}
			if e.S == "ln" && isNumVal(l, 0) {
				return Neg(Inf)
			}
			fail("limit: %s is undefined at the limiting value %s", e.S, l.String())
		}
	}
	// quotients (0/0, oo/oo, poles)
	n, d := NumDen(e)
	if !isNumVal(d, 1) {
		return limitQuotient(e, n, d, x, a, dir, depth)
	}
	switch e.K {
	case KMul:
		return limitProduct(e, x, a, dir, depth)
	case KPow:
		return limitPower(e, x, a, dir, depth)
	}
	fail("limit of %s could not be determined", e.String())
	return nil
}

func fnAtInfinity(name string, pos bool) E {
	switch name {
	case "exp", "sinh", "cosh":
		if pos || name == "cosh" {
			return Inf
		}
		if name == "sinh" {
			return Neg(Inf)
		}
		return Zero
	case "ln":
		if pos {
			return Inf
		}
	case "atan":
		if pos {
			return Mul(Frac(1, 2), Pi)
		}
		return Mul(Frac(-1, 2), Pi)
	case "tanh":
		if pos {
			return One
		}
		return MinusOne
	}
	fail("limit: %s has no limit at infinity", name)
	return nil
}

func limitQuotient(e, n, d E, x string, a E, dir, depth int) E {
	nv, nOK := tryVal(func() E { return Sub1(n, x, a) })
	dv, dOK := tryVal(func() E { return Sub1(d, x, a) })
	nl, dl := n, d
	if !nOK {
		nl = limit(n, x, a, dir, depth+1)
	} else {
		nl = nv
	}
	if !dOK {
		dl = limit(d, x, a, dir, depth+1)
	} else {
		dl = dv
	}
	nInf, dInf := isInfinite(nl), isInfinite(dl)
	nZero, dZero := isNumVal(nl, 0), isNumVal(dl, 0)
	switch {
	case (nZero && dZero) || (nInf && dInf):
		return lhopital(n, d, x, a, dir, depth)
	case dInf && !nInf:
		return Zero
	case nInf && !dInf && !dZero:
		s, ok := signNear(e, x, a, dir)
		if !ok {
			fail("limit does not exist (sign is not determined)")
		}
		return infOf(s)
	case dZero && !nZero && !nInf:
		s, ok := signNear(e, x, a, dir)
		if !ok {
			fail("limit does not exist (the one-sided limits differ)")
		}
		return infOf(s)
	}
	return Mul(nl, Pow(dl, MinusOne))
}

// lhopital applies L'Hôpital's rule to n/d. If differentiating as given does not terminate (an essential
// singularity such as e^(-1/t)/t), it retries on the inverted quotient (1/d)/(1/n).
func lhopital(n, d E, x string, a E, dir, depth int) E {
	if v, ok := tryVal(func() E { return limit(Mul(Diff(n, x), Pow(Diff(d, x), MinusOne)), x, a, dir, depth+1) }); ok {
		return v
	}
	ni, di := Pow(d, MinusOne), Pow(n, MinusOne)
	return limit(Mul(Diff(ni, x), Pow(Diff(di, x), MinusOne)), x, a, dir, depth+1)
}

func limitProduct(e E, x string, a E, dir, depth int) E {
	var zero, infinite, fin []E
	for _, f := range e.A {
		if !Contains(f, x) {
			fin = append(fin, f)
			continue
		}
		l := limit(f, x, a, dir, depth+1)
		switch {
		case isInfinite(l):
			infinite = append(infinite, f)
		case isNumVal(l, 0):
			zero = append(zero, f)
		default:
			fin = append(fin, l)
		}
	}
	if len(zero) > 0 && len(infinite) > 0 {
		w, r := Mul(infinite...), Mul(zero...)
		return lhopital(w, Pow(r, MinusOne), x, a, dir, depth)
	}
	if len(zero) > 0 {
		return Zero
	}
	if len(infinite) > 0 {
		s, ok := signNear(e, x, a, dir)
		if !ok {
			fail("limit does not exist (sign is not determined)")
		}
		return infOf(s)
	}
	return Mul(fin...)
}

func limitPower(e E, x string, a E, dir, depth int) E {
	u, v := e.A[0], e.A[1]
	if !Contains(v, x) {
		lu := limit(u, x, a, dir, depth+1)
		if isInfinite(lu) {
			if v.K == KNum && v.N.Sign() < 0 {
				return Zero
			}
			s, ok := signNear(e, x, a, dir)
			if !ok {
				fail("limit does not exist")
			}
			return infOf(s)
		}
		return Pow(lu, v)
	}
	// exp-log rewrite: u^v = exp(v ln u)
	l := limit(Mul(v, Ln(u)), x, a, dir, depth+1)
	switch {
	case isPosInf(l):
		return Inf
	case isNegInf(l):
		return Zero
	}
	return Exp(l)
}

func hasSqrt(e E) bool {
	if e.K == KPow && e.A[1].K == KNum && e.A[1].N.Cmp(big.NewRat(1, 2)) == 0 {
		return true
	}
	for _, a := range e.A {
		if hasSqrt(a) {
			return true
		}
	}
	return false
}

func tryLimit(e E, x string, a E, dir, depth int) E {
	v, _ := tryVal(func() E { return limit(e, x, a, dir, depth+1) })
	return v
}
