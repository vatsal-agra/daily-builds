package opt

import "dominion/ir"

// DCE is aggressive (mark & sweep) dead-code elimination. A store is live only if some live load
// may read its slot; allocas that are only ever written are removed together with their stores.
func DCE(f *ir.Func) int {
	live := map[*ir.Value]bool{}
	storesTo := map[*ir.Value][]*ir.Value{}
	slotNeeded := map[*ir.Value]bool{}
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		if v.Op == ir.OpStore {
			storesTo[v.Args[0]] = append(storesTo[v.Args[0]], v)
		}
	})
	var work []*ir.Value
	mark := func(v *ir.Value) {
		if v == nil || v.IsConst() || v.Op == ir.OpParam || live[v] {
			return
		}
		live[v] = true
		work = append(work, v)
	}
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		if v.Op != ir.OpStore && v.HasSideEffect() {
			mark(v)
		}
	})
	for _, b := range f.Blocks {
		mark(b.Ctrl)
	}
	for len(work) > 0 {
		v := work[len(work)-1]
		work = work[:len(work)-1]
		for _, a := range v.Args {
			mark(a)
		}
		if v.Op == ir.OpLoad && !slotNeeded[v.Args[0]] {
			slotNeeded[v.Args[0]] = true
			for _, s := range storesTo[v.Args[0]] {
				mark(s)
			}
		}
	}
	n := 0
	for _, b := range f.Blocks {
		kept := b.Phis[:0]
		for _, v := range b.Phis {
			if live[v] {
				kept = append(kept, v)
			} else {
				n++
			}
		}
		b.Phis = kept
		ki := b.Instrs[:0]
		for _, v := range b.Instrs {
			if live[v] {
				ki = append(ki, v)
			} else {
				n++
			}
		}
		b.Instrs = ki
	}
	return n
}
