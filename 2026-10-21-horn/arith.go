package main

import (
	"math"
	"math/big"
	"math/bits"
	"math/rand"
	"time"
)

var startTime = time.Now()

func toBig(t Term) *big.Int {
	switch x := t.(type) {
	case Int:
		return big.NewInt(int64(x))
	case *big.Int:
		return x
	}
	return nil
}

func toFloat(t Term) float64 {
	switch x := t.(type) {
	case Int:
		return float64(x)
	case *big.Int:
		f, _ := new(big.Float).SetInt(x).Float64()
		return f
	case Float:
		return float64(x)
	}
	return 0
}

func isInt(t Term) bool {
	switch t.(type) {
	case Int, *big.Int:
		return true
	}
	return false
}

func checkFloat(f float64) (Term, error) {
	if math.IsInf(f, 0) {
		return nil, evalErr("float_overflow")
	}
	if math.IsNaN(f) {
		return nil, evalErr("undefined")
	}
	return Float(f), nil
}

func (m *Machine) eval(t Term) (Term, error) {
	t = deref(t)
	switch x := t.(type) {
	case Int, Float, *big.Int:
		return t, nil
	case *Var:
		return nil, instErr()
	case *Atom:
		switch x.Name {
		case "pi":
			return Float(math.Pi), nil
		case "e":
			return Float(math.E), nil
		case "inf", "infinite":
			return Float(math.Inf(1)), nil
		case "nan":
			return Float(math.NaN()), nil
		case "epsilon":
			return Float(2.220446049250313e-16), nil
		case "max_tagged_integer":
			return Int(1<<60 - 1), nil
		case "min_tagged_integer":
			return Int(-(1 << 60)), nil
		case "max_integer":
			return Int(math.MaxInt64), nil
		case "min_integer":
			return Int(math.MinInt64), nil
		case "random":
			return Float(rand.Float64()), nil
		case "random_float":
			return Float(rand.Float64()), nil
		case "cputime":
			return Float(time.Since(startTime).Seconds()), nil
		case "realtime":
			return Int(time.Now().Unix()), nil
		case "[]":
		}
		return nil, typeErr("evaluable", pi(x, 0))
	case *Compound:
		if x.Fn == atDot && len(x.Args) == 2 {
			if deref(x.Args[1]) == Term(atNil) {
				return m.eval(x.Args[0])
			}
			return nil, typeErr("evaluable", x)
		}
		if len(x.Args) == 1 {
			a, err := m.eval(x.Args[0])
			if err != nil {
				return nil, err
			}
			return m.eval1(x, a)
		}
		if len(x.Args) == 2 {
			a, err := m.eval(x.Args[0])
			if err != nil {
				return nil, err
			}
			b, err := m.eval(x.Args[1])
			if err != nil {
				return nil, err
			}
			return m.eval2(x, a, b)
		}
		return nil, typeErr("evaluable", pi(x.Fn, len(x.Args)))
	}
	return nil, typeErr("evaluable", t)
}

func needInt(t Term) error {
	if !isInt(t) {
		return typeErr("integer", t)
	}
	return nil
}

func (m *Machine) eval1(x *Compound, a Term) (Term, error) {
	name := x.Fn.Name
	switch name {
	case "-":
		switch v := a.(type) {
		case Int:
			if v == math.MinInt64 {
				return normBig(new(big.Int).Neg(big.NewInt(int64(v)))), nil
			}
			return -v, nil
		case *big.Int:
			return normBig(new(big.Int).Neg(v)), nil
		case Float:
			return -v, nil
		}
	case "+":
		return a, nil
	case "abs":
		switch v := a.(type) {
		case Int:
			if v < 0 {
				return m.eval1(&Compound{Fn: atMinus, Args: x.Args}, a)
			}
			return v, nil
		case *big.Int:
			return normBig(new(big.Int).Abs(v)), nil
		case Float:
			return Float(math.Abs(float64(v))), nil
		}
	case "sign":
		switch v := a.(type) {
		case Int:
			if v > 0 {
				return Int(1), nil
			} else if v < 0 {
				return Int(-1), nil
			}
			return Int(0), nil
		case *big.Int:
			return Int(v.Sign()), nil
		case Float:
			if v > 0 {
				return Float(1), nil
			} else if v < 0 {
				return Float(-1), nil
			}
			return Float(0), nil
		}
	case "min", "max":
	case "sqrt":
		f := toFloat(a)
		if f < 0 {
			return nil, evalErr("undefined")
		}
		return Float(math.Sqrt(f)), nil
	case "sin":
		return checkFloat(math.Sin(toFloat(a)))
	case "cos":
		return checkFloat(math.Cos(toFloat(a)))
	case "tan":
		return checkFloat(math.Tan(toFloat(a)))
	case "asin":
		f := toFloat(a)
		if f < -1 || f > 1 {
			return nil, evalErr("undefined")
		}
		return Float(math.Asin(f)), nil
	case "acos":
		f := toFloat(a)
		if f < -1 || f > 1 {
			return nil, evalErr("undefined")
		}
		return Float(math.Acos(f)), nil
	case "atan":
		return Float(math.Atan(toFloat(a))), nil
	case "sinh":
		return checkFloat(math.Sinh(toFloat(a)))
	case "cosh":
		return checkFloat(math.Cosh(toFloat(a)))
	case "tanh":
		return checkFloat(math.Tanh(toFloat(a)))
	case "asinh":
		return checkFloat(math.Asinh(toFloat(a)))
	case "acosh":
		return checkFloat(math.Acosh(toFloat(a)))
	case "atanh":
		return checkFloat(math.Atanh(toFloat(a)))
	case "exp":
		return checkFloat(math.Exp(toFloat(a)))
	case "log":
		f := toFloat(a)
		if f <= 0 {
			if f == 0 && !isInt(a) {
				return nil, evalErr("undefined")
			}
			return nil, evalErr("undefined")
		}
		return Float(math.Log(f)), nil
	case "log2":
		f := toFloat(a)
		if f <= 0 {
			return nil, evalErr("undefined")
		}
		return Float(math.Log2(f)), nil
	case "float":
		return Float(toFloat(a)), nil
	case "integer":
		if isInt(a) {
			return a, nil
		}
		return floatToInt(math.Round(toFloat(a)))
	case "float_integer_part":
		return Float(math.Trunc(toFloat(a))), nil
	case "float_fractional_part":
		f := toFloat(a)
		return Float(f - math.Trunc(f)), nil
	case "truncate":
		if isInt(a) {
			return a, nil
		}
		return floatToInt(math.Trunc(toFloat(a)))
	case "round":
		if isInt(a) {
			return a, nil
		}
		return floatToInt(math.Round(toFloat(a)))
	case "ceiling":
		if isInt(a) {
			return a, nil
		}
		return floatToInt(math.Ceil(toFloat(a)))
	case "floor":
		if isInt(a) {
			return a, nil
		}
		return floatToInt(math.Floor(toFloat(a)))
	case "\\":
		if err := needInt(a); err != nil {
			return nil, err
		}
		return normBig(new(big.Int).Not(toBig(a))), nil
	case "msb":
		if err := needInt(a); err != nil {
			return nil, err
		}
		return Int(toBig(a).BitLen() - 1), nil
	case "succ":
		return m.eval2(&Compound{Fn: atPlus}, a, Int(1))
	case "random":
		if err := needInt(a); err != nil {
			return nil, err
		}
		n, _ := a.(Int)
		if n <= 0 {
			return nil, evalErr("undefined")
		}
		return Int(rand.Int63n(int64(n))), nil
	case "random_float":
		return Float(rand.Float64()), nil
	case "cot":
		return checkFloat(1 / math.Tan(toFloat(a)))
	case "acot":
		return checkFloat(math.Atan(1 / toFloat(a)))
	case "trig":
	}
	return nil, typeErr("evaluable", pi(x.Fn, 1))
}

func floatToInt(f float64) (Term, error) {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return nil, evalErr("undefined")
	}
	if f >= -9.2e18 && f <= 9.2e18 {
		return Int(int64(f)), nil
	}
	b, _ := new(big.Float).SetFloat64(f).Int(nil)
	return normBig(b), nil
}

func addInt(a, b Int) Term {
	c := a + b
	if (a > 0 && b > 0 && c < 0) || (a < 0 && b < 0 && c >= 0) {
		return normBig(new(big.Int).Add(big.NewInt(int64(a)), big.NewInt(int64(b))))
	}
	return c
}

func subInt(a, b Int) Term {
	c := a - b
	if (a >= 0 && b < 0 && c < 0) || (a < 0 && b > 0 && c >= 0) {
		return normBig(new(big.Int).Sub(big.NewInt(int64(a)), big.NewInt(int64(b))))
	}
	return c
}

func mulInt(a, b Int) Term {
	hi, lo := bits.Mul64(uint64(absI(a)), uint64(absI(b)))
	neg := (a < 0) != (b < 0)
	if hi == 0 && lo <= math.MaxInt64 {
		if neg {
			return Int(-int64(lo))
		}
		return Int(int64(lo))
	}
	return normBig(new(big.Int).Mul(big.NewInt(int64(a)), big.NewInt(int64(b))))
}

func absI(a Int) Int {
	if a < 0 {
		return -a
	}
	return a
}

func floorDivBig(a, b *big.Int) *big.Int {
	q, r := new(big.Int).QuoRem(a, b, new(big.Int))
	if r.Sign() != 0 && (r.Sign() < 0) != (b.Sign() < 0) {
		q.Sub(q, big.NewInt(1))
	}
	return q
}

func intPow(a, b Term) (Term, error) {
	bb := toBig(b)
	ab := toBig(a)
	if bb.Sign() < 0 {
		switch {
		case ab.IsInt64() && ab.Int64() == 1:
			return Int(1), nil
		case ab.IsInt64() && ab.Int64() == -1:
			if bb.Bit(0) == 0 {
				return Int(1), nil
			}
			return Int(-1), nil
		case ab.Sign() == 0:
			return nil, evalErr("zero_divisor")
		}
		return nil, typeErr("float", a)
	}
	if !bb.IsInt64() || bb.Int64() > 10_000_000 && ab.BitLen() > 1 {
		return nil, throwTerm(mk("resource_error", mkAtom("memory")), nil)
	}
	return normBig(new(big.Int).Exp(ab, bb, nil)), nil
}

func (m *Machine) eval2(x *Compound, a, b Term) (Term, error) {
	name := x.Fn.Name
	bothInt := isInt(a) && isInt(b)
	ai, aok := a.(Int)
	bi, bok := b.(Int)
	small := aok && bok
	switch name {
	case "+":
		if small {
			return addInt(ai, bi), nil
		}
		if bothInt {
			return normBig(new(big.Int).Add(toBig(a), toBig(b))), nil
		}
		return checkFloat(toFloat(a) + toFloat(b))
	case "-":
		if small {
			return subInt(ai, bi), nil
		}
		if bothInt {
			return normBig(new(big.Int).Sub(toBig(a), toBig(b))), nil
		}
		return checkFloat(toFloat(a) - toFloat(b))
	case "*":
		if small {
			return mulInt(ai, bi), nil
		}
		if bothInt {
			return normBig(new(big.Int).Mul(toBig(a), toBig(b))), nil
		}
		return checkFloat(toFloat(a) * toFloat(b))
	case "/":
		if bothInt {
			bb := toBig(b)
			if bb.Sign() == 0 {
				return nil, evalErr("zero_divisor")
			}
			q, r := new(big.Int).QuoRem(toBig(a), bb, new(big.Int))
			if r.Sign() == 0 {
				return normBig(q), nil
			}
			return checkFloat(toFloat(a) / toFloat(b))
		}
		if toFloat(b) == 0 {
			return nil, evalErr("zero_divisor")
		}
		return checkFloat(toFloat(a) / toFloat(b))
	case "//", "mod", "rem", "div", "gcd", "<<", ">>", "/\\", "\\/", "xor":
		if err := needInt(a); err != nil {
			return nil, err
		}
		if err := needInt(b); err != nil {
			return nil, err
		}
		return intOp(name, a, b)
	case "min":
		if cmpNum(a, b) <= 0 {
			return a, nil
		}
		return b, nil
	case "max":
		if cmpNum(a, b) >= 0 {
			return a, nil
		}
		return b, nil
	case "**":
		if bothInt {
			return intPow(a, b)
		}
		return checkFloat(math.Pow(toFloat(a), toFloat(b)))
	case "^":
		if bothInt {
			return intPow(a, b)
		}
		return checkFloat(math.Pow(toFloat(a), toFloat(b)))
	case "atan2", "atan":
		return Float(math.Atan2(toFloat(a), toFloat(b))), nil
	case "copysign":
		return Float(math.Copysign(toFloat(a), toFloat(b))), nil
	case "log":
		if toFloat(a) <= 0 || toFloat(b) <= 0 {
			return nil, evalErr("undefined")
		}
		return Float(math.Log(toFloat(b)) / math.Log(toFloat(a))), nil
	case "truncate":
	case "random":
	}
	return nil, typeErr("evaluable", pi(x.Fn, 2))
}

func intOp(name string, a, b Term) (Term, error) {
	if ai, ok := a.(Int); ok {
		if bi, ok := b.(Int); ok && !(ai == math.MinInt64) {
			switch name {
			case "//":
				if bi == 0 {
					return nil, evalErr("zero_divisor")
				}
				return Int(int64(ai) / int64(bi)), nil
			case "rem":
				if bi == 0 {
					return nil, evalErr("zero_divisor")
				}
				return Int(int64(ai) % int64(bi)), nil
			case "mod":
				if bi == 0 {
					return nil, evalErr("zero_divisor")
				}
				r := ai % bi
				if r != 0 && (r < 0) != (bi < 0) {
					r += bi
				}
				return r, nil
			case "div":
				if bi == 0 {
					return nil, evalErr("zero_divisor")
				}
				q := ai / bi
				if (ai%bi != 0) && ((ai < 0) != (bi < 0)) {
					q--
				}
				return q, nil
			case "/\\":
				return ai & bi, nil
			case "\\/":
				return ai | bi, nil
			case "xor":
				return ai ^ bi, nil
			case ">>":
				if bi >= 0 {
					if bi > 63 {
						bi = 63
					}
					return ai >> uint(bi), nil
				}
			}
		}
	}
	x, y := toBig(a), toBig(b)
	switch name {
	case "//":
		if y.Sign() == 0 {
			return nil, evalErr("zero_divisor")
		}
		return normBig(new(big.Int).Quo(x, y)), nil
	case "rem":
		if y.Sign() == 0 {
			return nil, evalErr("zero_divisor")
		}
		return normBig(new(big.Int).Rem(x, y)), nil
	case "mod":
		if y.Sign() == 0 {
			return nil, evalErr("zero_divisor")
		}
		r := new(big.Int).Rem(x, y)
		if r.Sign() != 0 && (r.Sign() < 0) != (y.Sign() < 0) {
			r.Add(r, y)
		}
		return normBig(r), nil
	case "div":
		if y.Sign() == 0 {
			return nil, evalErr("zero_divisor")
		}
		return normBig(floorDivBig(x, y)), nil
	case "gcd":
		return normBig(new(big.Int).GCD(nil, nil, new(big.Int).Abs(x), new(big.Int).Abs(y))), nil
	case "/\\":
		return normBig(new(big.Int).And(x, y)), nil
	case "\\/":
		return normBig(new(big.Int).Or(x, y)), nil
	case "xor":
		return normBig(new(big.Int).Xor(x, y)), nil
	case "<<", ">>":
		if !y.IsInt64() || y.Int64() > 1<<24 || y.Int64() < -(1<<24) {
			return nil, throwTerm(mk("resource_error", mkAtom("memory")), nil)
		}
		s := y.Int64()
		if name == ">>" {
			s = -s
		}
		if s >= 0 {
			return normBig(new(big.Int).Lsh(x, uint(s))), nil
		}
		return normBig(new(big.Int).Rsh(x, uint(-s))), nil
	}
	return nil, typeErr("evaluable", mk(name))
}

// numCompare compares two evaluated numbers.
func numCompare(a, b Term) int { return cmpNum(a, b) }
