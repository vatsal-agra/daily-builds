package sp

import (
	"fmt"
	"sort"
)

// linearRound is one pass of Poletto–Sarkar linear-scan allocation over
// conservative single-range intervals. When all K registers are busy it
// spills the interval (active or incoming) that ends furthest in the future.
// Spill temporaries are never chosen while an alternative exists.
func linearRound(f *Function, K int, unsp []bool) (assign []int, spills []int, err error) {
	lv := f.Liveness()
	ivs, _ := f.Intervals(lv)
	sort.Slice(ivs, func(i, j int) bool {
		if ivs[i].Start != ivs[j].Start {
			return ivs[i].Start < ivs[j].Start
		}
		return ivs[i].Reg < ivs[j].Reg
	})
	// move hints: dst of `dst = mov src` would like src's register
	hint := map[int]int{}
	for _, b := range f.Blocks {
		for i := range b.Instrs {
			in := &b.Instrs[i]
			if in.Op == OpMov && !in.Args[0].Imm {
				if _, ok := hint[in.Dst]; !ok {
					hint[in.Dst] = in.Args[0].Reg
				}
			}
		}
	}
	end := map[int]int{}
	for _, iv := range ivs {
		end[iv.Reg] = iv.End
	}
	assign = make([]int, f.NumRegs)
	for i := range assign {
		assign[i] = -1
	}
	free := make([]bool, K)
	for i := range free {
		free[i] = true
	}
	var active []int // registers (vregs) currently holding a physical reg
	spilled := map[int]bool{}
	isUnsp := func(r int) bool { return r < len(unsp) && unsp[r] }
	for _, iv := range ivs {
		// expire
		keep := active[:0]
		for _, a := range active {
			if end[a] < iv.Start {
				free[assign[a]] = true
			} else {
				keep = append(keep, a)
			}
		}
		active = keep
		reg := -1
		if h, ok := hint[iv.Reg]; ok && assign[h] >= 0 && free[assign[h]] {
			reg = assign[h]
		}
		if reg < 0 {
			for k := 0; k < K; k++ {
				if free[k] {
					reg = k
					break
				}
			}
		}
		if reg >= 0 {
			free[reg] = false
			assign[iv.Reg] = reg
			active = append(active, iv.Reg)
			continue
		}
		// all busy: spill the spillable interval ending last
		cand := -1
		if !isUnsp(iv.Reg) {
			cand = iv.Reg
		}
		for _, a := range active {
			if isUnsp(a) {
				continue
			}
			if cand < 0 || end[a] > end[cand] || (end[a] == end[cand] && a > cand) {
				cand = a
			}
		}
		if cand < 0 {
			return nil, nil, fmt.Errorf("linear: cannot allocate with K=%d: every live interval is an unspillable spill temporary", K)
		}
		spilled[cand] = true
		spills = append(spills, cand)
		if cand == iv.Reg {
			continue
		}
		assign[iv.Reg] = assign[cand]
		assign[cand] = -1
		for i, a := range active {
			if a == cand {
				active[i] = iv.Reg
				break
			}
		}
	}
	sort.Ints(spills)
	if len(spills) > 0 {
		return nil, spills, nil
	}
	return assign, nil, nil
}
