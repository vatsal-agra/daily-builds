package aig

import "gatecraft/internal/sat"

// Encoder Tseitin-encodes (the needed cone of) an AIG into a SAT solver.
// Several encoders may share one solver (time-frame unrolling) – each keeps its
// own node→literal map, and Bind lets a frame alias a node to an existing literal.
type Encoder struct {
	G *AIG
	S *sat.Solver
	m []sat.Lit // per node; -1 = unencoded
	// FreeVar is called for PI/Latch nodes without a binding; default allocates a fresh var.
	FreeVar func(id uint32) sat.Lit
}

func NewEncoder(g *AIG, s *sat.Solver) *Encoder {
	e := &Encoder{G: g, S: s, m: make([]sat.Lit, len(g.Nodes))}
	for i := range e.m {
		e.m[i] = -1
	}
	return e
}

// Bind pre-assigns the (positive) literal of a node.
func (e *Encoder) Bind(id uint32, l sat.Lit) { e.m[id] = l }

// Bound reports whether the node already has a SAT literal.
func (e *Encoder) Bound(id uint32) bool { return e.m[id] >= 0 }

// Lit returns the SAT literal for an AIG literal, encoding its cone on demand.
func (e *Encoder) Lit(l Lit) sat.Lit {
	e.encode(l.ID())
	r := e.m[l.ID()]
	if l.Neg() {
		return r.Not()
	}
	return r
}

func (e *Encoder) fresh() sat.Lit { return sat.MkLit(e.S.NewVar(), false) }

func (e *Encoder) encode(root uint32) {
	if e.m[root] >= 0 {
		return
	}
	stack := []uint32{root}
	for len(stack) > 0 {
		id := stack[len(stack)-1]
		if e.m[id] >= 0 {
			stack = stack[:len(stack)-1]
			continue
		}
		n := e.G.Nodes[id]
		switch n.Kind {
		case KConst:
			v := e.fresh()
			e.S.AddClause(v.Not())
			e.m[id] = v
			stack = stack[:len(stack)-1]
		case KInput, KLatch:
			if e.FreeVar != nil {
				e.m[id] = e.FreeVar(id)
			} else {
				e.m[id] = e.fresh()
			}
			stack = stack[:len(stack)-1]
		case KAnd:
			ia, ib := n.A.ID(), n.B.ID()
			if e.m[ia] < 0 || e.m[ib] < 0 {
				if e.m[ia] < 0 {
					stack = append(stack, ia)
				}
				if e.m[ib] < 0 {
					stack = append(stack, ib)
				}
				continue
			}
			v := e.fresh()
			a, b := e.m[ia].NotIf(n.A.Neg()), e.m[ib].NotIf(n.B.Neg())
			e.S.AddClause(v.Not(), a)
			e.S.AddClause(v.Not(), b)
			e.S.AddClause(v, a.Not(), b.Not())
			e.m[id] = v
			stack = stack[:len(stack)-1]
		}
	}
}
