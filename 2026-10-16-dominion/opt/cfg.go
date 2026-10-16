// Package opt contains Dominion's analyses and optimisation passes.
package opt

import "dominion/ir"

// replaceTrivialPhis removes phis whose operands (ignoring self references) are all the same value.
func replaceTrivialPhis(f *ir.Func) int {
	n := 0
	for changed := true; changed; {
		changed = false
		for _, b := range f.Blocks {
			for i := 0; i < len(b.Phis); i++ {
				ph := b.Phis[i]
				var same *ir.Value
				trivial := true
				for _, a := range ph.Args {
					if a == ph || a == same {
						continue
					}
					if same != nil {
						trivial = false
						break
					}
					same = a
				}
				if !trivial {
					continue
				}
				if same == nil {
					// phi of only itself: unreachable/undefined loop value; the interpreter default is 0
					same = f.Const(0)
				}
				f.ReplaceAllUses(ph, same)
				b.Phis = append(b.Phis[:i], b.Phis[i+1:]...)
				i--
				n++
				changed = true
			}
		}
	}
	return n
}

// SimplifyCFG folds constant branches, removes unreachable blocks, forwards empty blocks and merges chains.
func SimplifyCFG(f *ir.Func) int {
	total := 0
	for {
		n := 0
		// constant conditional branches
		for _, b := range f.Blocks {
			if b.Term == ir.TermCondBr && b.Ctrl.IsConst() {
				keep, drop := b.Succs[0], b.Succs[1]
				if b.Ctrl.Const == 0 {
					keep, drop = drop, keep
				}
				drop.RemovePredEdge(b)
				b.Term, b.Ctrl, b.Succs = ir.TermBr, nil, []*ir.Block{keep}
				n++
			}
		}
		if f.RemoveUnreachable() {
			n++
		}
		n += replaceTrivialPhis(f)
		// forward empty blocks
		for _, e := range append([]*ir.Block(nil), f.Blocks...) {
			if e == f.Entry() || e.Term != ir.TermBr || len(e.Phis) > 0 || len(e.Instrs) > 0 || e.Succs[0] == e {
				continue
			}
			x := e.Succs[0]
			for _, p := range append([]*ir.Block(nil), e.Preds...) {
				if x.PredIndex(p) >= 0 { // would create a duplicate edge p->x
					continue
				}
				idx := x.PredIndex(e)
				p.ReplaceSucc(e, x)
				for _, ph := range x.Phis {
					ph.Args = append(ph.Args, ph.Args[idx])
				}
				n++
			}
		}
		if f.RemoveUnreachable() {
			n++
		}
		// merge b -> s when s has a unique predecessor
		for i := 0; i < len(f.Blocks); i++ {
			b := f.Blocks[i]
			if b.Term != ir.TermBr {
				continue
			}
			s := b.Succs[0]
			if s == b || s == f.Entry() || len(s.Preds) != 1 {
				continue
			}
			for _, ph := range s.Phis {
				f.ReplaceAllUses(ph, ph.Args[0])
			}
			for _, v := range s.Instrs {
				v.Block = b
			}
			b.Instrs = append(b.Instrs, s.Instrs...)
			b.Term, b.Ctrl, b.Succs = s.Term, s.Ctrl, s.Succs
			for _, t := range s.Succs {
				for k, p := range t.Preds {
					if p == s {
						t.Preds[k] = b
					}
				}
			}
			s.Succs, s.Preds, s.Phis, s.Instrs = nil, nil, nil, nil
			for k, x := range f.Blocks {
				if x == s {
					f.Blocks = append(f.Blocks[:k], f.Blocks[k+1:]...)
					break
				}
			}
			i--
			n++
		}
		total += n
		if n == 0 {
			return total
		}
	}
}
