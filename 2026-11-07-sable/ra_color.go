package sable

import "sort"

// Graph-colouring allocator: Chaitin–Briggs with optimistic colouring,
// conservative (Briggs) copy coalescing, call-crossing colour restrictions and
// spill-and-retry. Spilled values are rewritten into short-lived temporaries.

type gcNode struct {
	adj    map[int]bool
	forbid []bool // colours this node may not take (caller-saved if live across a call)
	cost   float64
	temp   bool // introduced by spill code: never spill again
}

func graphColor(mf *MFunc, t Target) (*Assignment, AllocStats) {
	st := AllocStats{Alg: GraphColor}
	spilledSlot := map[int]bool{}
	_ = spilledSlot
	for round := 1; round <= 200; round++ {
		st.Rounds = round
		as, spills, coalesced := tryColor(mf, t)
		st.Coalesced = coalesced
		if len(spills) == 0 {
			return as, st
		}
		st.Spilled += len(spills)
		insertSpillCode(mf, spills)
	}
	panic("graph colouring failed to converge in " + mf.Name)
}

func isTemp(mf *MFunc, v int) bool { return mf.TempVRegs[v] }

// insertSpillCode gives every spilled vreg a frame slot and rewrites each
// use/def through a fresh temporary with an explicit ld/st.
func insertSpillCode(mf *MFunc, spills map[int]bool) {
	if mf.TempVRegs == nil {
		mf.TempVRegs = map[int]bool{}
	}
	slot := map[int]int{}
	var vs []int
	for v := range spills {
		vs = append(vs, v)
	}
	sort.Ints(vs)
	for _, v := range vs {
		slot[v] = mf.NSlots
		mf.NSlots++
	}
	for _, b := range mf.Blocks {
		var out []MInstr
		for _, in := range b.Instrs {
			tmp := map[int]int{}
			for _, o := range in.uses() {
				if o.K == OVReg && spills[int(o.V)] {
					v := int(o.V)
					tv, ok := tmp[v]
					if !ok {
						tv = mf.newVReg()
						mf.TempVRegs[tv] = true
						tmp[v] = tv
						out = append(out, MInstr{Op: MLd, D: VReg(tv), Slot: slot[v]})
					}
					*o = VReg(tv)
				}
			}
			var after []MInstr
			if d := in.def(); d != nil && d.K == OVReg && spills[int(d.V)] {
				v := int(d.V)
				tv := mf.newVReg()
				mf.TempVRegs[tv] = true
				*d = VReg(tv)
				after = append(after, MInstr{Op: MSt, A: VReg(tv), Slot: slot[v]})
			}
			out = append(out, in)
			out = append(out, after...)
		}
		b.Instrs = out
	}
}

func tryColor(mf *MFunc, t Target) (*Assignment, map[int]bool, int) {
	n := mf.NVRegs
	lv := computeLiveness(mf)
	nodes := make([]*gcNode, n)
	for i := range nodes {
		nodes[i] = &gcNode{adj: map[int]bool{}, forbid: make([]bool, t.K)}
	}
	addEdge := func(a, b int) {
		if a != b {
			nodes[a].adj[b] = true
			nodes[b].adj[a] = true
		}
	}
	type move struct{ d, s int }
	var moves []move
	for _, b := range mf.Blocks {
		w := 1.0
		for i := 0; i < b.Depth && i < 6; i++ {
			w *= 10
		}
		live := newBitset(n)
		live.copyFrom(lv.out[b])
		for i := len(b.Instrs) - 1; i >= 0; i-- {
			in := &b.Instrs[i]
			if in.Op == MCall {
				for _, v := range live.members() {
					for r := 0; r < t.Caller; r++ {
						nodes[v].forbid[r] = true
					}
				}
			}
			if d := in.def(); d != nil && d.K == OVReg {
				dv := int(d.V)
				nodes[dv].cost += w
				skip := -1
				if in.Op == MMov && in.A.K == OVReg {
					skip = int(in.A.V)
					moves = append(moves, move{dv, skip})
				}
				for _, l := range live.members() {
					if l != skip {
						addEdge(dv, l)
					}
				}
				live.clear(dv)
			}
			for _, o := range in.uses() {
				if o.K == OVReg {
					nodes[int(o.V)].cost += w
					live.set(int(o.V))
				}
			}
		}
	}
	for v := 0; v < n; v++ {
		if isTemp(mf, v) {
			nodes[v].temp = true
		}
	}
	// ---- conservative coalescing ----
	alias := make([]int, n)
	for i := range alias {
		alias[i] = i
	}
	find := func(x int) int {
		for alias[x] != x {
			alias[x] = alias[alias[x]]
			x = alias[x]
		}
		return x
	}
	avail := func(nd *gcNode) int {
		c := 0
		for _, f := range nd.forbid {
			if !f {
				c++
			}
		}
		return c
	}
	coalesced := 0
	for changed := true; changed; {
		changed = false
		for _, m := range moves {
			u, v := find(m.d), find(m.s)
			if u == v || nodes[u].adj[v] {
				continue
			}
			nu, nv := nodes[u], nodes[v]
			merged := make([]bool, t.K)
			for r := range merged {
				merged[r] = nu.forbid[r] || nv.forbid[r]
			}
			ka := 0
			for _, f := range merged {
				if !f {
					ka++
				}
			}
			if ka == 0 {
				continue
			}
			union := map[int]bool{}
			for x := range nu.adj {
				union[x] = true
			}
			for x := range nv.adj {
				union[x] = true
			}
			sig := 0
			for x := range union {
				deg := len(nodes[x].adj)
				if nu.adj[x] && nv.adj[x] {
					deg--
				}
				if deg >= avail(nodes[x]) {
					sig++
				}
			}
			if sig >= ka {
				continue
			}
			// merge v into u
			for x := range nv.adj {
				delete(nodes[x].adj, v)
				if x != u {
					nodes[x].adj[u] = true
					nu.adj[x] = true
				}
			}
			nv.adj = map[int]bool{}
			nu.forbid = merged
			nu.cost += nv.cost
			nu.temp = nu.temp || nv.temp
			alias[v] = u
			coalesced++
			changed = true
		}
	}
	// ---- simplify / potential spill ----
	var live []int
	for v := 0; v < n; v++ {
		if find(v) == v {
			live = append(live, v)
		}
	}
	removed := map[int]bool{}
	deg := map[int]int{}
	for _, v := range live {
		deg[v] = len(nodes[v].adj)
	}
	var stack []int
	remaining := len(live)
	for remaining > 0 {
		pick := -1
		for _, v := range live { // trivially colourable first
			if !removed[v] && deg[v] < avail(nodes[v]) {
				pick = v
				break
			}
		}
		if pick < 0 { // optimistic: push the cheapest-per-degree node
			best := 0.0
			for _, v := range live {
				if removed[v] {
					continue
				}
				c := nodes[v].cost / float64(deg[v]+1)
				if nodes[v].temp {
					c = 1e18
				}
				if pick < 0 || c < best {
					pick, best = v, c
				}
			}
		}
		removed[pick] = true
		remaining--
		stack = append(stack, pick)
		for x := range nodes[pick].adj {
			if !removed[x] {
				deg[x]--
			}
		}
	}
	// ---- select ----
	color := map[int]int{}
	spills := map[int]bool{}
	partners := map[int][]int{}
	for _, m := range moves {
		u, v := find(m.d), find(m.s)
		if u != v {
			partners[u] = append(partners[u], v)
			partners[v] = append(partners[v], u)
		}
	}
	for i := len(stack) - 1; i >= 0; i-- {
		v := stack[i]
		bad := make([]bool, t.K)
		for r, f := range nodes[v].forbid {
			bad[r] = f
		}
		for x := range nodes[v].adj {
			if c, ok := color[x]; ok {
				bad[c] = true
			}
		}
		pick := -1
		for _, p := range partners[v] { // biased colouring: try to match a copy partner
			if c, ok := color[p]; ok && !bad[c] {
				pick = c
				break
			}
		}
		if pick < 0 {
			crosses := false
			for r := 0; r < t.Caller; r++ {
				if nodes[v].forbid[r] {
					crosses = true
				}
			}
			_ = crosses
			for r := 0; r < t.K; r++ { // caller-saved first: callee-saved cost a save/restore
				if !bad[r] {
					pick = r
					break
				}
			}
		}
		if pick < 0 {
			spills[v] = true
			continue
		}
		color[v] = pick
	}
	if len(spills) > 0 {
		// spill every vreg of the failed coalesced groups
		out := map[int]bool{}
		for v := 0; v < n; v++ {
			if spills[find(v)] {
				out[v] = true
			}
		}
		return nil, out, coalesced
	}
	as := &Assignment{Reg: map[int]int{}, Slot: map[int]int{}}
	for v := 0; v < n; v++ {
		if c, ok := color[find(v)]; ok {
			as.Reg[v] = c
		}
	}
	return as, nil, coalesced
}
