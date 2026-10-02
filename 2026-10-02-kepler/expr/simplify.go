package expr

import "math"

// Simplify applies constant folding and algebraic identities bottom-up until
// a fixed point. It never changes the function computed (on its domain).
func Simplify(n *Node) *Node {
	for i := 0; i < 20; i++ {
		m := simp(n.Clone())
		if m.Equal(n) {
			return m
		}
		n = m
	}
	return n
}

func isC(n *Node, v float64) bool { return n.Kind == Const && n.Val == v }

func simp(n *Node) *Node {
	if n.L != nil {
		n.L = simp(n.L)
	}
	if n.R != nil {
		n.R = simp(n.R)
	}
	switch n.Kind {
	case Un:
		if n.L.Kind == Const {
			if v := n.Eval(nil); !math.IsNaN(v) && !math.IsInf(v, 0) {
				return C(v)
			}
			return n
		}
		if n.Op == "neg" {
			if n.L.Kind == Un && n.L.Op == "neg" {
				return n.L.L
			}
		}
		if n.Op == "sqrt" && n.L.Kind == Bin && n.L.Op == "^" && isC(n.L.R, 2) {
			return U("abs", n.L.L)
		}
		if n.Op == "exp" && n.L.Kind == Un && n.L.Op == "log" {
			return n.L.L
		}
		if n.Op == "log" && n.L.Kind == Un && n.L.Op == "exp" {
			return n.L.L
		}
		if n.Op == "abs" && n.L.Kind == Un && n.L.Op == "abs" {
			return n.L
		}
	case Bin:
		if n.L.Kind == Const && n.R.Kind == Const {
			if v := n.Eval(nil); !math.IsNaN(v) && !math.IsInf(v, 0) {
				return C(v)
			}
			return n
		}
		l, r := n.L, n.R
		switch n.Op {
		case "+":
			if isC(l, 0) {
				return r
			}
			if isC(r, 0) {
				return l
			}
			if l.Equal(r) {
				return B("*", C(2), l)
			}
			if r.Kind == Un && r.Op == "neg" {
				return B("-", l, r.L)
			}
			if r.Kind == Const && r.Val < 0 {
				return B("-", l, C(-r.Val))
			}
			// (a + c1) + c2 -> a + (c1+c2)
			if r.Kind == Const && l.Kind == Bin && l.Op == "+" && l.R.Kind == Const {
				return B("+", l.L, C(l.R.Val+r.Val))
			}
		case "-":
			if isC(r, 0) {
				return l
			}
			if isC(l, 0) {
				return U("neg", r)
			}
			if l.Equal(r) {
				return C(0)
			}
			if r.Kind == Un && r.Op == "neg" {
				return B("+", l, r.L)
			}
			if r.Kind == Const && r.Val < 0 {
				return B("+", l, C(-r.Val))
			}
		case "*":
			if isC(l, 0) || isC(r, 0) {
				return C(0)
			}
			if isC(l, 1) {
				return r
			}
			if isC(r, 1) {
				return l
			}
			if isC(l, -1) {
				return U("neg", r)
			}
			if isC(r, -1) {
				return U("neg", l)
			}
			if r.Kind == Const && l.Kind != Const { // constants to the left
				return B("*", r, l)
			}
			// c1 * (c2 * a) -> (c1c2) * a
			if l.Kind == Const && r.Kind == Bin && r.Op == "*" && r.L.Kind == Const {
				return B("*", C(l.Val*r.L.Val), r.R)
			}
			if l.Equal(r) {
				return B("^", l, C(2))
			}
			if l.Kind == Un && l.Op == "neg" && r.Kind == Un && r.Op == "neg" {
				return B("*", l.L, r.L)
			}
			// x * x^n -> x^(n+1) when n const
			if r.Kind == Bin && r.Op == "^" && r.R.Kind == Const && r.L.Equal(l) {
				return B("^", l, C(r.R.Val+1))
			}
		case "/":
			if isC(r, 1) {
				return l
			}
			if isC(l, 0) && !isC(r, 0) {
				return C(0)
			}
			if l.Equal(r) && !isC(r, 0) {
				return C(1)
			}
			if r.Kind == Const && r.Val != 0 {
				return B("*", C(1/r.Val), l)
			}
		case "^":
			if isC(r, 1) {
				return l
			}
			if isC(r, 0) {
				return C(1)
			}
			if isC(l, 1) {
				return C(1)
			}
			if l.Kind == Bin && l.Op == "^" && l.R.Kind == Const && r.Kind == Const {
				// (a^p)^q = a^(pq) only safe when p is even-int/q int; restrict to both integers
				if l.R.Val == math.Trunc(l.R.Val) && r.Val == math.Trunc(r.Val) {
					return B("^", l.L, C(l.R.Val*r.Val))
				}
			}
		}
	}
	return n
}
