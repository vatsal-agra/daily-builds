package sable

import "sort"

// LICM hoists loop-invariant, side-effect-free, non-trapping computations into
// a loop preheader (created on demand).
func LICM(f *Func) bool {
	changed := false
	done := map[*Block]bool{}
	for {
		an := Analyze(f)
		loops := an.Loops()
		sort.SliceStable(loops, func(i, j int) bool { return len(loops[i].Blocks) < len(loops[j].Blocks) })
		var lp *Loop
		for _, l := range loops {
			if !done[l.Header] {
				lp = l
				break
			}
		}
		if lp == nil {
			return changed
		}
		done[lp.Header] = true
		ph := preheader(f, lp)
		if ph == nil {
			continue
		}
		// recompute membership info after a possible CFG edit
		an = Analyze(f)
		var cur *Loop
		for _, l := range an.Loops() {
			if l.Header == lp.Header {
				cur = l
			}
		}
		if cur == nil {
			continue
		}
		if hoist(f, an, cur, ph) {
			changed = true
		}
		if ph.ID >= 0 && lp.Header.predIndex(ph) >= 0 {
			changed = changed || false
		}
	}
}

func preheader(f *Func, lp *Loop) *Block {
	var outside []*Block
	for _, p := range lp.Header.Preds {
		if !lp.Blocks[p] {
			outside = append(outside, p)
		}
	}
	if len(outside) == 0 {
		return nil
	}
	if len(outside) == 1 && outside[0].Kind == KJump {
		return outside[0]
	}
	h := lp.Header
	ph := f.NewBlock()
	np := h.NumPhis()
	// collect operands for each header phi along the outside edges
	var idxs []int
	for _, p := range outside {
		idxs = append(idxs, h.predIndex(p))
	}
	newArgs := make([]*Value, np)
	for i := 0; i < np; i++ {
		phi := h.Instrs[i]
		same := phi.Args[idxs[0]]
		allSame := true
		for _, ix := range idxs[1:] {
			if phi.Args[ix] != same {
				allSame = false
			}
		}
		if allSame {
			newArgs[i] = same
			continue
		}
		m := f.newValue(OpPhi)
		for _, ix := range idxs {
			m.Args = append(m.Args, phi.Args[ix])
		}
		ph.insertAt(len(ph.Instrs), m)
		newArgs[i] = m
	}
	// remove outside preds from the header (descending index order)
	sort.Sort(sort.Reverse(sort.IntSlice(idxs)))
	for _, ix := range idxs {
		h.removePredAt(ix)
	}
	ph.Preds = append(ph.Preds, outside...)
	for _, p := range outside {
		for i, s := range p.Succs {
			if s == h {
				p.Succs[i] = ph
			}
		}
	}
	ph.Kind, ph.Succs = KJump, nil
	link(ph, h)
	for i := 0; i < np; i++ {
		h.Instrs[i].Args = append(h.Instrs[i].Args, newArgs[i])
	}
	return ph
}

func hoist(f *Func, an *Analysis, lp *Loop, ph *Block) bool {
	inLoop := func(v *Value) bool { return lp.Blocks[v.Block] }
	changed := false
	for again := true; again; {
		again = false
		for _, b := range an.RPO {
			if !lp.Blocks[b] {
				continue
			}
			keep := b.Instrs[:0]
			for _, v := range b.Instrs {
				ok := v.Op != OpPhi && v.Op != OpConst && v.Op != OpParam && v.Pure()
				if ok {
					for _, a := range v.Args {
						if inLoop(a) {
							ok = false
							break
						}
					}
				}
				if ok {
					v.Block = ph
					ph.Instrs = append(ph.Instrs, v)
					changed, again = true, true
				} else {
					keep = append(keep, v)
				}
			}
			b.Instrs = keep
		}
	}
	return changed
}
