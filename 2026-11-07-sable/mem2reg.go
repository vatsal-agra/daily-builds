package sable

// Mem2Reg promotes slot load/stores into SSA values using pruned phi placement:
// phis are inserted at the iterated dominance frontier of each slot's stores,
// but only where the slot is live-in, so no operand is ever "undefined".
func Mem2Reg(f *Func) {
	f.removeUnreachable()
	an := Analyze(f)
	n := f.NSlots
	if n == 0 {
		return
	}
	words := (n + 63) / 64
	type bits []uint64
	newBits := func() bits { return make(bits, words) }
	set := func(b bits, i int) { b[i/64] |= 1 << (uint(i) % 64) }
	has := func(b bits, i int) bool { return b[i/64]&(1<<(uint(i)%64)) != 0 }

	use := map[*Block]bits{} // upward-exposed loads
	def := map[*Block]bits{}
	defBlocks := make([][]*Block, n)
	for _, b := range f.Blocks {
		u, d := newBits(), newBits()
		for _, v := range b.Instrs {
			s := int(v.Imm)
			switch v.Op {
			case OpLoad:
				if !has(d, s) {
					set(u, s)
				}
			case OpStore:
				if !has(d, s) {
					defBlocks[s] = append(defBlocks[s], b)
				}
				set(d, s)
			}
		}
		use[b], def[b] = u, d
	}
	// backward liveness over slots
	liveIn := map[*Block]bits{}
	for _, b := range f.Blocks {
		liveIn[b] = newBits()
	}
	for changed := true; changed; {
		changed = false
		for i := len(an.RPO) - 1; i >= 0; i-- {
			b := an.RPO[i]
			out := newBits()
			for _, s := range b.Succs {
				for w := range out {
					out[w] |= liveIn[s][w]
				}
			}
			for w := 0; w < words; w++ {
				nw := use[b][w] | (out[w] &^ def[b][w])
				if nw != liveIn[b][w] {
					liveIn[b][w] = nw
					changed = true
				}
			}
		}
	}
	// phi placement
	phiSlot := map[*Value]int{}
	for s := 0; s < n; s++ {
		placed := map[*Block]bool{}
		work := append([]*Block(nil), defBlocks[s]...)
		for len(work) > 0 {
			b := work[len(work)-1]
			work = work[:len(work)-1]
			for _, d := range an.DF[b] {
				if placed[d] || !has(liveIn[d], s) {
					continue
				}
				placed[d] = true
				phi := f.newValue(OpPhi)
				phi.Args = make([]*Value, len(d.Preds))
				d.insertAt(d.NumPhis(), phi)
				phiSlot[phi] = s
				if !containsBlock(defBlocks[s], d) {
					work = append(work, d)
				}
			}
		}
	}
	// renaming over the dominator tree
	stacks := make([][]*Value, n)
	repl := map[*Value]*Value{}
	var entryZero *Value // slot read before any store (never happens for pruned SSA of checked programs)
	getZero := func() *Value {
		if entryZero == nil {
			entryZero = f.newValue(OpConst)
		}
		return entryZero
	}
	top := func(s int) *Value {
		if len(stacks[s]) == 0 {
			return getZero()
		}
		return stacks[s][len(stacks[s])-1]
	}
	resolve := func(v *Value) *Value {
		for {
			w, ok := repl[v]
			if !ok {
				return v
			}
			v = w
		}
	}
	var rename func(b *Block)
	rename = func(b *Block) {
		pushed := make([]int, 0, 8)
		var keep []*Value
		for _, v := range b.Instrs {
			for i, a := range v.Args {
				v.Args[i] = resolve(a)
			}
			switch v.Op {
			case OpPhi:
				s := phiSlot[v]
				stacks[s] = append(stacks[s], v)
				pushed = append(pushed, s)
				keep = append(keep, v)
			case OpLoad:
				repl[v] = top(int(v.Imm))
			case OpStore:
				s := int(v.Imm)
				stacks[s] = append(stacks[s], v.Args[0])
				pushed = append(pushed, s)
			default:
				keep = append(keep, v)
			}
		}
		b.Instrs = keep
		if b.Ctrl != nil {
			b.Ctrl = resolve(b.Ctrl)
		}
		for _, s := range b.Succs {
			pi := s.predIndex(b)
			for _, v := range s.Instrs {
				if v.Op != OpPhi {
					break
				}
				if sl, ok := phiSlot[v]; ok && v.Args[pi] == nil {
					v.Args[pi] = top(sl)
				}
			}
		}
		for _, c := range an.Children[b] {
			rename(c)
		}
		for _, s := range pushed {
			stacks[s] = stacks[s][:len(stacks[s])-1]
		}
	}
	rename(f.Entry)
	if entryZero != nil {
		f.Entry.insertAt(0, entryZero)
	}
	// a phi arg resolved before its source load was renamed can still point at a load
	f.replaceAllUses(repl)
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			if v.Op == OpPhi {
				for i, a := range v.Args {
					v.Args[i] = resolve(a)
				}
			}
		}
	}
	f.NSlots = 0
	f.renumber()
}
