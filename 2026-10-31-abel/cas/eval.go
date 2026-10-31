package cas

import (
	"math"
	"math/big"
	"math/cmplx"
)

// EvalNum evaluates e numerically (complex128) with the given variable bindings.
func EvalNum(e E, env map[string]complex128) (v complex128, err error) {
	err = Guard(func() { v = evalC(e, env) })
	return
}

func ratToC(r *big.Rat) complex128 {
	f, _ := r.Float64()
	return complex(f, 0)
}

func evalC(e E, env map[string]complex128) complex128 {
	switch e.K {
	case KNum:
		return ratToC(e.N)
	case KSym:
		switch e.S {
		case "pi":
			return complex(math.Pi, 0)
		case "e":
			return complex(math.E, 0)
		case "i":
			return 1i
		}
		if v, ok := env[e.S]; ok {
			return v
		}
		fail("unbound variable %q", e.S)
	case KAdd:
		var s complex128
		for _, t := range e.A {
			s += evalC(t, env)
		}
		return s
	case KMul:
		p := complex(1, 0)
		for _, t := range e.A {
			p *= evalC(t, env)
		}
		return p
	case KPow:
		b, x := evalC(e.A[0], env), evalC(e.A[1], env)
		if imag(x) == 0 && real(x) == math.Trunc(real(x)) && math.Abs(real(x)) <= 64 {
			n := int(real(x))
			r := complex(1, 0)
			for k := 0; k < abs(n); k++ {
				r *= b
			}
			if n < 0 {
				return 1 / r
			}
			return r
		}
		if imag(b) == 0 && real(b) < 0 && imag(x) == 0 {
			// real odd roots of negatives, e.g. (-8)^(1/3), are returned as the real root
			if n, d, ok := smallFrac(real(x)); ok && d%2 == 1 {
				v := math.Pow(-real(b), real(x))
				if n%2 == 0 {
					return complex(v, 0)
				}
				return complex(-v, 0)
			}
		}
		return cmplx.Pow(b, x)
	case KFn:
		if len(e.A) != 1 {
			fail("cannot evaluate %s", e.S)
		}
		a := evalC(e.A[0], env)
		switch e.S {
		case "sin":
			return cmplx.Sin(a)
		case "cos":
			return cmplx.Cos(a)
		case "tan":
			return cmplx.Tan(a)
		case "exp":
			return cmplx.Exp(a)
		case "ln":
			return cmplx.Log(a)
		case "atan":
			return cmplx.Atan(a)
		case "asin":
			return cmplx.Asin(a)
		case "acos":
			return cmplx.Acos(a)
		case "sinh":
			return cmplx.Sinh(a)
		case "cosh":
			return cmplx.Cosh(a)
		case "tanh":
			return cmplx.Tanh(a)
		}
		fail("cannot evaluate unknown function %q", e.S)
	case KMat:
		fail("cannot evaluate a matrix numerically")
	}
	return 0
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func smallFrac(x float64) (n, d int, ok bool) {
	for d = 1; d <= 12; d++ {
		v := x * float64(d)
		if math.Abs(v-math.Round(v)) < 1e-12 {
			return int(math.Round(v)), d, true
		}
	}
	return 0, 0, false
}

// EvalReal evaluates to a float64, failing if the result is not (nearly) real.
func EvalReal(e E, env map[string]float64) (float64, error) {
	cenv := make(map[string]complex128, len(env))
	for k, v := range env {
		cenv[k] = complex(v, 0)
	}
	v, err := EvalNum(e, cenv)
	if err != nil {
		return 0, err
	}
	if math.Abs(imag(v)) > 1e-9*(1+math.Abs(real(v))) {
		return 0, MathError("result is not real")
	}
	return real(v), nil
}
