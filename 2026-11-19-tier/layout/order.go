package layout

import (
	"sort"
)

type adjE struct{ to, w int }

// pg is the "proper" layered graph: every edge spans exactly one rank because
// long edges were split by virtual (dummy) nodes.
type pg struct {
	n       int
	rank    []int
	virtual []bool
	w, h    []float64 // node extent in layout orientation (w along the layer)
	up      [][]adjE
	down    [][]adjE
	layers  [][]int
	pos     []int
	real    []int // index in the component's node list, -1 for dummies
}

func (g *pg) addNode(rank int, virtual bool, w, h float64, real int) int {
	id := g.n
	g.n++
	g.rank = append(g.rank, rank)
	g.virtual = append(g.virtual, virtual)
	g.w = append(g.w, w)
	g.h = append(g.h, h)
	g.up = append(g.up, nil)
	g.down = append(g.down, nil)
	g.real = append(g.real, real)
	return id
}

func (g *pg) addArc(u, v, w int) {
	g.down[u] = append(g.down[u], adjE{v, w})
	g.up[v] = append(g.up[v], adjE{u, w})
}

func (g *pg) reindex() {
	for _, l := range g.layers {
		for i, v := range l {
			g.pos[v] = i
		}
	}
}

// initialOrder places nodes layer by layer in DFS discovery order, a cheap
// start that already keeps tree-like structure planar.
func (g *pg) initialOrder() {
	g.pos = make([]int, g.n)
	nl := 0
	for _, r := range g.rank {
		if r+1 > nl {
			nl = r + 1
		}
	}
	g.layers = make([][]int, nl)
	seen := make([]bool, g.n)
	var visit func(v int)
	visit = func(v int) {
		stack := []int{v}
		seen[v] = true
		g.layers[g.rank[v]] = append(g.layers[g.rank[v]], v)
		// iterative preorder DFS over down edges
		type fr struct{ v, i int }
		st := []fr{{v, 0}}
		_ = stack
		for len(st) > 0 {
			f := &st[len(st)-1]
			if f.i == len(g.down[f.v]) {
				st = st[:len(st)-1]
				continue
			}
			w := g.down[f.v][f.i].to
			f.i++
			if !seen[w] {
				seen[w] = true
				g.layers[g.rank[w]] = append(g.layers[g.rank[w]], w)
				st = append(st, fr{w, 0})
			}
		}
	}
	for v := 0; v < g.n; v++ {
		if len(g.up[v]) == 0 && !seen[v] {
			visit(v)
		}
	}
	for v := 0; v < g.n; v++ { // safety: unreachable leftovers
		if !seen[v] {
			visit(v)
		}
	}
	g.reindex()
}

// crossingsBetween counts crossings among edges between layer i and i+1.
func (g *pg) crossingsBetween(i int) int {
	type pr struct{ a, b int }
	var es []pr
	for _, v := range g.layers[i] {
		for _, e := range g.down[v] {
			es = append(es, pr{g.pos[v], g.pos[e.to]})
		}
	}
	if len(es) < 2 {
		return 0
	}
	sort.Slice(es, func(x, y int) bool {
		if es[x].a != es[y].a {
			return es[x].a < es[y].a
		}
		return es[x].b < es[y].b
	})
	m := len(g.layers[i+1])
	bit := make([]int, m+2)
	total := 0
	for k, e := range es {
		// edges before k with b > e.b
		s := 0
		for x := e.b + 1; x > 0; x -= x & -x {
			s += bit[x]
		}
		total += k - s
		for x := e.b + 1; x <= m; x += x & -x {
			bit[x]++
		}
	}
	return total
}

func (g *pg) crossings() int {
	t := 0
	for i := 0; i+1 < len(g.layers); i++ {
		t += g.crossingsBetween(i)
	}
	return t
}

// weightedMedian of neighbour positions (Gansner et al.); -1 = no neighbours.
func (g *pg) medianValue(v int, useUp bool) float64 {
	adj := g.down[v]
	if useUp {
		adj = g.up[v]
	}
	if len(adj) == 0 {
		return -1
	}
	ps := make([]int, len(adj))
	for i, e := range adj {
		ps[i] = g.pos[e.to]
	}
	sort.Ints(ps)
	m := len(ps) / 2
	switch {
	case len(ps)%2 == 1:
		return float64(ps[m])
	case len(ps) == 2:
		return float64(ps[0]+ps[1]) / 2
	}
	left := float64(ps[m-1] - ps[0])
	right := float64(ps[len(ps)-1] - ps[m])
	if left+right == 0 {
		return float64(ps[m-1]+ps[m]) / 2
	}
	return (float64(ps[m-1])*right + float64(ps[m])*left) / (left + right)
}

func (g *pg) sortLayer(i int, useUp bool) {
	l := g.layers[i]
	type kv struct {
		v   int
		key float64
	}
	var movable []kv
	var slots []int
	for k, v := range l {
		if m := g.medianValue(v, useUp); m >= 0 {
			movable = append(movable, kv{v, m})
			slots = append(slots, k)
		}
	}
	sort.SliceStable(movable, func(a, b int) bool { return movable[a].key < movable[b].key })
	for j, s := range slots {
		l[s] = movable[j].v
	}
	for k, v := range l {
		g.pos[v] = k
	}
}

// pairCross counts crossings contributed by v placed left of w on their layer.
func (g *pg) pairCross(v, w int) int {
	c := 0
	for _, a := range g.up[v] {
		for _, b := range g.up[w] {
			if g.pos[a.to] > g.pos[b.to] {
				c++
			}
		}
	}
	for _, a := range g.down[v] {
		for _, b := range g.down[w] {
			if g.pos[a.to] > g.pos[b.to] {
				c++
			}
		}
	}
	return c
}

func (g *pg) transpose() {
	improved := true
	for rounds := 0; improved && rounds < 50; rounds++ {
		improved = false
		for _, l := range g.layers {
			for k := 0; k+1 < len(l); k++ {
				v, w := l[k], l[k+1]
				if g.pairCross(w, v) < g.pairCross(v, w) {
					l[k], l[k+1] = w, v
					g.pos[w], g.pos[v] = k, k+1
					improved = true
				}
			}
		}
	}
}

// minimizeCrossings runs alternating median sweeps with transposition,
// restoring the best ordering found.
func (g *pg) minimizeCrossings(maxIter int) {
	best := g.crossings()
	bestLayers := cloneLayers(g.layers)
	if best == 0 {
		return
	}
	stale := 0
	for it := 0; it < maxIter && best > 0 && stale < 6; it++ {
		if it%2 == 0 {
			for i := 1; i < len(g.layers); i++ {
				g.sortLayer(i, true)
			}
		} else {
			for i := len(g.layers) - 2; i >= 0; i-- {
				g.sortLayer(i, false)
			}
		}
		g.transpose()
		if c := g.crossings(); c < best {
			best = c
			bestLayers = cloneLayers(g.layers)
			stale = 0
		} else {
			stale++
		}
	}
	g.layers = bestLayers
	g.reindex()
}

func cloneLayers(ls [][]int) [][]int {
	out := make([][]int, len(ls))
	for i, l := range ls {
		out[i] = append([]int(nil), l...)
	}
	return out
}
