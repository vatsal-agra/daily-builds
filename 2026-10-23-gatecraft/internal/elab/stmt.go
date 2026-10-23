package elab

import (
	"fmt"
	"math/big"

	"gatecraft/internal/aig"
	"gatecraft/internal/hdl"
)

// lvWrite routes bit valIdx of an assignment value to sig[bit] when cond holds.
type lvWrite struct {
	sig    *signal
	bit    int
	valIdx int
	cond   aig.Lit
}

// lvalue resolves an assignment target; st may be nil (static contexts reject dynamic indices).
func (c *ctx) lvalue(st *state, e hdl.Expr) (int, []lvWrite) {
	g := c.g()
	switch e := e.(type) {
	case *hdl.Ident:
		s := c.sigByName(e.At, e.Name)
		if s.isInt {
			c.fail(e.At, "integer variable '%s' cannot be used as a hardware assignment target", e.Name)
		}
		ws := make([]lvWrite, s.width)
		for i := range ws {
			ws[i] = lvWrite{s, i, i, aig.True}
		}
		return s.width, ws
	case *hdl.Index:
		id := c.baseSignal(e.X, e.At)
		s := c.sigByName(id.At, id.Name)
		switch e.Part {
		case 0:
			if k, ok := c.tryConst(st, e.Hi); ok {
				i := int(k.Int64()) - s.lsb
				if i < 0 || i >= s.width {
					c.fail(e.At, "bit index %s is out of range for '%s'", k, s.name)
				}
				return 1, []lvWrite{{s, i, 0, aig.True}}
			}
			if st == nil {
				c.fail(e.At, "continuous assignment needs a constant index")
			}
			idx := c.build(st, e.Hi, c.selfWidth(st, e.Hi))
			var ws []lvWrite
			for j := 0; j < s.width; j++ {
				t := j + s.lsb
				if len(idx) < 40 && t >= 1<<uint(len(idx)) {
					continue
				}
				ws = append(ws, lvWrite{s, j, 0, g.EqV(idx, aig.Const(uint64(t), len(idx)))})
			}
			return 1, ws
		case ':':
			hi, lo := c.constInt(st, e.Hi, "part-select msb"), c.constInt(st, e.Lo, "part-select lsb")
			if hi < lo || lo-s.lsb < 0 || hi-s.lsb >= s.width {
				c.fail(e.At, "part-select [%d:%d] is out of range for '%s'", hi, lo, s.name)
			}
			ws := make([]lvWrite, hi-lo+1)
			for k := range ws {
				ws[k] = lvWrite{s, lo - s.lsb + k, k, aig.True}
			}
			return hi - lo + 1, ws
		default:
			w := c.constInt(st, e.Lo, "indexed part-select width")
			k, ok := c.tryConst(st, e.Hi)
			if !ok {
				c.fail(e.At, "indexed part-select assignment target needs a constant base")
			}
			base := int(k.Int64())
			if e.Part == '-' {
				base = base - w + 1
			}
			if base-s.lsb < 0 || base-s.lsb+w > s.width {
				c.fail(e.At, "indexed part-select is out of range for '%s'", s.name)
			}
			ws := make([]lvWrite, w)
			for j := range ws {
				ws[j] = lvWrite{s, base - s.lsb + j, j, aig.True}
			}
			return w, ws
		}
	case *hdl.Concat:
		total := 0
		var ws []lvWrite
		for i := len(e.Parts) - 1; i >= 0; i-- {
			w, pw := c.lvalue(st, e.Parts[i])
			for _, x := range pw {
				x.valIdx += total
				ws = append(ws, x)
			}
			total += w
		}
		return total, ws
	}
	c.fail(e.P(), "invalid assignment target")
	return 0, nil
}

// assignedSignals lists, in order, the hardware signals a statement may write.
func (c *ctx) assignedSignals(s hdl.Stmt, out *[]*signal, seen map[*signal]bool) {
	var lv func(e hdl.Expr)
	lv = func(e hdl.Expr) {
		switch e := e.(type) {
		case *hdl.Ident:
			s := c.sigByName(e.At, e.Name)
			if !s.isInt && !seen[s] {
				seen[s] = true
				*out = append(*out, s)
			}
		case *hdl.Index:
			lv(e.X)
		case *hdl.Concat:
			for _, p := range e.Parts {
				lv(p)
			}
		}
	}
	switch s := s.(type) {
	case *hdl.Block:
		for _, x := range s.Stmts {
			c.assignedSignals(x, out, seen)
		}
	case *hdl.Assign:
		lv(s.LHS)
	case *hdl.If:
		c.assignedSignals(s.Then, out, seen)
		if s.Else != nil {
			c.assignedSignals(s.Else, out, seen)
		}
	case *hdl.Case:
		for _, it := range s.Items {
			c.assignedSignals(it.Body, out, seen)
		}
	case *hdl.For:
		c.assignedSignals(s.Init, out, seen)
		c.assignedSignals(s.Step, out, seen)
		c.assignedSignals(s.Body, out, seen)
	}
}

// ------------------------------------------------------------------ combinational blocks

func (c *ctx) installComb(a *hdl.Always) {
	var sigs []*signal
	c.assignedSignals(a.Body, &sigs, map[*signal]bool{})
	for _, s := range sigs {
		if !s.isReg {
			c.fail(a.At, "'%s' is assigned in an always block and must be declared 'reg'", s.name)
		}
	}
	d := &driver{what: fmt.Sprintf("always@%s", a.At)}
	for _, s := range sigs {
		for b := 0; b < s.width; b++ {
			d.targets = append(d.targets, bitRef{s, b})
		}
	}
	d.eval = func() []aig.Lit {
		st := &state{cur: map[*signal][]aig.Lit{}, kind: map[*signal]byte{}, consts: map[string]*big.Int{}}
		for _, s := range sigs {
			st.cur[s] = undefVec(s.width)
		}
		c.exec(st, a.Body)
		var out []aig.Lit
		for _, s := range sigs {
			for b, l := range st.cur[s] {
				if l == aig.Undef {
					c.fail(a.At, "latch inferred: '%s' bit %d is not assigned on every path through this always block", s.name, b+s.lsb)
				}
			}
			out = append(out, st.cur[s]...)
		}
		return out
	}
	if len(sigs) > 0 {
		c.setDriver(a.At, d)
	}
}

// ------------------------------------------------------------------ clocked blocks

func (c *ctx) declareLatches(cb *clockedBlock) {
	c.assignedSignals(cb.a.Body, &cb.assigned, map[*signal]bool{})
	for _, s := range cb.assigned {
		if !s.isReg {
			c.fail(cb.a.At, "'%s' is assigned in an always block and must be declared 'reg'", s.name)
		}
		for b := 0; b < s.width; b++ {
			if s.driver[b] != nil || s.latch[b] >= 0 {
				c.fail(cb.a.At, "multiple drivers for %s[%d]", s.name, b+s.lsb)
			}
		}
		for b := 0; b < s.width; b++ {
			name := s.full
			if s.width > 1 {
				name = fmt.Sprintf("%s[%d]", s.full, b+s.lsb)
			}
			init := s.init != nil && s.init.Bit(b) == 1
			q := c.g().AddLatch(name, init)
			s.val[b] = q
			s.latch[b] = int(c.g().Nodes[q.ID()].Idx)
		}
	}
}

func (c *ctx) resolveClock(cb *clockedBlock) {
	cs := c.sigByName(cb.a.At, cb.a.Clock)
	if cs.width != 1 {
		c.fail(cb.a.At, "clock '%s' must be a single bit", cs.name)
	}
	v := c.readSignal(cs, cb.a.At)[0]
	n := c.g().Nodes[v.ID()]
	if v.Neg() || n.Kind != aig.KInput {
		c.fail(cb.a.At, "clock '%s' must be driven directly by a top-level input (no gating or inversion)", cs.name)
	}
	pi := c.g().PIs[n.Idx]
	cb.clock = pi.Port
	if ts := c.e.ctxs[0].sigs[pi.Port]; ts != nil && ts.width > 1 {
		cb.clock = fmt.Sprintf("%s[%d]", pi.Port, pi.Bit+ts.lsb)
	}
}

func (c *ctx) execClocked(cb *clockedBlock) {
	st := &state{cur: map[*signal][]aig.Lit{}, nxt: map[*signal][]aig.Lit{}, kind: map[*signal]byte{}, consts: map[string]*big.Int{}, clocked: true}
	for _, s := range cb.assigned {
		st.cur[s] = append([]aig.Lit(nil), s.val...)
		st.nxt[s] = append([]aig.Lit(nil), s.val...)
	}
	c.exec(st, cb.a.Body)
	for _, s := range cb.assigned {
		for b := 0; b < s.width; b++ {
			l := &c.g().Latches[s.latch[b]]
			l.D = st.nxt[s][b]
			l.Clock = cb.clock
		}
	}
}

// ------------------------------------------------------------------ statement execution

const maxLoop = 1 << 14

func muxLit(g *aig.AIG, cnd, t, f aig.Lit) aig.Lit {
	if cnd == aig.True {
		return t
	}
	if cnd == aig.False {
		return f
	}
	if t == f {
		return t
	}
	if t == aig.Undef || f == aig.Undef {
		return aig.Undef
	}
	return g.Mux(cnd, t, f)
}

func (c *ctx) merge(cnd aig.Lit, a, b *state) *state {
	g := c.g()
	out := &state{cur: map[*signal][]aig.Lit{}, kind: a.kind, consts: a.consts, clocked: a.clocked}
	for s, av := range a.cur {
		bv := b.cur[s]
		r := make([]aig.Lit, len(av))
		for i := range r {
			r[i] = muxLit(g, cnd, av[i], bv[i])
		}
		out.cur[s] = r
	}
	if a.nxt != nil {
		out.nxt = map[*signal][]aig.Lit{}
		for s, av := range a.nxt {
			bv := b.nxt[s]
			r := make([]aig.Lit, len(av))
			for i := range r {
				r[i] = muxLit(g, cnd, av[i], bv[i])
			}
			out.nxt[s] = r
		}
	}
	return out
}

func (st *state) replace(n *state) { st.cur, st.nxt = n.cur, n.nxt }

func (c *ctx) execIf(st *state, cnd aig.Lit, thenFn, elseFn func(*state)) {
	switch cnd {
	case aig.True:
		thenFn(st)
		return
	case aig.False:
		elseFn(st)
		return
	}
	a, b := st.clone(), st.clone()
	thenFn(a)
	elseFn(b)
	st.replace(c.merge(cnd, a, b))
}

func (c *ctx) exec(st *state, s hdl.Stmt) {
	g := c.g()
	switch s := s.(type) {
	case *hdl.Block:
		for _, x := range s.Stmts {
			c.exec(st, x)
		}
	case *hdl.Assign:
		c.execAssign(st, s)
	case *hdl.If:
		cnd := c.boolOf(st, s.C)
		c.execIf(st, cnd, func(x *state) { c.exec(x, s.Then) }, func(x *state) {
			if s.Else != nil {
				c.exec(x, s.Else)
			}
		})
	case *hdl.Case:
		selW := c.selfWidth(st, s.Sel)
		var def hdl.Stmt
		var items []hdl.CaseItem
		for _, it := range s.Items {
			if len(it.Labels) == 0 {
				if def != nil {
					c.fail(s.At, "case has more than one default")
				}
				def = it.Body
			} else {
				items = append(items, it)
			}
		}
		var chain func(x *state, i int)
		chain = func(x *state, i int) {
			if i == len(items) {
				if def != nil {
					c.exec(x, def)
				}
				return
			}
			cnd := aig.False
			for _, lab := range items[i].Labels {
				m := max(selW, c.selfWidth(x, lab))
				cnd = g.Or(cnd, g.EqV(c.build(x, s.Sel, m), c.build(x, lab, m)))
			}
			c.execIf(x, cnd, func(y *state) { c.exec(y, items[i].Body) }, func(y *state) { chain(y, i+1) })
		}
		chain(st, 0)
	case *hdl.For:
		c.execFor(st, s)
	default:
		c.fail(s.SP(), "unsupported statement")
	}
}

func (c *ctx) intTarget(lhs hdl.Expr) (string, bool) {
	if id, ok := lhs.(*hdl.Ident); ok {
		if s, ok := c.sigs[id.Name]; ok && s.isInt {
			return id.Name, true
		}
	}
	return "", false
}

func (c *ctx) execFor(st *state, f *hdl.For) {
	name, ok := c.intTarget(f.Init.LHS)
	if !ok {
		c.fail(f.At, "for-loop variable must be an 'integer'")
	}
	v, ok := c.tryConst(st, f.Init.RHS)
	if !ok {
		c.fail(f.At, "for-loop initial value must be constant")
	}
	st.consts[name] = v
	defer delete(st.consts, name)
	for iter := 0; ; iter++ {
		cv, ok := c.tryConst(st, f.Cond)
		if !ok {
			c.fail(f.At, "for-loop condition must be a compile-time constant (loops are unrolled)")
		}
		if cv.Sign() == 0 {
			return
		}
		if iter >= maxLoop {
			c.fail(f.At, "for loop does not terminate within %d iterations", maxLoop)
		}
		c.exec(st, f.Body)
		n, ok := c.intTarget(f.Step.LHS)
		if !ok || n != name {
			c.fail(f.At, "for-loop step must update the loop variable '%s'", name)
		}
		nv, ok := c.tryConst(st, f.Step.RHS)
		if !ok {
			c.fail(f.At, "for-loop step must be constant")
		}
		st.consts[name] = nv
	}
}

func (c *ctx) execAssign(st *state, a *hdl.Assign) {
	g := c.g()
	if name, ok := c.intTarget(a.LHS); ok {
		v, ok := c.tryConst(st, a.RHS)
		if !ok {
			c.fail(a.At, "integer variable '%s' can only hold compile-time constants", name)
		}
		st.consts[name] = v
		return
	}
	w, writes := c.lvalue(st, a.LHS)
	val := c.assignWidth(st, a.RHS, w)
	if !st.clocked && a.NonBlocking {
		c.fail(a.At, "non-blocking assignment (<=) in a combinational always block; use '='")
	}
	for _, wr := range writes {
		k := byte('b')
		if a.NonBlocking {
			k = 'n'
		}
		if old, ok := st.kind[wr.sig]; ok && old != k && st.clocked {
			c.fail(a.At, "'%s' mixes blocking and non-blocking assignments", wr.sig.name)
		}
		st.kind[wr.sig] = k
		bits := val[wr.valIdx]
		if a.NonBlocking {
			nx := st.nxt[wr.sig]
			nx[wr.bit] = muxLit(g, wr.cond, bits, nx[wr.bit])
			continue
		}
		cu := st.cur[wr.sig]
		if cu == nil {
			c.fail(a.At, "internal: no state for '%s'", wr.sig.name)
		}
		cu[wr.bit] = muxLit(g, wr.cond, bits, cu[wr.bit])
		if st.nxt != nil {
			st.nxt[wr.sig][wr.bit] = cu[wr.bit]
		}
	}
}
