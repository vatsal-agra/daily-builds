package expr

import (
	"math"
	"sort"
)

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
		if n.Op == "*" || n.Op == "/" {
			if c := collectFactors(n); c != nil && !c.Equal(n) {
				return c
			}
		}
		if n.Op == "+" || n.Op == "-" {
			if c := collectTerms(n); c != nil {
				return c
			}
		}
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
			// (c*a)*a -> c*a^2
			if l.Kind == Bin && l.Op == "*" && l.R.Equal(r) {
				return B("*", l.L, B("^", r, C(2)))
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
			// (c*a)^k -> c^k * a^k for integer k
			if r.Kind == Const && r.Val == math.Trunc(r.Val) && l.Kind == Bin && l.Op == "*" && l.L.Kind == Const {
				return B("*", C(math.Pow(l.L.Val, r.Val)), B("^", l.R, r))
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

// ---- like-term collection:  x^3 - x - x  ->  x^3 - 2*x ----

type term struct {
	coef float64
	base *Node // nil = pure constant
}

func flattenSum(n *Node, sign float64, out *[]term) {
	switch {
	case n.Kind == Bin && n.Op == "+":
		flattenSum(n.L, sign, out)
		flattenSum(n.R, sign, out)
	case n.Kind == Bin && n.Op == "-":
		flattenSum(n.L, sign, out)
		flattenSum(n.R, -sign, out)
	case n.Kind == Un && n.Op == "neg":
		flattenSum(n.L, -sign, out)
	case n.Kind == Const:
		*out = append(*out, term{sign * n.Val, nil})
	case n.Kind == Bin && n.Op == "*" && n.L.Kind == Const:
		*out = append(*out, term{sign * n.L.Val, n.R})
	default:
		*out = append(*out, term{sign, n})
	}
}

// collectTerms merges terms with identical bases. It returns nil unless the
// number of terms strictly shrinks, so it cannot oscillate with other rules.
func collectTerms(n *Node) *Node {
	var ts []term
	flattenSum(n, 1, &ts)
	idx := map[string]int{}
	var merged []term
	var keys []string
	for _, t := range ts {
		k := "#const"
		if t.base != nil {
			k = t.base.String()
		}
		if i, ok := idx[k]; ok {
			merged[i].coef += t.coef
		} else {
			idx[k] = len(merged)
			merged = append(merged, t)
			keys = append(keys, k)
		}
	}
	if len(merged) >= len(ts) {
		return nil
	}
	var out *Node
	for _, t := range merged {
		if t.coef == 0 {
			continue
		}
		var piece *Node
		switch {
		case t.base == nil:
			piece = C(t.coef)
		case t.coef == 1:
			piece = t.base
		default:
			piece = B("*", C(t.coef), t.base)
		}
		if out == nil {
			out = piece
		} else {
			out = B("+", out, piece)
		}
	}
	if out == nil {
		return C(0)
	}
	return out
}

// ---- monomial normalisation:  m2/r/(c/m1)/r  ->  (1/c) * m1 * m2 / r^2 ----

type factors struct {
	coef  float64
	bases []*Node
	exps  []float64
	count int // number of factors before merging
}

func (f *factors) add(b *Node, e float64) {
	f.count++
	k := b.String()
	for i := range f.bases {
		if f.bases[i].String() == k {
			f.exps[i] += e
			return
		}
	}
	f.bases = append(f.bases, b)
	f.exps = append(f.exps, e)
}

func (f *factors) walk(n *Node, e float64) { // e is +1 (numerator) or -1 (denominator)
	switch {
	case n.Kind == Bin && n.Op == "*":
		f.walk(n.L, e)
		f.walk(n.R, e)
	case n.Kind == Bin && n.Op == "/":
		f.walk(n.L, e)
		f.walk(n.R, -e)
	case n.Kind == Un && n.Op == "neg":
		f.coef = -f.coef
		f.walk(n.L, e)
	case n.Kind == Const && (e == 1 || n.Val != 0):
		f.count++
		if e == 1 {
			f.coef *= n.Val
		} else {
			f.coef /= n.Val
		}
	case n.Kind == Bin && n.Op == "^" && n.R.Kind == Const:
		f.add(n.L, e*n.R.Val)
	default:
		f.add(n, e)
	}
}

// collectFactors merges repeated bases in a product/quotient. It returns nil
// unless something was actually merged or the result is cheaper to read.
func collectFactors(n *Node) *Node {
	f := &factors{coef: 1}
	f.walk(n, 1)
	var num, den *Node
	mul := func(acc, x *Node) *Node {
		if acc == nil {
			return x
		}
		return B("*", acc, x)
	}
	if f.coef != 1 && f.coef != 0 {
		num = C(f.coef) // constant leads the product: 2 * a * b
	}
	// canonical order (by printed form) so equal products print identically
	ord := make([]int, len(f.bases))
	for i := range ord {
		ord[i] = i
	}
	rank := func(n *Node) int { // plain variables first, then compound factors
		if n.Kind == Var {
			return 0
		}
		return 1
	}
	sort.SliceStable(ord, func(a, b int) bool {
		x, y := f.bases[ord[a]], f.bases[ord[b]]
		if rank(x) != rank(y) {
			return rank(x) < rank(y)
		}
		return x.String() < y.String()
	})
	for _, i := range ord {
		b, e := f.bases[i], f.exps[i]
		switch {
		case e == 0:
		case e == 1:
			num = mul(num, b)
		case e == -1:
			den = mul(den, b)
		case e > 0:
			num = mul(num, B("^", b, C(e)))
		default:
			den = mul(den, B("^", b, C(-e)))
		}
	}
	var out *Node
	coef := f.coef
	if coef == 0 {
		return C(0)
	}
	switch {
	case num == nil && den == nil:
		return C(1)
	case num == nil:
		out = B("/", C(1), den)
	case den == nil:
		out = num
	default:
		out = B("/", num, den)
	}
	_ = coef
	if len(f.bases) < f.count && (out.Complexity() <= n.Complexity()) || out.Complexity() < n.Complexity() {
		return out
	}
	return nil
}
