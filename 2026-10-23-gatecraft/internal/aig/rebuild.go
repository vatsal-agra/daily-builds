package aig

import "sort"

// latchSub says what to do with latch i when rebuilding.
type latchSub struct {
	kind int // 0 keep, 1 constant, 2 alias of latch `to`, 3 dead
	val  bool
	to   int
}

// rebuilder copies a source AIG into a fresh one, translating logic on demand
// from the roots (so unreachable logic disappears) through a per-pass hook.
type rebuilder struct {
	src, dst *AIG
	m        []Lit
	lvl      []int
	refs     []int
	andFn    func(rb *rebuilder, id uint32) Lit
	subs     []latchSub
}

func newRebuilder(src *AIG, rewrite bool, subs []latchSub) *rebuilder {
	dst := New()
	dst.Rewrite = rewrite
	rb := &rebuilder{src: src, dst: dst, m: make([]Lit, len(src.Nodes)), subs: subs}
	for i := range rb.m {
		rb.m[i] = Undef
	}
	rb.m[0] = False
	for _, pi := range src.PIs {
		rb.m[pi.Node] = dst.AddInput(pi.Port, pi.Bit)
	}
	if subs == nil {
		rb.subs = make([]latchSub, len(src.Latches))
	}
	for i, l := range src.Latches {
		if rb.subs[i].kind == 0 {
			q := dst.AddLatch(l.Name, l.Init)
			dst.Latches[len(dst.Latches)-1].Clock = l.Clock
			rb.m[l.Q] = q
		}
	}
	// resolve substitutions (aliases may chain through other substituted latches)
	var resolve func(i int, depth int) Lit
	resolve = func(i, depth int) Lit {
		s := rb.subs[i]
		switch s.kind {
		case 0:
			return rb.m[src.Latches[i].Q]
		case 1:
			if s.val {
				return True
			}
			return False
		case 2:
			if depth > len(src.Latches) {
				panic("aig: alias cycle")
			}
			return resolve(s.to, depth+1)
		}
		return Undef
	}
	for i, l := range src.Latches {
		if rb.subs[i].kind == 1 || rb.subs[i].kind == 2 {
			rb.m[l.Q] = resolve(i, 0)
		}
	}
	return rb
}

// lit translates a source literal into the destination graph.
func (rb *rebuilder) lit(l Lit) Lit {
	if l == Undef {
		return Undef
	}
	id := l.ID()
	if rb.m[id] == Undef {
		n := rb.src.Nodes[id]
		if n.Kind != KAnd {
			panic("aig: reference to dropped node " + l.String())
		}
		if rb.andFn != nil {
			rb.m[id] = rb.andFn(rb, id)
		} else {
			rb.m[id] = rb.dst.And(rb.lit(n.A), rb.lit(n.B))
		}
	}
	return rb.m[id].NotIf(l.Neg())
}

func (rb *rebuilder) level(l Lit) int {
	for len(rb.lvl) < len(rb.dst.Nodes) {
		i := len(rb.lvl)
		n := rb.dst.Nodes[i]
		v := 0
		if n.Kind == KAnd {
			v = max(rb.lvl[n.A.ID()], rb.lvl[n.B.ID()]) + 1
		}
		rb.lvl = append(rb.lvl, v)
	}
	return rb.lvl[l.ID()]
}

// finish translates every root and copies ports, names and bookkeeping.
func (rb *rebuilder) finish() *AIG {
	src, dst := rb.src, rb.dst
	for _, p := range src.Inputs {
		bits := make([]Lit, len(p.Bits))
		for i, b := range p.Bits {
			bits[i] = rb.m[b.ID()].NotIf(b.Neg())
		}
		dst.Inputs = append(dst.Inputs, Port{Name: p.Name, Bits: bits})
	}
	for _, p := range src.Outputs {
		bits := make([]Lit, len(p.Bits))
		for i, b := range p.Bits {
			bits[i] = rb.lit(b)
		}
		dst.Outputs = append(dst.Outputs, Port{Name: p.Name, Bits: bits})
	}
	for _, p := range src.Asserts {
		dst.Asserts = append(dst.Asserts, Prop{p.Name, rb.lit(p.Lit)})
	}
	for _, p := range src.Assumes {
		dst.Assumes = append(dst.Assumes, Prop{p.Name, rb.lit(p.Lit)})
	}
	k := 0
	for i, l := range src.Latches {
		if rb.subs[i].kind == 0 {
			dst.Latches[k].D = rb.lit(l.D)
			k++
		}
	}
	// names: keep those whose logic survived
	for _, n := range src.NameOrder {
		bits := src.Names[n]
		out := make([]Lit, len(bits))
		ok := true
		for i, b := range bits {
			if b == Undef || rb.m[b.ID()] == Undef {
				ok = false
				break
			}
			out[i] = rb.m[b.ID()].NotIf(b.Neg())
		}
		if ok {
			dst.SetName(n, out)
		}
	}
	// removed-latch bookkeeping, composed with earlier passes
	dst.Removed = map[string]string{}
	for k, v := range src.Removed {
		dst.Removed[k] = v
	}
	for i, l := range src.Latches {
		switch s := rb.subs[i]; s.kind {
		case 1:
			if s.val {
				dst.Removed[l.Name] = "1"
			} else {
				dst.Removed[l.Name] = "0"
			}
		case 2:
			dst.Removed[l.Name] = src.Latches[s.to].Name
		case 3:
			dst.Removed[l.Name] = "dead"
		}
	}
	// re-point earlier removals whose target was removed in this pass
	for k, v := range dst.Removed {
		for depth := 0; depth < len(src.Latches)+1; depth++ {
			if v == "0" || v == "1" || v == "dead" {
				break
			}
			t, gone := dst.Removed[v]
			if !gone {
				break
			}
			v = t
		}
		dst.Removed[k] = v
	}
	return dst
}

// ------------------------------------------------------------------ passes

// Sweep rebuilds the graph keeping only logic that feeds outputs, properties and live latches.
func Sweep(g *AIG) *AIG {
	subs := make([]latchSub, len(g.Latches))
	for i, live := range g.LiveLatches() {
		if !live {
			subs[i].kind = 3
		}
	}
	return newRebuilder(g, false, subs).finish()
}

// Rewrite re-creates the graph applying two-level local simplification rules.
func Rewrite(g *AIG) *AIG {
	subs := make([]latchSub, len(g.Latches))
	for i, live := range g.LiveLatches() {
		if !live {
			subs[i].kind = 3
		}
	}
	return newRebuilder(g, true, subs).finish()
}

// Balance restructures AND trees into minimum-depth form (single-fanout supergates).
func Balance(g *AIG) *AIG {
	subs := make([]latchSub, len(g.Latches))
	live := g.LiveLatches()
	for i, l := range live {
		if !l {
			subs[i].kind = 3
		}
	}
	rb := newRebuilder(g, true, subs)
	refs := make([]int, len(g.Nodes))
	nodes := g.Live()
	for id, n := range g.Nodes {
		if n.Kind == KAnd && nodes[id] {
			refs[n.A.ID()]++
			refs[n.B.ID()]++
		}
	}
	for _, r := range g.Roots() {
		if r != Undef {
			refs[r.ID()]++
		}
	}
	rb.refs = refs
	rb.andFn = func(rb *rebuilder, id uint32) Lit {
		var leaves []Lit
		var collect func(l Lit, top bool)
		collect = func(l Lit, top bool) {
			n := g.Nodes[l.ID()]
			if !l.Neg() && n.Kind == KAnd && (top || rb.refs[l.ID()] == 1) {
				collect(n.A, false)
				collect(n.B, false)
				return
			}
			leaves = append(leaves, l)
		}
		collect(Lit(id<<1), true)
		items := make([]Lit, 0, len(leaves))
		seen := map[Lit]bool{}
		for _, l := range leaves {
			t := rb.lit(l)
			if t == False {
				return False
			}
			if t == True || seen[t] {
				continue
			}
			if seen[t.Not()] {
				return False
			}
			seen[t] = true
			items = append(items, t)
		}
		if len(items) == 0 {
			return True
		}
		for len(items) > 1 {
			sort.SliceStable(items, func(i, j int) bool { return rb.level(items[i]) < rb.level(items[j]) })
			a := rb.dst.And(items[0], items[1])
			items = append([]Lit{a}, items[2:]...)
		}
		return items[0]
	}
	return rb.finish()
}
