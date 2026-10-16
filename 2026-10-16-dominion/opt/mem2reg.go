package opt

import "dominion/ir"

func promotable(f *ir.Func, uses map[*ir.Value][]*ir.Value) []*ir.Value {
	var out []*ir.Value
	for _, v := range f.Entry().Instrs {
		if v.Op != ir.OpAlloca || v.Const != 1 {
			continue
		}
		ok := true
		for _, u := range uses[v] {
			if (u.Op != ir.OpLoad && u.Op != ir.OpStore) || u.Args[0] != v || !u.Args[1].IsConst() || u.Args[1].Const != 0 {
				ok = false
				break
			}
		}
		if ok {
			out = append(out, v)
		}
	}
	return out
}

// Mem2Reg promotes single-word allocas to SSA values using iterated dominance frontiers
// (Cytron et al. 1991) and a dominator-tree renaming walk. Contents of a fresh alloca are zero.
func Mem2Reg(f *ir.Func) int {
	f.RemoveUnreachable()
	uses := map[*ir.Value][]*ir.Value{}
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		for _, a := range v.Args {
			if a.Op == ir.OpAlloca {
				uses[a] = append(uses[a], v)
			}
		}
	})
	allocas := promotable(f, uses)
	if len(allocas) == 0 {
		return 0
	}
	dom := ir.ComputeDom(f)
	df := dom.Frontiers()
	isProm := map[*ir.Value]int{}
	for i, a := range allocas {
		isProm[a] = i
	}
	// phi placement
	phiFor := map[*ir.Block]map[int]*ir.Value{}
	for i, a := range allocas {
		var work []*ir.Block
		inWork := map[*ir.Block]bool{}
		for _, u := range uses[a] {
			if u.Op == ir.OpStore && !inWork[u.Block] {
				inWork[u.Block] = true
				work = append(work, u.Block)
			}
		}
		hasPhi := map[*ir.Block]bool{}
		for len(work) > 0 {
			b := work[len(work)-1]
			work = work[:len(work)-1]
			for _, y := range df[b] {
				if hasPhi[y] {
					continue
				}
				hasPhi[y] = true
				ph := f.NewValue(ir.OpPhi)
				ph.Args = make([]*ir.Value, len(y.Preds))
				y.Append(ph)
				if phiFor[y] == nil {
					phiFor[y] = map[int]*ir.Value{}
				}
				phiFor[y][i] = ph
				if !inWork[y] {
					inWork[y] = true
					work = append(work, y)
				}
			}
		}
	}
	// renaming
	repl := map[*ir.Value]*ir.Value{}
	resolve := func(v *ir.Value) *ir.Value {
		for {
			r, ok := repl[v]
			if !ok {
				return v
			}
			v = r
		}
	}
	cur := make([][]*ir.Value, len(allocas)) // stacks
	for i := range cur {
		cur[i] = []*ir.Value{f.Const(0)}
	}
	removed := map[*ir.Value]bool{}
	var rename func(b *ir.Block)
	rename = func(b *ir.Block) {
		pushed := make([]int, len(allocas))
		for i, ph := range phiFor[b] {
			cur[i] = append(cur[i], ph)
			pushed[i]++
		}
		for _, v := range b.Instrs {
			for k, a := range v.Args {
				if a.Op != ir.OpAlloca {
					v.Args[k] = resolve(a)
				}
			}
			switch v.Op {
			case ir.OpLoad:
				if i, ok := isProm[v.Args[0]]; ok {
					repl[v] = cur[i][len(cur[i])-1]
					removed[v] = true
				}
			case ir.OpStore:
				if i, ok := isProm[v.Args[0]]; ok {
					cur[i] = append(cur[i], v.Args[2])
					pushed[i]++
					removed[v] = true
				}
			}
		}
		if b.Ctrl != nil {
			b.Ctrl = resolve(b.Ctrl)
		}
		for _, s := range b.Succs {
			k := s.PredIndex(b)
			for i, ph := range phiFor[s] {
				ph.Args[k] = cur[i][len(cur[i])-1]
			}
		}
		for _, c := range dom.Children[b] {
			rename(c)
		}
		for i, n := range pushed {
			cur[i] = cur[i][:len(cur[i])-n]
		}
	}
	rename(f.Entry())
	for _, a := range allocas {
		removed[a] = true
	}
	for _, b := range f.Blocks {
		kept := b.Instrs[:0]
		for _, v := range b.Instrs {
			if !removed[v] {
				kept = append(kept, v)
			}
		}
		b.Instrs = kept
	}
	// final sweep: resolve any remaining references to replaced loads (phi args, later blocks)
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		for k, a := range v.Args {
			if a.Op != ir.OpAlloca {
				v.Args[k] = resolve(a)
			}
		}
	})
	for _, b := range f.Blocks {
		if b.Ctrl != nil {
			b.Ctrl = resolve(b.Ctrl)
		}
	}
	replaceTrivialPhis(f)
	return len(allocas)
}
