package opt

import "dominion/ir"

// ifconvBudget bounds the cycle cost (VM cost model) speculated per arm.
const ifconvBudget = 4

func specCost(v *ir.Value) int {
	switch v.Op {
	case ir.OpMul:
		return 3
	case ir.OpDiv, ir.OpRem:
		return 12
	}
	return 1
}

// cheapArm reports whether block b holds only a few side-effect-free instructions (safe to execute
// unconditionally) and nothing else but a branch to join.
func cheapArm(b *ir.Block, h, join *ir.Block) bool {
	if len(b.Phis) != 0 || len(b.Preds) != 1 || b.Preds[0] != h || b.Term != ir.TermBr || b.Succs[0] != join {
		return false
	}
	cost := 0
	for _, v := range b.Instrs {
		if !v.IsPure() { // loads, calls, stores, trapping division stay put
			return false
		}
		cost += specCost(v)
	}
	return cost <= ifconvBudget
}

// IfConvert turns small diamonds and triangles whose join has phis into straight-line code with
// select instructions (branch elimination by speculation of cheap pure arms).
func IfConvert(f *ir.Func) int {
	n := 0
	for changed := true; changed; {
		changed = false
		for _, h := range f.Blocks {
			if h.Term != ir.TermCondBr {
				continue
			}
			t, e := h.Succs[0], h.Succs[1]
			var join *ir.Block
			var arms []*ir.Block // speculated blocks, in {true-arm, false-arm} order (nil = direct edge)
			switch {
			case t.Term == ir.TermBr && e.Term == ir.TermBr && t.Succs[0] == e.Succs[0] && t != e:
				join = t.Succs[0]
				if !cheapArm(t, h, join) || !cheapArm(e, h, join) || len(join.Preds) != 2 {
					continue
				}
				arms = []*ir.Block{t, e}
			case t.Term == ir.TermBr && t.Succs[0] == e: // triangle: true arm then join=e
				join = e
				if !cheapArm(t, h, join) || len(join.Preds) != 2 {
					continue
				}
				arms = []*ir.Block{t, nil}
			case e.Term == ir.TermBr && e.Succs[0] == t: // triangle: false arm then join=t
				join = t
				if !cheapArm(e, h, join) || len(join.Preds) != 2 {
					continue
				}
				arms = []*ir.Block{nil, e}
			default:
				continue
			}
			if join == h {
				continue
			}
			// predecessor index of each arm's contribution in join's phis
			idx := func(arm *ir.Block) int {
				if arm != nil {
					return join.PredIndex(arm)
				}
				return join.PredIndex(h)
			}
			ti, ei := idx(arms[0]), idx(arms[1])
			if ti < 0 || ei < 0 || ti == ei {
				continue
			}
			// speculate arm instructions into h
			for _, arm := range arms {
				if arm == nil {
					continue
				}
				for _, v := range arm.Instrs {
					v.Block = h
					h.Instrs = append(h.Instrs, v)
				}
				arm.Instrs = nil
			}
			repl := ir.NewReplacer()
			for _, ph := range join.Phis {
				sel := f.NewValue(ir.OpSelect, h.Ctrl, ph.Args[ti], ph.Args[ei])
				h.Append(sel)
				repl.Add(ph, sel)
			}
			join.Phis = nil
			// rewire: h -> join directly
			for _, arm := range arms {
				if arm != nil {
					join.RemovePredEdge(arm)
				}
			}
			// join now has the single pred h (via the direct edge) or, for diamonds, none: add it
			if len(join.Preds) == 0 { // diamond; a triangle keeps its direct h->join edge
				join.Preds = []*ir.Block{h}
			}
			h.Term, h.Ctrl, h.Succs = ir.TermBr, nil, []*ir.Block{join}
			f.Apply(repl)
			f.RemoveUnreachable()
			n++
			changed = true
			break
		}
	}
	return n
}
