package opt

import (
	"fmt"

	"dominion/ir"
)

func exprKey(v *ir.Value) string {
	a := v.Args
	if v.Op.IsCommutative() && argOrder(a[0]) > argOrder(a[1]) {
		a = []*ir.Value{a[1], a[0]}
	}
	k := v.Op.String()
	for _, x := range a {
		if x.IsConst() {
			k += fmt.Sprintf(" #%d", x.Const)
		} else {
			k += fmt.Sprintf(" %%%d", x.ID)
		}
	}
	return k
}

func argOrder(v *ir.Value) int64 {
	if v.IsConst() {
		return v.Const*2 + 1<<40 // arbitrary but stable
	}
	return int64(v.ID) * 2
}

// GVN is dominator-tree based global value numbering: a pure expression is replaced by an
// identical one that dominates it. Phis in one block with identical operands are merged too.
func GVN(f *ir.Func) int {
	f.RemoveUnreachable()
	dom := ir.ComputeDom(f)
	n := 0
	type scope struct{ added []string }
	table := map[string]*ir.Value{}
	var walk func(b *ir.Block)
	walk = func(b *ir.Block) {
		var added []string
		// identical phis
		seenPhi := map[string]*ir.Value{}
		for i := 0; i < len(b.Phis); i++ {
			ph := b.Phis[i]
			k := ""
			for _, a := range ph.Args {
				k += fmt.Sprintf("%p,", a)
			}
			if prev, ok := seenPhi[k]; ok {
				f.ReplaceAllUses(ph, prev)
				b.Phis = append(b.Phis[:i], b.Phis[i+1:]...)
				i--
				n++
			} else {
				seenPhi[k] = ph
			}
		}
		for i := 0; i < len(b.Instrs); i++ {
			v := b.Instrs[i]
			if !v.IsPure() {
				continue
			}
			k := exprKey(v)
			if prev, ok := table[k]; ok {
				f.ReplaceAllUses(v, prev)
				b.Instrs = append(b.Instrs[:i], b.Instrs[i+1:]...)
				i--
				n++
				continue
			}
			table[k] = v
			added = append(added, k)
		}
		for _, c := range dom.Children[b] {
			walk(c)
		}
		for _, k := range added {
			delete(table, k)
		}
	}
	walk(f.Entry())
	return n
}

// MemOpt does store-to-load forwarding, redundant-load elimination and dead-store elimination on
// alloca slots across single-predecessor chains. Slots never escape, so calls cannot clobber them.
func MemOpt(f *ir.Func) int {
	f.RemoveUnreachable()
	n := 0
	type key struct {
		slot *ir.Value
		idx  *ir.Value
	}
	exit := map[*ir.Block]map[key]*ir.Value{}
	for _, b := range ir.ReversePostorder(f) {
		known := map[key]*ir.Value{}
		if len(b.Preds) == 1 {
			if pm, ok := exit[b.Preds[0]]; ok {
				for k, v := range pm {
					known[k] = v
				}
			}
		}
		pendingStore := map[key]*ir.Value{} // last store not yet observed by a load
		kill := func(slot, idx *ir.Value) {
			for k := range known {
				if k.slot != slot {
					continue
				}
				if idx != nil && idx.IsConst() && k.idx.IsConst() && idx.Const != k.idx.Const {
					continue
				}
				delete(known, k)
			}
		}
		for i := 0; i < len(b.Instrs); i++ {
			v := b.Instrs[i]
			switch v.Op {
			case ir.OpLoad:
				k := key{v.Args[0], v.Args[1]}
				if val, ok := known[k]; ok {
					f.ReplaceAllUses(v, val)
					b.Instrs = append(b.Instrs[:i], b.Instrs[i+1:]...)
					i--
					n++
					continue
				}
				known[k] = v
				for pk := range pendingStore { // a load may observe any store to this slot
					if pk.slot == k.slot {
						delete(pendingStore, pk)
					}
				}
			case ir.OpStore:
				k := key{v.Args[0], v.Args[1]}
				if old, ok := pendingStore[k]; ok {
					b.RemoveInstr(old)
					// removal shifted indices at or before i
					for j := range b.Instrs {
						if b.Instrs[j] == v {
							i = j
							break
						}
					}
					n++
				}
				// a store through an unknown index may clobber other entries
				kill(k.slot, k.idx)
				// a store through a non-constant index makes other pending stores uncertain
				if !k.idx.IsConst() {
					for pk := range pendingStore {
						if pk.slot == k.slot {
							delete(pendingStore, pk)
						}
					}
				}
				known[k] = v.Args[2]
				pendingStore[k] = v
			}
		}
		exit[b] = known
	}
	return n
}
