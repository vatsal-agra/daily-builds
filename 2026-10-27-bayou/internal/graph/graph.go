// Package graph holds the graph-theoretic machinery behind exact inference:
// moralisation, elimination orderings, triangulation, junction trees, and
// d-separation (Bayes-ball reachability).
package graph

import (
	"fmt"
	"sort"

	"bayou/internal/bn"
)

// Undirected is a simple undirected graph on 0..N-1.
type Undirected struct {
	N   int
	Adj []map[int]bool
}

// NewUndirected makes an edgeless graph.
func NewUndirected(n int) *Undirected {
	g := &Undirected{N: n, Adj: make([]map[int]bool, n)}
	for i := range g.Adj {
		g.Adj[i] = map[int]bool{}
	}
	return g
}

// AddEdge adds u-v (ignored for u==v).
func (g *Undirected) AddEdge(u, v int) {
	if u == v {
		return
	}
	g.Adj[u][v], g.Adj[v][u] = true, true
}

// Has reports whether u-v is an edge.
func (g *Undirected) Has(u, v int) bool { return g.Adj[u][v] }

// Clone copies the graph.
func (g *Undirected) Clone() *Undirected {
	h := NewUndirected(g.N)
	for u := range g.Adj {
		for v := range g.Adj[u] {
			h.Adj[u][v] = true
		}
	}
	return h
}

// Neighbors returns the sorted neighbours of u.
func (g *Undirected) Neighbors(u int) []int {
	out := make([]int, 0, len(g.Adj[u]))
	for v := range g.Adj[u] {
		out = append(out, v)
	}
	sort.Ints(out)
	return out
}

// Edges returns the number of edges.
func (g *Undirected) Edges() int {
	e := 0
	for u := range g.Adj {
		e += len(g.Adj[u])
	}
	return e / 2
}

// Moralize marries all co-parents and drops edge directions.
func Moralize(n *bn.Network) *Undirected {
	g := NewUndirected(len(n.Vars))
	for v, x := range n.Vars {
		for i, p := range x.Parents {
			g.AddEdge(v, p)
			for _, q := range x.Parents[i+1:] {
				g.AddEdge(p, q)
			}
		}
	}
	return g
}

// Weight is the state-space size of a set of variables, saturating at 1<<60.
func Weight(card []int, vs []int) float64 {
	w := 1.0
	for _, v := range vs {
		w *= float64(card[v])
	}
	return w
}

// fillIn counts the edges that eliminating v would add among its neighbours.
func fillIn(g *Undirected, v int) int {
	nb := g.Neighbors(v)
	f := 0
	for i, a := range nb {
		for _, b := range nb[i+1:] {
			if !g.Has(a, b) {
				f++
			}
		}
	}
	return f
}

// Heuristic selects the greedy elimination criterion.
type Heuristic int

const (
	MinFill   Heuristic = iota // fewest fill-in edges, ties by smallest clique weight
	MinWeight                  // smallest resulting clique weight, ties by fill-in
)

// EliminationOrder greedily orders the vertices in `among` (all vertices if nil).
// Vertices not in `among` are ignored (treated as already removed).
func EliminationOrder(g *Undirected, card []int, among []int, h Heuristic) []int {
	w := g.Clone()
	alive := map[int]bool{}
	if among == nil {
		for v := 0; v < g.N; v++ {
			alive[v] = true
		}
	} else {
		for _, v := range among {
			alive[v] = true
		}
	}
	// Remove vertices outside `among` from the working graph.
	for v := 0; v < g.N; v++ {
		if !alive[v] {
			for u := range w.Adj[v] {
				delete(w.Adj[u], v)
			}
			w.Adj[v] = map[int]bool{}
		}
	}
	var order []int
	for len(alive) > 0 {
		best, bf, bw := -1, 0, 0.0
		for v := range alive {
			f := fillIn(w, v)
			cl := append(w.Neighbors(v), v)
			wt := Weight(card, cl)
			better := false
			switch {
			case best == -1:
				better = true
			case h == MinFill:
				better = f < bf || (f == bf && (wt < bw || (wt == bw && v < best)))
			default:
				better = wt < bw || (wt == bw && (f < bf || (f == bf && v < best)))
			}
			if better {
				best, bf, bw = v, f, wt
			}
		}
		nb := w.Neighbors(best)
		for i, a := range nb {
			for _, b := range nb[i+1:] {
				w.AddEdge(a, b)
			}
		}
		for _, u := range nb {
			delete(w.Adj[u], best)
		}
		w.Adj[best] = map[int]bool{}
		delete(alive, best)
		order = append(order, best)
	}
	return order
}

// Triangulate eliminates in the given order and returns the elimination cliques
// (each sorted) in order. The maximal ones are the cliques of the chordal fill-in graph.
func Triangulate(g *Undirected, order []int) (cliques [][]int, fill *Undirected) {
	w := g.Clone()
	fill = g.Clone()
	pos := map[int]int{}
	for i, v := range order {
		pos[v] = i
	}
	for _, v := range order {
		var nb []int
		for _, u := range w.Neighbors(v) {
			if pos[u] > pos[v] {
				nb = append(nb, u)
			}
		}
		for i, a := range nb {
			for _, b := range nb[i+1:] {
				w.AddEdge(a, b)
				fill.AddEdge(a, b)
			}
		}
		cl := append([]int{v}, nb...)
		sort.Ints(cl)
		cliques = append(cliques, cl)
	}
	return cliques, fill
}

// MaximalCliques keeps only cliques that are not subsets of another one.
func MaximalCliques(cs [][]int) [][]int {
	var out [][]int
	for i, c := range cs {
		sub := false
		for j, d := range cs {
			if i == j {
				continue
			}
			if len(d) > len(c) || (len(d) == len(c) && j < i) {
				if isSubset(c, d) {
					sub = true
					break
				}
			}
		}
		if !sub {
			out = append(out, c)
		}
	}
	sort.Slice(out, func(i, j int) bool { return lessIntSlice(out[i], out[j]) })
	return out
}

func lessIntSlice(a, b []int) bool {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return len(a) < len(b)
}

func isSubset(a, b []int) bool { // both sorted
	j := 0
	for _, x := range a {
		for j < len(b) && b[j] < x {
			j++
		}
		if j == len(b) || b[j] != x {
			return false
		}
		j++
	}
	return true
}

// Intersect of two sorted slices.
func Intersect(a, b []int) []int {
	var out []int
	i, j := 0, 0
	for i < len(a) && j < len(b) {
		switch {
		case a[i] < b[j]:
			i++
		case a[i] > b[j]:
			j++
		default:
			out = append(out, a[i])
			i++
			j++
		}
	}
	return out
}

// JunctionTree is a tree of maximal cliques with separators on the edges.
type JunctionTree struct {
	Cliques [][]int // sorted variable ids
	Edges   []JTEdge
	Adj     [][]int // clique index -> edge indices
}

// JTEdge joins two cliques over their separator.
type JTEdge struct {
	A, B int
	Sep  []int
}

// BuildJunctionTree triangulates the moral graph of net and links the maximal
// cliques with a maximum-weight spanning tree on separator size, which yields
// the running-intersection property. Disconnected components are joined by
// empty separators, so the result is always a single tree.
func BuildJunctionTree(n *bn.Network, h Heuristic) (*JunctionTree, error) {
	card := make([]int, len(n.Vars))
	for i := range card {
		card[i] = n.Card(i)
	}
	g := Moralize(n)
	order := EliminationOrder(g, card, nil, h)
	elim, _ := Triangulate(g, order)
	cl := MaximalCliques(elim)
	jt := &JunctionTree{Cliques: cl, Adj: make([][]int, len(cl))}
	type cand struct{ a, b, w int }
	var cands []cand
	for i := range cl {
		for j := i + 1; j < len(cl); j++ {
			cands = append(cands, cand{i, j, len(Intersect(cl[i], cl[j]))})
		}
	}
	sort.SliceStable(cands, func(x, y int) bool { return cands[x].w > cands[y].w })
	uf := make([]int, len(cl))
	for i := range uf {
		uf[i] = i
	}
	var find func(int) int
	find = func(x int) int {
		for uf[x] != x {
			uf[x] = uf[uf[x]]
			x = uf[x]
		}
		return x
	}
	for _, c := range cands {
		ra, rb := find(c.a), find(c.b)
		if ra == rb {
			continue
		}
		uf[ra] = rb
		e := JTEdge{A: c.a, B: c.b, Sep: Intersect(cl[c.a], cl[c.b])}
		jt.Adj[c.a] = append(jt.Adj[c.a], len(jt.Edges))
		jt.Adj[c.b] = append(jt.Adj[c.b], len(jt.Edges))
		jt.Edges = append(jt.Edges, e)
	}
	if err := jt.CheckRunningIntersection(len(n.Vars)); err != nil {
		return nil, err
	}
	return jt, nil
}

// CheckRunningIntersection verifies that for each variable the cliques containing
// it form a connected subtree (the defining property of a junction tree).
func (jt *JunctionTree) CheckRunningIntersection(nvars int) error {
	for v := 0; v < nvars; v++ {
		var with []int
		for i, c := range jt.Cliques {
			if contains(c, v) {
				with = append(with, i)
			}
		}
		if len(with) == 0 {
			return fmt.Errorf("variable %d is in no clique", v)
		}
		seen := map[int]bool{with[0]: true}
		stack := []int{with[0]}
		for len(stack) > 0 {
			c := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			for _, ei := range jt.Adj[c] {
				e := jt.Edges[ei]
				o := e.A
				if o == c {
					o = e.B
				}
				if !seen[o] && contains(jt.Cliques[o], v) {
					seen[o] = true
					stack = append(stack, o)
				}
			}
		}
		if len(seen) != len(with) {
			return fmt.Errorf("running intersection violated for variable %d", v)
		}
	}
	return nil
}

func contains(sorted []int, v int) bool {
	i := sort.SearchInts(sorted, v)
	return i < len(sorted) && sorted[i] == v
}

// TreeWidth is max clique size minus one.
func (jt *JunctionTree) TreeWidth() int {
	w := 0
	for _, c := range jt.Cliques {
		if len(c)-1 > w {
			w = len(c) - 1
		}
	}
	return w
}

// DSeparated reports whether every variable in xs is d-separated from every
// variable in ys given zs, using the reachable-set ("Bayes-ball") algorithm of
// Koller & Friedman, Alg. 3.1.
func DSeparated(n *bn.Network, xs, ys, zs []int) bool {
	reach := Reachable(n, xs, zs)
	for _, y := range ys {
		if reach[y] {
			return false
		}
	}
	return true
}

// Reachable returns the set of variables d-connected to any of xs given zs
// (excluding observed variables themselves; xs are always included).
func Reachable(n *bn.Network, xs, zs []int) map[int]bool {
	obs := map[int]bool{}
	for _, z := range zs {
		obs[z] = true
	}
	// A is the set of observed vars and their ancestors (v-structure activation).
	anc := n.Ancestors(zs)
	ch := n.Children()
	type state struct {
		v  int
		up bool // true: trail arrived from a child (moving up); false: from a parent
	}
	visited := map[state]bool{}
	reach := map[int]bool{}
	var queue []state
	for _, x := range xs {
		queue = append(queue, state{x, true})
		reach[x] = true
	}
	for len(queue) > 0 {
		s := queue[0]
		queue = queue[1:]
		if visited[s] {
			continue
		}
		visited[s] = true
		if !obs[s.v] {
			reach[s.v] = true
		}
		if s.up {
			if !obs[s.v] {
				for _, p := range n.Vars[s.v].Parents {
					queue = append(queue, state{p, true})
				}
				for _, c := range ch[s.v] {
					queue = append(queue, state{c, false})
				}
			}
		} else {
			if !obs[s.v] {
				for _, c := range ch[s.v] {
					queue = append(queue, state{c, false})
				}
			}
			if anc[s.v] { // v-structure at s.v is active
				for _, p := range n.Vars[s.v].Parents {
					queue = append(queue, state{p, true})
				}
			}
		}
	}
	return reach
}

// MarkovBlanket returns parents, children and co-parents of v, sorted.
func MarkovBlanket(n *bn.Network, v int) []int {
	set := map[int]bool{}
	for _, p := range n.Vars[v].Parents {
		set[p] = true
	}
	for _, c := range n.Children()[v] {
		set[c] = true
		for _, p := range n.Vars[c].Parents {
			set[p] = true
		}
	}
	delete(set, v)
	out := make([]int, 0, len(set))
	for u := range set {
		out = append(out, u)
	}
	sort.Ints(out)
	return out
}
