package elab

import (
	"math/big"

	"gatecraft/internal/aig"
	"gatecraft/internal/hdl"
)

// state is the symbolic-execution environment of one procedural block.
type state struct {
	cur     map[*signal][]aig.Lit // values visible to reads
	nxt     map[*signal][]aig.Lit // pending non-blocking values (clocked blocks)
	kind    map[*signal]byte      // 'b' or 'n' – assignment style used per register
	consts  map[string]*big.Int   // integer loop variables
	clocked bool
}

func (st *state) clone() *state {
	n := &state{cur: map[*signal][]aig.Lit{}, kind: st.kind, consts: st.consts, clocked: st.clocked}
	for k, v := range st.cur {
		n.cur[k] = append([]aig.Lit(nil), v...)
	}
	if st.nxt != nil {
		n.nxt = map[*signal][]aig.Lit{}
		for k, v := range st.nxt {
			n.nxt[k] = append([]aig.Lit(nil), v...)
		}
	}
	return n
}

func bitlen32(v *big.Int) int {
	n := v.BitLen()
	if n < 32 {
		return 32
	}
	return n
}

func constLookup(c *ctx, st *state, name string) (*big.Int, bool) {
	if st != nil {
		if v, ok := st.consts[name]; ok {
			return v, true
		}
	}
	if v, ok := c.params[name]; ok {
		return v, true
	}
	return nil, false
}

// ------------------------------------------------------------------ constant evaluation

// tryConst evaluates e at compile time (arbitrary precision); ok=false if it depends on signals.
func (c *ctx) tryConst(st *state, e hdl.Expr) (*big.Int, bool) {
	switch e := e.(type) {
	case *hdl.Number:
		return new(big.Int).Set(e.Val), true
	case *hdl.Ident:
		return constLookup(c, st, e.Name)
	case *hdl.Unary:
		x, ok := c.tryConst(st, e.X)
		if !ok {
			return nil, false
		}
		switch e.Op {
		case "-":
			return new(big.Int).Neg(x), true
		case "+":
			return x, true
		case "!":
			return b2i(x.Sign() == 0), true
		case "~":
			w := c.selfWidth(st, e.X)
			mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(w)), big.NewInt(1))
			return new(big.Int).AndNot(mask, x), true
		}
		return nil, false
	case *hdl.Binary:
		l, ok1 := c.tryConst(st, e.L)
		r, ok2 := c.tryConst(st, e.R)
		if !ok1 || !ok2 {
			return nil, false
		}
		z := new(big.Int)
		switch e.Op {
		case "+":
			return z.Add(l, r), true
		case "-":
			return z.Sub(l, r), true
		case "*":
			return z.Mul(l, r), true
		case "/":
			if r.Sign() == 0 {
				c.fail(e.At, "division by zero in constant expression")
			}
			return z.Quo(l, r), true
		case "%":
			if r.Sign() == 0 {
				c.fail(e.At, "modulo by zero in constant expression")
			}
			return z.Rem(l, r), true
		case "&":
			return z.And(l, r), true
		case "|":
			return z.Or(l, r), true
		case "^":
			return z.Xor(l, r), true
		case "<<":
			if r.Sign() < 0 || r.BitLen() > 20 {
				c.fail(e.At, "bad shift amount in constant expression")
			}
			return z.Lsh(l, uint(r.Int64())), true
		case ">>":
			if r.Sign() < 0 || r.BitLen() > 20 {
				c.fail(e.At, "bad shift amount in constant expression")
			}
			return z.Rsh(l, uint(r.Int64())), true
		case "**":
			if r.Sign() < 0 || r.BitLen() > 12 {
				c.fail(e.At, "bad exponent in constant expression")
			}
			return z.Exp(l, r, nil), true
		case "==":
			return b2i(l.Cmp(r) == 0), true
		case "!=":
			return b2i(l.Cmp(r) != 0), true
		case "<":
			return b2i(l.Cmp(r) < 0), true
		case "<=":
			return b2i(l.Cmp(r) <= 0), true
		case ">":
			return b2i(l.Cmp(r) > 0), true
		case ">=":
			return b2i(l.Cmp(r) >= 0), true
		case "&&":
			return b2i(l.Sign() != 0 && r.Sign() != 0), true
		case "||":
			return b2i(l.Sign() != 0 || r.Sign() != 0), true
		}
		return nil, false
	case *hdl.Ternary:
		cv, ok := c.tryConst(st, e.C)
		if !ok {
			return nil, false
		}
		if cv.Sign() != 0 {
			return c.tryConst(st, e.T)
		}
		return c.tryConst(st, e.F)
	case *hdl.Call:
		switch e.Name {
		case "$clog2":
			if len(e.Args) != 1 {
				c.fail(e.At, "$clog2 takes one argument")
			}
			x, ok := c.tryConst(st, e.Args[0])
			if !ok {
				return nil, false
			}
			if x.Sign() <= 0 {
				return big.NewInt(0), true
			}
			return big.NewInt(int64(new(big.Int).Sub(x, big.NewInt(1)).BitLen())), true
		case "$unsigned":
			if len(e.Args) == 1 {
				return c.tryConst(st, e.Args[0])
			}
		}
		return nil, false
	case *hdl.Concat:
		// constant concatenation of sized constants
		acc := new(big.Int)
		for _, p := range e.Parts {
			v, ok := c.tryConst(st, p)
			if !ok {
				return nil, false
			}
			w := c.selfWidth(st, p)
			acc.Lsh(acc, uint(w))
			acc.Or(acc, new(big.Int).And(v, mask(w)))
		}
		return acc, true
	case *hdl.Repl:
		n, ok := c.tryConst(st, e.Count)
		if !ok {
			return nil, false
		}
		v, ok := c.tryConst(st, e.X)
		if !ok {
			return nil, false
		}
		w := c.selfWidth(st, e.X)
		acc := new(big.Int)
		for i := int64(0); i < n.Int64(); i++ {
			acc.Lsh(acc, uint(w))
			acc.Or(acc, new(big.Int).And(v, mask(w)))
		}
		return acc, true
	}
	return nil, false
}

func mask(w int) *big.Int {
	return new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(w)), big.NewInt(1))
}

func b2i(b bool) *big.Int {
	if b {
		return big.NewInt(1)
	}
	return big.NewInt(0)
}

func (c *ctx) constInt(st *state, e hdl.Expr, what string) int {
	v, ok := c.tryConst(st, e)
	if !ok {
		c.fail(e.P(), "%s must be a constant expression", what)
	}
	if !v.IsInt64() || v.Int64() > 1<<20 || v.Int64() < -(1<<20) {
		c.fail(e.P(), "%s is out of range", what)
	}
	return int(v.Int64())
}

// ------------------------------------------------------------------ self-determined widths

func (c *ctx) selfWidth(st *state, e hdl.Expr) int {
	switch e := e.(type) {
	case *hdl.Number:
		if e.Width > 0 {
			return e.Width
		}
		return bitlen32(e.Val)
	case *hdl.Ident:
		if v, ok := constLookup(c, st, e.Name); ok {
			return bitlen32(v)
		}
		s := c.sigByName(e.At, e.Name)
		if s.isInt {
			return 32
		}
		return s.width
	case *hdl.Index:
		switch e.Part {
		case 0:
			return 1
		case ':':
			hi, lo := c.constInt(st, e.Hi, "part-select msb"), c.constInt(st, e.Lo, "part-select lsb")
			if hi < lo {
				c.fail(e.At, "part-select [%d:%d] has msb < lsb", hi, lo)
			}
			return hi - lo + 1
		default:
			w := c.constInt(st, e.Lo, "indexed part-select width")
			if w <= 0 {
				c.fail(e.At, "indexed part-select width must be positive")
			}
			return w
		}
	case *hdl.Unary:
		switch e.Op {
		case "~", "-", "+":
			return c.selfWidth(st, e.X)
		}
		return 1
	case *hdl.Binary:
		switch e.Op {
		case "+", "-", "*", "/", "%", "&", "|", "^", "~^":
			return max(c.selfWidth(st, e.L), c.selfWidth(st, e.R))
		case "<<", ">>", "**", ">>>":
			return c.selfWidth(st, e.L)
		}
		return 1
	case *hdl.Ternary:
		return max(c.selfWidth(st, e.T), c.selfWidth(st, e.F))
	case *hdl.Concat:
		n := 0
		for _, p := range e.Parts {
			if num, ok := p.(*hdl.Number); ok && num.Width == 0 {
				c.fail(num.At, "unsized number not allowed in concatenation")
			}
			n += c.selfWidth(st, p)
		}
		return n
	case *hdl.Repl:
		n := c.constInt(st, e.Count, "replication count")
		if n < 0 || n > 1<<14 {
			c.fail(e.At, "bad replication count %d", n)
		}
		return n * c.selfWidth(st, e.X)
	case *hdl.Call:
		if e.Name == "$unsigned" && len(e.Args) == 1 {
			return c.selfWidth(st, e.Args[0])
		}
		return 32
	}
	panic("selfWidth: unhandled expression")
}

// ------------------------------------------------------------------ building logic

func (c *ctx) g() *aig.AIG { return c.e.g }

// assignWidth evaluates e in an assignment context of width w and returns exactly w bits.
func (c *ctx) assignWidth(st *state, e hdl.Expr, w int) []aig.Lit {
	cw := max(w, c.selfWidth(st, e))
	return aig.Ext(c.build(st, e, cw), w)
}

func (c *ctx) boolOf(st *state, e hdl.Expr) aig.Lit {
	return c.g().ReduceOr(c.build(st, e, c.selfWidth(st, e)))
}

func (c *ctx) constVec(v *big.Int, w int) []aig.Lit {
	r := make([]aig.Lit, w)
	for i := range r {
		r[i] = bitOf(v, i) // big.Int.Bit handles negatives in two's complement? no: use And
	}
	if v.Sign() < 0 {
		m := new(big.Int).And(v, mask(w))
		for i := range r {
			r[i] = bitOf(m, i)
		}
	}
	return r
}

func (c *ctx) identVec(st *state, e *hdl.Ident) []aig.Lit {
	return c.identBits(st, e, -1, -1)
}

// identBits reads signal e; if lo >= 0 only bits [lo,hi) are resolved (others stay Undef).
func (c *ctx) identBits(st *state, e *hdl.Ident, lo, hi int) []aig.Lit {
	if v, ok := constLookup(c, st, e.Name); ok {
		return c.constVec(v, bitlen32(v))
	}
	s := c.sigByName(e.At, e.Name)
	if s.isInt {
		c.fail(e.At, "integer variable '%s' used before it was given a constant value", e.Name)
	}
	if lo < 0 {
		lo, hi = 0, s.width
	}
	if st != nil {
		if v, ok := st.cur[s]; ok {
			for i := lo; i < hi; i++ {
				if v[i] == aig.Undef {
					c.fail(e.At, "'%s' bit %d is read before it is assigned in this always block (that would infer a latch)", s.name, i+s.lsb)
				}
			}
			return v
		}
	}
	return c.readRange(s, e.At, lo, hi)
}

// build returns the value of e as exactly w bits (context-determined width w >= selfWidth for sized ops).
func (c *ctx) build(st *state, e hdl.Expr, w int) []aig.Lit {
	g := c.g()
	switch e := e.(type) {
	case *hdl.Number:
		return c.constVec(e.Val, w)
	case *hdl.Ident:
		return aig.Ext(c.identVec(st, e), w)
	case *hdl.Index:
		return aig.Ext(c.buildIndex(st, e), w)
	case *hdl.Unary:
		switch e.Op {
		case "~":
			return g.NotV(c.build(st, e.X, w))
		case "-":
			return g.NegV(c.build(st, e.X, w))
		case "+":
			return c.build(st, e.X, w)
		}
		x := c.build(st, e.X, c.selfWidth(st, e.X))
		var r aig.Lit
		switch e.Op {
		case "!":
			r = g.ReduceOr(x).Not()
		case "&":
			r = g.ReduceAnd(x)
		case "|":
			r = g.ReduceOr(x)
		case "^":
			r = g.ReduceXor(x)
		case "~&":
			r = g.ReduceAnd(x).Not()
		case "~|":
			r = g.ReduceOr(x).Not()
		case "~^":
			r = g.ReduceXor(x).Not()
		default:
			c.fail(e.At, "unsupported unary operator %s", e.Op)
		}
		return aig.Ext([]aig.Lit{r}, w)
	case *hdl.Binary:
		return c.buildBinary(st, e, w)
	case *hdl.Ternary:
		cond := c.boolOf(st, e.C)
		return g.MuxV(cond, c.build(st, e.T, w), c.build(st, e.F, w))
	case *hdl.Concat:
		var r []aig.Lit
		for i := len(e.Parts) - 1; i >= 0; i-- {
			p := e.Parts[i]
			r = append(r, c.build(st, p, c.selfWidth(st, p))...)
		}
		return aig.Ext(r, w)
	case *hdl.Repl:
		n := c.constInt(st, e.Count, "replication count")
		inner := c.build(st, e.X, c.selfWidth(st, e.X))
		var r []aig.Lit
		for i := 0; i < n; i++ {
			r = append(r, inner...)
		}
		return aig.Ext(r, w)
	case *hdl.Call:
		switch e.Name {
		case "$unsigned":
			if len(e.Args) == 1 {
				return c.build(st, e.Args[0], w)
			}
		case "$clog2":
			if v, ok := c.tryConst(st, e); ok {
				return c.constVec(v, w)
			}
			c.fail(e.At, "$clog2 argument must be constant")
		}
		c.fail(e.At, "unsupported system function %s", e.Name)
	}
	panic("build: unhandled expression")
}

func (c *ctx) buildBinary(st *state, e *hdl.Binary, w int) []aig.Lit {
	g := c.g()
	switch e.Op {
	case "+", "-", "*", "/", "%", "&", "|", "^", "~^":
		l, r := c.build(st, e.L, w), c.build(st, e.R, w)
		switch e.Op {
		case "+":
			return g.AddV(l, r)
		case "-":
			d, _ := g.SubV(l, r)
			return d
		case "*":
			return g.MulV(l, r)
		case "/":
			q, _ := g.DivModV(l, r)
			return q
		case "%":
			_, rem := g.DivModV(l, r)
			return rem
		case "&":
			return g.BitwiseV('&', l, r)
		case "|":
			return g.BitwiseV('|', l, r)
		case "^":
			return g.BitwiseV('^', l, r)
		default:
			return g.BitwiseV('x', l, r)
		}
	case "<<", ">>":
		l := c.build(st, e.L, w)
		if n, ok := c.tryConst(st, e.R); ok {
			return shiftConst(l, n, e.Op == "<<")
		}
		return g.ShiftV(l, c.build(st, e.R, c.selfWidth(st, e.R)), e.Op == "<<")
	case ">>>":
		c.fail(e.At, "arithmetic shift '>>>' needs signed arithmetic, which is not supported")
	case "**":
		v, ok := c.tryConst(st, e)
		if !ok {
			c.fail(e.At, "'**' requires constant operands")
		}
		return c.constVec(v, w)
	case "==", "!=", "<", "<=", ">", ">=":
		m := max(c.selfWidth(st, e.L), c.selfWidth(st, e.R))
		l, r := c.build(st, e.L, m), c.build(st, e.R, m)
		var res aig.Lit
		switch e.Op {
		case "==":
			res = g.EqV(l, r)
		case "!=":
			res = g.EqV(l, r).Not()
		case "<":
			res = g.LtV(l, r)
		case ">=":
			res = g.LtV(l, r).Not()
		case ">":
			res = g.LtV(r, l)
		case "<=":
			res = g.LtV(r, l).Not()
		}
		return aig.Ext([]aig.Lit{res}, w)
	case "&&", "||":
		a, b := c.boolOf(st, e.L), c.boolOf(st, e.R)
		if e.Op == "&&" {
			return aig.Ext([]aig.Lit{g.And(a, b)}, w)
		}
		return aig.Ext([]aig.Lit{g.Or(a, b)}, w)
	}
	c.fail(e.At, "unsupported operator %s", e.Op)
	return nil
}

func shiftConst(l []aig.Lit, n *big.Int, left bool) []aig.Lit {
	w := len(l)
	r := make([]aig.Lit, w)
	if n.Sign() < 0 || !n.IsInt64() || n.Int64() >= int64(w) {
		return r
	}
	k := int(n.Int64())
	for i := 0; i < w; i++ {
		if left {
			if i-k >= 0 {
				r[i] = l[i-k]
			}
		} else if i+k < w {
			r[i] = l[i+k]
		}
	}
	return r
}

func (c *ctx) baseSignal(e hdl.Expr, at hdl.Pos) *hdl.Ident {
	id, ok := e.(*hdl.Ident)
	if !ok {
		c.fail(at, "bit/part-select is only supported directly on a named signal")
	}
	return id
}

func (c *ctx) buildIndex(st *state, e *hdl.Index) []aig.Lit {
	g := c.g()
	id := c.baseSignal(e.X, e.At)
	var vec []aig.Lit
	lsb := 0
	if v, ok := constLookup(c, st, id.Name); ok {
		vec = c.constVec(v, bitlen32(v))
	} else {
		s := c.sigByName(id.At, id.Name)
		if s.isInt {
			c.fail(id.At, "cannot index integer variable '%s'", id.Name)
		}
		lsb = s.lsb
		lo, hi := -1, -1
		switch e.Part {
		case 0:
			if k, ok := c.tryConst(st, e.Hi); ok && k.IsInt64() {
				if i := int(k.Int64()) - lsb; i >= 0 && i < s.width {
					lo, hi = i, i+1
				}
			}
		case ':':
			h, l := c.constInt(st, e.Hi, "part-select msb"), c.constInt(st, e.Lo, "part-select lsb")
			if l <= h && l-lsb >= 0 && h-lsb < s.width {
				lo, hi = l-lsb, h-lsb+1
			}
		}
		vec = c.identBits(st, id, lo, hi)
	}
	n := len(vec)
	switch e.Part {
	case 0:
		if k, ok := c.tryConst(st, e.Hi); ok {
			i := int(k.Int64()) - lsb
			if !k.IsInt64() || i < 0 || i >= n {
				c.fail(e.At, "bit index %s is out of range for '%s' [%d:%d]", k, id.Name, n-1+lsb, lsb)
			}
			return []aig.Lit{vec[i]}
		}
		idx := c.build(st, e.Hi, c.selfWidth(st, e.Hi))
		return []aig.Lit{dynSelect(g, vec, lsb, idx, 0)}
	case ':':
		hi, lo := c.constInt(st, e.Hi, "part-select msb"), c.constInt(st, e.Lo, "part-select lsb")
		if hi < lo {
			c.fail(e.At, "part-select [%d:%d] has msb < lsb", hi, lo)
		}
		if lo-lsb < 0 || hi-lsb >= n {
			c.fail(e.At, "part-select [%d:%d] is out of range for '%s' [%d:%d]", hi, lo, id.Name, n-1+lsb, lsb)
		}
		return append([]aig.Lit(nil), vec[lo-lsb:hi-lsb+1]...)
	default:
		w := c.constInt(st, e.Lo, "indexed part-select width")
		out := make([]aig.Lit, w)
		if k, ok := c.tryConst(st, e.Hi); ok {
			base := int(k.Int64())
			if e.Part == '-' {
				base = base - w + 1
			}
			if base-lsb < 0 || base-lsb+w > n {
				c.fail(e.At, "indexed part-select is out of range for '%s'", id.Name)
			}
			copy(out, vec[base-lsb:base-lsb+w])
			return out
		}
		idx := c.build(st, e.Hi, c.selfWidth(st, e.Hi))
		for j := 0; j < w; j++ {
			off := j
			if e.Part == '-' {
				off = j - w + 1
			}
			out[j] = dynSelect(g, vec, lsb, idx, off)
		}
		return out
	}
}

// dynSelect returns vec[idx+off-lsb] as a mux tree (0 when out of range).
func dynSelect(g *aig.AIG, vec []aig.Lit, lsb int, idx []aig.Lit, off int) aig.Lit {
	acc := aig.False
	for j := range vec {
		target := j + lsb - off
		if target < 0 || (len(idx) < 40 && target >= 1<<uint(len(idx))) {
			continue
		}
		acc = g.Or(acc, g.And(g.EqV(idx, aig.Const(uint64(target), len(idx))), vec[j]))
	}
	return acc
}
