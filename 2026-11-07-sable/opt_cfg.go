package sable

// SimplifyCFG: fold constant branches, drop unreachable blocks, merge
// straight-line blocks, bypass empty forwarding blocks, remove trivial phis.
// Invariant kept throughout: no block has two edges to the same successor.
func SimplifyCFG(f *Func) bool {
	changed := false
	for {
		c := false
		c = foldConstBranches(f) || c
		c = f.removeUnreachable() || c
		c = removeTrivialPhis(f) || c
		c = mergeBlocks(f) || c
		c = bypassEmpty(f) || c
		if !c {
			return changed
		}
		changed = true
	}
}

func foldConstBranches(f *Func) bool {
	ch := false
	for _, b := range f.Blocks {
		if b.Kind != KBr {
			continue
		}
		var taken int = -1
		if b.Ctrl.Op == OpConst {
			if b.Ctrl.Imm != 0 {
				taken = 0
			} else {
				taken = 1
			}
		}
		if taken < 0 {
			continue
		}
		dead := b.Succs[1-taken]
		keep := b.Succs[taken]
		dropEdgeTo(b, dead)
		b.Kind, b.Ctrl, b.Succs = KJump, nil, []*Block{keep}
		ch = true
	}
	return ch
}

func removeTrivialPhis(f *Func) bool {
	ch := false
	for {
		repl := map[*Value]*Value{}
		for _, b := range f.Blocks {
			for _, v := range b.Instrs {
				if v.Op != OpPhi {
					break
				}
				var same *Value
				triv := true
				for _, a := range v.Args {
					if a == v || a == same {
						continue
					}
					if same != nil {
						triv = false
						break
					}
					same = a
				}
				if triv && same != nil {
					repl[v] = same
				}
			}
		}
		if len(repl) == 0 {
			return ch
		}
		for _, b := range f.Blocks {
			keep := b.Instrs[:0]
			for _, v := range b.Instrs {
				if _, dead := repl[v]; !dead {
					keep = append(keep, v)
				}
			}
			b.Instrs = keep
		}
		f.replaceAllUses(repl)
		ch = true
	}
}

func mergeBlocks(f *Func) bool {
	ch := false
	for again := true; again; {
		again = false
		for _, b := range f.Blocks {
			if b.Kind != KJump || len(b.Succs) != 1 {
				continue
			}
			s := b.Succs[0]
			if s == b || s == f.Entry || len(s.Preds) != 1 {
				continue
			}
			repl := map[*Value]*Value{}
			np := s.NumPhis()
			for _, p := range s.Instrs[:np] {
				repl[p] = p.Args[0]
			}
			for _, v := range s.Instrs[np:] {
				v.Block = b
				b.Instrs = append(b.Instrs, v)
			}
			b.Kind, b.Ctrl, b.Succs = s.Kind, s.Ctrl, s.Succs
			for _, t := range b.Succs {
				for i, p := range t.Preds {
					if p == s {
						t.Preds[i] = b
					}
				}
			}
			s.Instrs, s.Succs, s.Preds = nil, nil, nil
			var keep []*Block
			for _, x := range f.Blocks {
				if x != s {
					keep = append(keep, x)
				}
			}
			f.Blocks = keep
			f.replaceAllUses(repl)
			ch, again = true, true
			break
		}
	}
	return ch
}

func bypassEmpty(f *Func) bool {
	ch := false
	for again := true; again; {
		again = false
		for _, e := range f.Blocks {
			if e == f.Entry || len(e.Instrs) != 0 || e.Kind != KJump || len(e.Preds) == 0 {
				continue
			}
			t := e.Succs[0]
			if t == e {
				continue
			}
			overlap := false
			for _, p := range e.Preds {
				if t.predIndex(p) >= 0 {
					overlap = true
				}
			}
			if overlap {
				continue
			}
			idx := t.predIndex(e)
			np := t.NumPhis()
			args := make([]*Value, np)
			for i := 0; i < np; i++ {
				args[i] = t.Instrs[i].Args[idx]
			}
			t.removePredAt(idx)
			for _, p := range e.Preds {
				for i, s := range p.Succs {
					if s == e {
						p.Succs[i] = t
					}
				}
				t.Preds = append(t.Preds, p)
				for i := 0; i < np; i++ {
					t.Instrs[i].Args = append(t.Instrs[i].Args, args[i])
				}
			}
			e.Preds, e.Succs = nil, nil
			var keep []*Block
			for _, x := range f.Blocks {
				if x != e {
					keep = append(keep, x)
				}
			}
			f.Blocks = keep
			ch, again = true, true
			break
		}
	}
	return ch
}
