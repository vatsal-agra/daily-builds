package cas

import (
	"math/big"
	"strings"
)

// String pretty-prints an expression in the same syntax the parser reads.
func (e E) String() string { return pr(e, 0) }

// precedence levels: 0 top, 1 add, 2 mul, 3 unary/neg, 4 pow, 5 atom
func paren(s string, need bool) string {
	if need {
		return "(" + s + ")"
	}
	return s
}

func ratStr(r *big.Rat) string { return r.RatString() }

func pr(e E, ctx int) string {
	switch e.K {
	case KNum:
		s := ratStr(e.N)
		if e.N.Sign() < 0 {
			return paren(s, ctx > 1)
		}
		return paren(s, !e.N.IsInt() && ctx >= 2)
	case KSym:
		return e.S
	case KAdd:
		var sb strings.Builder
		for i, t := range e.A {
			c, rest := splitCoeff(t)
			neg := c.Sign() < 0
			var body string
			if neg {
				body = pr(scale(new(big.Rat).Neg(c), rest), 1)
			} else {
				body = pr(t, 1)
			}
			if t.K == KNum {
				neg = t.N.Sign() < 0
				if neg {
					body = ratStr(new(big.Rat).Neg(t.N))
				} else {
					body = ratStr(t.N)
				}
			}
			switch {
			case i == 0 && neg:
				sb.WriteString("-" + body)
			case i == 0:
				sb.WriteString(body)
			case neg:
				sb.WriteString(" - " + body)
			default:
				sb.WriteString(" + " + body)
			}
		}
		return paren(sb.String(), ctx > 1)
	case KMul:
		return paren(prMul(e.A), ctx > 2)
	case KPow:
		if e.A[1].K == KNum && e.A[1].N.Sign() < 0 {
			return paren(prMul([]E{e}), ctx > 2)
		}
		if e.A[1].K == KNum && e.A[1].N.Cmp(big.NewRat(1, 2)) == 0 {
			return "sqrt(" + pr(e.A[0], 0) + ")"
		}
		base := pr(e.A[0], 5)
		if e.A[0].K == KFn && e.A[0].S == "exp" {
			base = "(" + base + ")"
		}
		ex := pr(e.A[1], 5)
		if e.A[1].K == KNum && e.A[1].N.IsInt() && e.A[1].N.Sign() >= 0 {
			ex = ratStr(e.A[1].N)
		}
		return paren(base+"^"+ex, ctx > 4)
	case KFn:
		if e.S == "exp" && len(e.A) == 1 {
			arg := e.A[0]
			if arg.K == KSym || (arg.K == KNum && arg.N.IsInt() && arg.N.Sign() >= 0) {
				return paren("e^"+pr(arg, 5), ctx > 4)
			}
			return paren("e^("+pr(arg, 0)+")", ctx > 4)
		}
		parts := make([]string, len(e.A))
		for i, a := range e.A {
			parts[i] = pr(a, 0)
		}
		return e.S + "(" + strings.Join(parts, ", ") + ")"
	case KMat:
		rows := make([]string, e.R)
		for i := 0; i < e.R; i++ {
			cells := make([]string, e.C)
			for j := 0; j < e.C; j++ {
				cells[j] = pr(e.A[i*e.C+j], 0)
			}
			rows[i] = "[" + strings.Join(cells, ", ") + "]"
		}
		return "[" + strings.Join(rows, ", ") + "]"
	}
	return "?"
}

// prMul prints a product, moving negative-exponent factors under a fraction bar.
func prMul(fs []E) string {
	coef := big.NewRat(1, 1)
	var num, den []string
	for _, f := range fs {
		switch {
		case f.K == KNum:
			coef.Mul(coef, f.N)
		case f.K == KPow && f.A[1].K == KNum && f.A[1].N.Sign() < 0:
			pos := Pow(f.A[0], Num(new(big.Rat).Neg(f.A[1].N)))
			s := pr(pos, 4)
			if pos.K == KPow && pos.A[1].K == KNum && pos.A[1].N.Cmp(big.NewRat(1, 2)) == 0 {
				s = pr(pos, 5)
			}
			den = append(den, s)
		default:
			num = append(num, pr(f, 3))
		}
	}
	sign := ""
	if coef.Sign() < 0 {
		sign = "-"
		coef.Neg(coef)
	}
	numCoef, denCoef := coef.Num().String(), coef.Denom().String()
	one := big.NewInt(1)
	if coef.Num().Cmp(one) != 0 || len(num) == 0 {
		num = append([]string{numCoef}, num...)
	}
	if coef.Denom().Cmp(one) != 0 {
		den = append([]string{denCoef}, den...)
	}
	n := strings.Join(num, "*")
	if len(den) == 0 {
		return sign + n
	}
	d := strings.Join(den, "*")
	if len(den) > 1 {
		d = "(" + d + ")"
	}
	return sign + n + "/" + d
}
