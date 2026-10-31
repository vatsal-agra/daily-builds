package cas

import "math/big"

// Diff differentiates e with respect to the symbol x.
func Diff(e E, x string) E {
	switch e.K {
	case KNum:
		return Zero
	case KSym:
		if e.S == x {
			return One
		}
		return Zero
	case KAdd:
		out := make([]E, len(e.A))
		for i, t := range e.A {
			out[i] = Diff(t, x)
		}
		return Add(out...)
	case KMul:
		var out []E
		for i := range e.A {
			d := Diff(e.A[i], x)
			if isNumVal(d, 0) {
				continue
			}
			fs := make([]E, len(e.A))
			copy(fs, e.A)
			fs[i] = d
			out = append(out, Mul(fs...))
		}
		return Add(out...)
	case KPow:
		u, v := e.A[0], e.A[1]
		if !Contains(v, x) {
			if !Contains(u, x) {
				return Zero
			}
			return Mul(v, Pow(u, Sub(v, One)), Diff(u, x))
		}
		if !Contains(u, x) {
			return Mul(e, Ln(u), Diff(v, x))
		}
		return Mul(e, Add(Mul(Diff(v, x), Ln(u)), Mul(v, Diff(u, x), Pow(u, MinusOne))))
	case KFn:
		if len(e.A) != 1 {
			fail("cannot differentiate %s with %d arguments", e.S, len(e.A))
		}
		u := e.A[0]
		du := Diff(u, x)
		if isNumVal(du, 0) {
			return Zero
		}
		var outer E
		switch e.S {
		case "sin":
			outer = Fn("cos", u)
		case "cos":
			outer = Neg(Fn("sin", u))
		case "tan":
			outer = Pow(Fn("cos", u), Int(-2))
		case "exp":
			outer = e
		case "ln":
			outer = Pow(u, MinusOne)
		case "atan":
			outer = Pow(Add(One, Pow(u, Int(2))), MinusOne)
		case "asin":
			outer = Pow(Sub(One, Pow(u, Int(2))), Frac(-1, 2))
		case "acos":
			outer = Neg(Pow(Sub(One, Pow(u, Int(2))), Frac(-1, 2)))
		case "sinh":
			outer = Fn("cosh", u)
		case "cosh":
			outer = Fn("sinh", u)
		case "tanh":
			outer = Sub(One, Pow(e, Int(2)))
		case "abs":
			outer = Mul(u, Pow(e, MinusOne))
		default:
			fail("don't know how to differentiate %s", e.S)
		}
		return Mul(outer, du)
	}
	fail("cannot differentiate this expression")
	return nil
}

// DiffN takes the n-th derivative.
func DiffN(e E, x string, n int) E {
	for i := 0; i < n; i++ {
		e = Diff(e, x)
	}
	return e
}

// Taylor returns the degree-n Taylor polynomial of e about x = a.
func Taylor(e E, x string, a E, n int) E {
	if n < 0 || n > 60 {
		fail("series order must be between 0 and 60")
	}
	var out []E
	cur := e
	fact := big.NewInt(1)
	for k := 0; k <= n; k++ {
		if k > 0 {
			cur = Diff(cur, x)
			fact.Mul(fact, big.NewInt(int64(k)))
		}
		if isNumVal(cur, 0) {
			continue
		}
		val := Sub1(cur, x, a)
		if isNumVal(val, 0) {
			continue
		}
		coef := Mul(val, Num(new(big.Rat).SetFrac(big.NewInt(1), fact)))
		out = append(out, Mul(coef, Pow(Sub(Sym(x), a), Int(int64(k)))))
	}
	return Add(out...)
}
