package opt

import "dominion/ir"

// TailRecursionElim turns self tail calls (`%r = call @self(...); ret %r`) into a back edge.
// Only applies to functions without remaining allocas (a loop must not share array storage).
func TailRecursionElim(f *ir.Func) int {
	for _, v := range f.Entry().Instrs {
		if v.Op == ir.OpAlloca {
			return 0
		}
	}
	var sites []*ir.Value
	for _, b := range f.Blocks {
		if b.Term != ir.TermRet || len(b.Instrs) == 0 {
			continue
		}
		last := b.Instrs[len(b.Instrs)-1]
		if last.Op == ir.OpCall && last.Callee == f.Name && b.Ctrl == last && len(last.Args) == len(f.Params) {
			sites = append(sites, last)
		}
	}
	if len(sites) == 0 {
		return 0
	}
	old := f.Entry()
	// new entry -> old entry (now a loop header whose phis carry the parameters)
	ne := f.NewBlock(f.UniqueBlockName("tre.entry"))
	f.Blocks = append([]*ir.Block{ne}, f.Blocks[:len(f.Blocks)-1]...)
	hdrName := f.UniqueBlockName("tre.loop")
	old.Name = hdrName
	// phis for params
	phis := make([]*ir.Value, len(f.Params))
	for i := range f.Params {
		phis[i] = f.NewValue(ir.OpPhi)
		old.Phis = append([]*ir.Value{phis[i]}, old.Phis...)
		phis[i].Block = old
	}
	// Pre-existing preds of old (none, entry has no preds) -> ne is the first pred.
	old.Preds = nil
	ne.Term, ne.Succs = ir.TermBr, []*ir.Block{old}
	old.Preds = append(old.Preds, ne)
	for i, p := range f.Params {
		phis[i].Args = append(phis[i].Args, p)
	}
	// rewrite uses of params (except the phi args from ne) to the phis
	for i, p := range f.Params {
		for _, b := range f.Blocks {
			for _, v := range append(append([]*ir.Value(nil), b.Phis...), b.Instrs...) {
				if v == phis[i] {
					continue
				}
				for k, a := range v.Args {
					if a == p {
						v.Args[k] = phis[i]
					}
				}
			}
			if b.Ctrl == p {
				b.Ctrl = phis[i]
			}
		}
	}
	// the tail calls: branch back to the header
	for _, c := range sites {
		b := c.Block
		for i := range f.Params {
			phis[i].Args = append(phis[i].Args, c.Args[i])
		}
		b.Instrs = b.Instrs[:len(b.Instrs)-1]
		b.Term, b.Ctrl, b.Succs = ir.TermBr, nil, []*ir.Block{old}
		old.Preds = append(old.Preds, b)
	}
	return len(sites)
}
