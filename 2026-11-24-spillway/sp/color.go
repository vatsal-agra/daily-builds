package sp

import "math"

// Chaitin–Briggs graph colouring in the formulation of Appel & George
// ("Iterated Register Coalescing"): simplify / coalesce / freeze / potential
// spill worklists, Briggs-conservative coalescing, optimistic select.

type nstate uint8

const (
	nsNone nstate = iota // not a live variable
	nsInitial
	nsSimplify
	nsFreeze
	nsSpill
	nsStack
	nsCoalesced
	nsColored
	nsSpilled
)

type mstate uint8

const (
	msWork mstate = iota
	msActive
	msCoalesced
	msConstrained
	msFrozen
)

type move struct{ dst, src int }

type colorer struct {
	K      int
	n      int
	adjSet []Bitset
	adj    [][]int
	deg    []int
	mlist  [][]int
	moves  []move
	mst    []mstate
	st     []nstate
	alias  []int
	color  []int
	cost   []float64
	unsp   []bool

	simplifyWL, freezeWL, spillWL []int
	workMoves                     []int
	stack                         []int
	coalesce                      bool
}

func (c *colorer) addEdge(u, v int) {
	if u == v || c.adjSet[u].Has(v) {
		return
	}
	c.adjSet[u].Set(v)
	c.adjSet[v].Set(u)
	c.adj[u] = append(c.adj[u], v)
	c.adj[v] = append(c.adj[v], u)
	c.deg[u]++
	c.deg[v]++
}

func (c *colorer) adjacent(n int) []int {
	var out []int
	for _, w := range c.adj[n] {
		if c.st[w] != nsStack && c.st[w] != nsCoalesced {
			out = append(out, w)
		}
	}
	return out
}

func (c *colorer) nodeMoves(n int) []int {
	var out []int
	for _, m := range c.mlist[n] {
		if c.mst[m] == msActive || c.mst[m] == msWork {
			out = append(out, m)
		}
	}
	return out
}

func (c *colorer) moveRelated(n int) bool {
	for _, m := range c.mlist[n] {
		if c.mst[m] == msActive || c.mst[m] == msWork {
			return true
		}
	}
	return false
}

func (c *colorer) getAlias(n int) int {
	for c.st[n] == nsCoalesced {
		n = c.alias[n]
	}
	return n
}

func (c *colorer) push(n int, s nstate) {
	c.st[n] = s
	switch s {
	case nsSimplify:
		c.simplifyWL = append(c.simplifyWL, n)
	case nsFreeze:
		c.freezeWL = append(c.freezeWL, n)
	case nsSpill:
		c.spillWL = append(c.spillWL, n)
	}
}

func (c *colorer) enableMoves(nodes ...int) {
	for _, n := range nodes {
		for _, m := range c.nodeMoves(n) {
			if c.mst[m] == msActive {
				c.mst[m] = msWork
				c.workMoves = append(c.workMoves, m)
			}
		}
	}
}

func (c *colorer) decrementDegree(m int) {
	d := c.deg[m]
	c.deg[m]--
	if d == c.K {
		c.enableMoves(append(c.adjacent(m), m)...)
		if c.st[m] == nsSpill {
			if c.moveRelated(m) {
				c.push(m, nsFreeze)
			} else {
				c.push(m, nsSimplify)
			}
		}
	}
}

func (c *colorer) addWorkList(u int) {
	if c.st[u] == nsFreeze && !c.moveRelated(u) && c.deg[u] < c.K {
		c.push(u, nsSimplify)
	}
}

// briggs: coalesced node would have fewer than K neighbours of significant degree.
func (c *colorer) briggs(u, v int) bool {
	seen := map[int]bool{}
	cnt := 0
	for _, side := range [][]int{c.adjacent(u), c.adjacent(v)} {
		for _, w := range side {
			if !seen[w] {
				seen[w] = true
				if c.deg[w] >= c.K {
					cnt++
				}
			}
		}
	}
	return cnt < c.K
}

func (c *colorer) combine(u, v int) {
	c.st[v] = nsCoalesced // lazily removed from freeze/spill lists
	c.alias[v] = u
	c.mlist[u] = append(c.mlist[u], c.mlist[v]...)
	c.unsp[u] = c.unsp[u] || c.unsp[v]
	c.cost[u] += c.cost[v]
	c.enableMoves(v)
	for _, t := range c.adj[v] {
		if c.st[t] == nsStack || c.st[t] == nsCoalesced {
			continue
		}
		c.addEdge(t, u)
		c.decrementDegree(t)
	}
	if c.deg[u] >= c.K && c.st[u] == nsFreeze {
		c.push(u, nsSpill)
	}
}

func (c *colorer) freezeMoves(u int) {
	for _, m := range c.nodeMoves(u) {
		x, y := c.getAlias(c.moves[m].dst), c.getAlias(c.moves[m].src)
		v := y
		if y == c.getAlias(u) {
			v = x
		}
		c.mst[m] = msFrozen
		if !c.moveRelated(v) && c.deg[v] < c.K && c.st[v] == nsFreeze {
			c.push(v, nsSimplify)
		}
	}
}

func pop(list *[]int, want nstate, st []nstate) (int, bool) {
	for len(*list) > 0 {
		n := (*list)[len(*list)-1]
		*list = (*list)[:len(*list)-1]
		if st[n] == want {
			return n, true
		}
	}
	return 0, false
}

// colorRound attempts one colouring of f. It returns the assignment (valid
// only if spills is empty) and the registers that must be spilled.
func colorRound(f *Function, K int, unsp []bool, coalesce bool) (assign []int, spills []int) {
	n := f.NumRegs
	c := &colorer{K: K, n: n, coalesce: coalesce}
	c.adjSet = make([]Bitset, n)
	for i := range c.adjSet {
		c.adjSet[i] = NewBitset(n)
	}
	c.adj = make([][]int, n)
	c.deg = make([]int, n)
	c.mlist = make([][]int, n)
	c.st = make([]nstate, n)
	c.alias = make([]int, n)
	c.color = make([]int, n)
	c.unsp = append([]bool(nil), unsp...)
	c.cost = spillCosts(f)
	for i := range c.color {
		c.color[i] = -1
	}
	lv := f.Liveness()
	// mark occurring registers
	for _, b := range f.Blocks {
		for i := range b.Instrs {
			in := &b.Instrs[i]
			if in.HasDst() {
				c.st[in.Dst] = nsInitial
			}
			for _, u := range in.Uses() {
				c.st[u] = nsInitial
			}
		}
	}
	// build interference graph and move list
	f.LiveAfter(lv, func(bi, ii int, live Bitset) {
		in := &f.Blocks[bi].Instrs[ii]
		if !in.HasDst() {
			return
		}
		d := in.Dst
		src := -1
		if in.Op == OpMov && !in.Args[0].Imm && coalesce {
			src = in.Args[0].Reg
			if src != d {
				mi := len(c.moves)
				c.moves = append(c.moves, move{d, src})
				c.mst = append(c.mst, msWork)
				c.mlist[d] = append(c.mlist[d], mi)
				c.mlist[src] = append(c.mlist[src], mi)
				c.workMoves = append(c.workMoves, mi)
			}
		}
		live.each(func(l int) {
			if l != d && l != src {
				c.addEdge(l, d)
			}
		})
	})
	// make worklists
	for v := 0; v < n; v++ {
		if c.st[v] != nsInitial {
			continue
		}
		switch {
		case c.deg[v] >= K:
			c.push(v, nsSpill)
		case c.moveRelated(v):
			c.push(v, nsFreeze)
		default:
			c.push(v, nsSimplify)
		}
	}
	for {
		if v, ok := pop(&c.simplifyWL, nsSimplify, c.st); ok {
			c.st[v] = nsStack
			c.stack = append(c.stack, v)
			for _, w := range c.adjacent(v) {
				c.decrementDegree(w)
			}
			continue
		}
		if len(c.workMoves) > 0 {
			m := c.workMoves[len(c.workMoves)-1]
			c.workMoves = c.workMoves[:len(c.workMoves)-1]
			if c.mst[m] != msWork {
				continue
			}
			x, y := c.getAlias(c.moves[m].dst), c.getAlias(c.moves[m].src)
			switch {
			case x == y:
				c.mst[m] = msCoalesced
				c.addWorkList(x)
			case c.adjSet[x].Has(y):
				c.mst[m] = msConstrained
				c.addWorkList(x)
				c.addWorkList(y)
			case c.briggs(x, y):
				c.mst[m] = msCoalesced
				c.combine(x, y)
				c.addWorkList(x)
			default:
				c.mst[m] = msActive
			}
			continue
		}
		if v, ok := pop(&c.freezeWL, nsFreeze, c.st); ok {
			c.push(v, nsSimplify)
			c.freezeMoves(v)
			continue
		}
		// select a potential spill: cheapest cost per degree, never a spill temp
		best, bestScore := -1, math.Inf(1)
		for _, v := range c.spillWL {
			if c.st[v] != nsSpill {
				continue
			}
			score := c.cost[v] / float64(max(c.deg[v], 1))
			if c.unsp[v] {
				score = math.MaxFloat64
			}
			if best < 0 || score < bestScore || (score == bestScore && v < best) {
				best, bestScore = v, score
			}
		}
		if best >= 0 {
			c.push(best, nsSimplify)
			c.freezeMoves(best)
			continue
		}
		break
	}
	// select
	for len(c.stack) > 0 {
		v := c.stack[len(c.stack)-1]
		c.stack = c.stack[:len(c.stack)-1]
		used := make([]bool, K)
		for _, w := range c.adj[v] {
			a := c.getAlias(w)
			if c.st[a] == nsColored {
				used[c.color[a]] = true
			}
		}
		pick := -1
		// biased colouring: prefer the register of a move partner
		for _, m := range c.mlist[v] {
			for _, e := range []int{c.moves[m].dst, c.moves[m].src} {
				a := c.getAlias(e)
				if a != v && c.st[a] == nsColored && !used[c.color[a]] {
					pick = c.color[a]
				}
			}
		}
		if pick < 0 {
			for k := 0; k < K; k++ {
				if !used[k] {
					pick = k
					break
				}
			}
		}
		if pick < 0 {
			c.st[v] = nsSpilled
			spills = append(spills, v)
		} else {
			c.st[v] = nsColored
			c.color[v] = pick
		}
	}
	if len(spills) > 0 {
		return nil, spills
	}
	assign = make([]int, n)
	for v := 0; v < n; v++ {
		assign[v] = -1
		if c.st[v] == nsColored {
			assign[v] = c.color[v]
		}
	}
	for v := 0; v < n; v++ {
		if c.st[v] == nsCoalesced {
			assign[v] = c.color[c.getAlias(v)]
		}
	}
	return assign, nil
}
