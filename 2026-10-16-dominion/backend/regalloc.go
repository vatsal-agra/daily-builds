package backend

import "sort"

// interval is a live range [start,end] in instruction positions (use = 2*i, def = 2*i+1).
type interval struct {
	v          int
	start, end int
	crosses    bool // live across a call: must live in a callee-saved register or memory
	reg        int  // -1 when spilled
	off        int  // frame offset of the spill slot (when spilled)
}

type liveness struct {
	order  []*mblock
	succ   map[*mblock][]*mblock
	nIdx   int
	calls  []int // positions (2*i) of call instructions
	ivals  []*interval
	byVreg []*interval
}

func (mf *mfunc) analyze() *liveness {
	lv := &liveness{succ: map[*mblock][]*mblock{}, order: mf.blocks}
	byIR := map[interface{}]*mblock{}
	for _, mb := range mf.blocks {
		byIR[mb.b] = mb
	}
	idx := 0
	for _, mb := range mf.blocks {
		mb.pos = idx
		idx += len(mb.instrs)
		for _, s := range mb.b.Succs {
			lv.succ[mb] = append(lv.succ[mb], byIR[s])
		}
	}
	lv.nIdx = idx
	n := mf.nvreg
	gen := map[*mblock]bitset{}
	kill := map[*mblock]bitset{}
	for _, mb := range mf.blocks {
		g, k := newBitset(n), newBitset(n)
		for _, mi := range mb.instrs {
			for _, u := range uses(mi) {
				if !k.has(u) {
					g.set(u)
				}
			}
			for _, d := range defs(mi) {
				k.set(d)
			}
		}
		gen[mb], kill[mb] = g, k
		mb.liveIn, mb.liveOut = newBitset(n), newBitset(n)
	}
	for changed := true; changed; {
		changed = false
		for i := len(mf.blocks) - 1; i >= 0; i-- {
			mb := mf.blocks[i]
			for _, s := range lv.succ[mb] {
				if mb.liveOut.or(s.liveIn) {
					changed = true
				}
			}
			in := newBitset(n)
			in.copyFrom(mb.liveOut)
			kill[mb].each(func(d int) { in.clear(d) })
			in.or(gen[mb])
			if mb.liveIn.or(in) {
				changed = true
			}
		}
	}
	lv.byVreg = make([]*interval, n)
	extend := func(v, p int) {
		iv := lv.byVreg[v]
		if iv == nil {
			iv = &interval{v: v, start: p, end: p, reg: -1}
			lv.byVreg[v] = iv
			return
		}
		if p < iv.start {
			iv.start = p
		}
		if p > iv.end {
			iv.end = p
		}
	}
	for _, mb := range mf.blocks {
		if len(mb.instrs) > 0 {
			bs, be := 2*mb.pos, 2*(mb.pos+len(mb.instrs)-1)+1
			mb.liveOut.each(func(v int) { extend(v, be) })
			mb.liveIn.each(func(v int) { extend(v, bs) })
		}
		for i, mi := range mb.instrs {
			p := 2 * (mb.pos + i)
			for _, u := range uses(mi) {
				extend(u, p)
			}
			for _, d := range defs(mi) {
				extend(d, p+1)
			}
			if mi.k == kCall {
				lv.calls = append(lv.calls, p)
			}
		}
	}
	for _, iv := range lv.byVreg {
		if iv == nil {
			continue
		}
		i := sort.SearchInts(lv.calls, iv.start+1) // first call strictly after start
		iv.crosses = i < len(lv.calls) && lv.calls[i] < iv.end
		lv.ivals = append(lv.ivals, iv)
	}
	sort.Slice(lv.ivals, func(i, j int) bool {
		if lv.ivals[i].start != lv.ivals[j].start {
			return lv.ivals[i].start < lv.ivals[j].start
		}
		return lv.ivals[i].v < lv.ivals[j].v
	})
	return lv
}

// linearScan assigns registers (Poletto & Sarkar). Registers [0,callerSaved) are clobbered by calls;
// [callerSaved,k) are callee-saved. Intervals crossing calls may only use callee-saved registers.
// When no register is free the interval (or the active one ending last) is spilled whole.
func linearScan(ivals []*interval, k, callerSaved int) (spills int) {
	free := make([]bool, k)
	for i := range free {
		free[i] = true
	}
	var active []*interval // sorted by end
	allowed := func(iv *interval, r int) bool { return !iv.crosses || r >= callerSaved }
	for _, iv := range ivals {
		// expire
		j := 0
		for _, a := range active {
			if a.end < iv.start {
				free[a.reg] = true
			} else {
				active[j] = a
				j++
			}
		}
		active = active[:j]
		got := -1
		if iv.crosses {
			for r := callerSaved; r < k; r++ {
				if free[r] {
					got = r
					break
				}
			}
		} else {
			for r := 0; r < k; r++ {
				if free[r] {
					got = r
					break
				}
			}
		}
		if got < 0 {
			var victim *interval
			for _, a := range active {
				if allowed(iv, a.reg) && (victim == nil || a.end > victim.end) {
					victim = a
				}
			}
			if victim != nil && victim.end > iv.end {
				got = victim.reg
				victim.reg = -1
				spills++
				for x, a := range active {
					if a == victim {
						active = append(active[:x], active[x+1:]...)
						break
					}
				}
			} else {
				iv.reg = -1
				spills++
				continue
			}
		} else {
			free[got] = false
		}
		iv.reg = got
		active = append(active, iv)
		sort.SliceStable(active, func(x, y int) bool { return active[x].end < active[y].end })
	}
	return spills
}
