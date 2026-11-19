package layout

import (
	"errors"
	"sort"
)

// rankEdge is a DAG arc with a minimum length and weight.
type rankEdge struct{ u, v, w, minlen int }

// longestPathRanks gives the feasible layering with every node as high as
// possible (sources at 0). The graph must be acyclic.
func longestPathRanks(n int, edges []rankEdge) ([]int, error) {
	indeg := make([]int, n)
	out := make([][]int, n)
	for i, e := range edges {
		indeg[e.v]++
		out[e.u] = append(out[e.u], i)
	}
	rank := make([]int, n)
	q := []int{}
	for v := 0; v < n; v++ {
		if indeg[v] == 0 {
			q = append(q, v)
		}
	}
	seen := 0
	for len(q) > 0 {
		v := q[0]
		q = q[1:]
		seen++
		for _, ei := range out[v] {
			e := edges[ei]
			if r := rank[v] + e.minlen; r > rank[e.v] {
				rank[e.v] = r
			}
			indeg[e.v]--
			if indeg[e.v] == 0 {
				q = append(q, e.v)
			}
		}
	}
	if seen != n {
		return nil, errors.New("rank: graph contains a cycle")
	}
	return rank, nil
}

// networkSimplexRanks minimises Σ w·(rank[v]−rank[u]) subject to
// rank[v]−rank[u] ≥ minlen, for a connected acyclic graph (Gansner et al.,
// "A Technique for Drawing Directed Graphs"). Ranks are normalised to start
// at 0, then balanced to reduce layer width without changing the cost.
func networkSimplexRanks(n int, edges []rankEdge) ([]int, error) {
	rank, err := longestPathRanks(n, edges)
	if err != nil {
		return nil, err
	}
	if n <= 1 || len(edges) == 0 {
		return rank, nil
	}
	ns := &simplex{n: n, edges: edges, rank: rank}
	if err := ns.run(); err != nil {
		return nil, err
	}
	ns.normalize()
	ns.balance()
	return ns.rank, nil
}

type simplex struct {
	n      int
	edges  []rankEdge
	rank   []int
	inTree []bool
	adj    [][]int // incident edge indices (all edges)
	// rooted tree
	parent  []int // parent node, -1 for root
	pedge   []int // tree edge to parent
	low     []int
	lim     []int
	order   []int // postorder
	cut     []int // cut value per tree edge (indexed by edge)
	treeAdj [][]int
}

func (s *simplex) slack(ei int) int {
	e := s.edges[ei]
	return s.rank[e.v] - s.rank[e.u] - e.minlen
}

func (s *simplex) run() error {
	s.adj = make([][]int, s.n)
	for i, e := range s.edges {
		s.adj[e.u] = append(s.adj[e.u], i)
		s.adj[e.v] = append(s.adj[e.v], i)
	}
	if err := s.feasibleTree(); err != nil {
		return err
	}
	s.root()
	s.cutValues()
	limit := 200000 + 50*len(s.edges)
	start := 0
	for it := 0; it < limit; it++ {
		le := -1
		m := len(s.edges)
		for k := 0; k < m; k++ {
			ei := (start + k) % m
			if s.inTree[ei] && s.cut[ei] < 0 {
				le = ei
				start = ei + 1
				break
			}
		}
		if le < 0 {
			return nil
		}
		ee := s.enterEdge(le)
		if ee < 0 {
			return errors.New("rank: network simplex found no entering edge (graph disconnected?)")
		}
		s.exchange(le, ee)
	}
	return errors.New("rank: network simplex iteration limit reached")
}

// feasibleTree builds a spanning tree of tight edges, shifting ranks of the
// partial tree whenever it cannot grow.
func (s *simplex) feasibleTree() error {
	s.inTree = make([]bool, len(s.edges))
	inT := make([]bool, s.n)
	count := 1
	inT[0] = true
	// grow greedily along tight edges
	grow := func() {
		stack := []int{}
		for v := 0; v < s.n; v++ {
			if inT[v] {
				stack = append(stack, v)
			}
		}
		for len(stack) > 0 {
			v := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			for _, ei := range s.adj[v] {
				e := s.edges[ei]
				w := e.u
				if w == v {
					w = e.v
				}
				if !inT[w] && s.slack(ei) == 0 {
					inT[w] = true
					s.inTree[ei] = true
					count++
					stack = append(stack, w)
				}
			}
		}
	}
	grow()
	for count < s.n {
		best, bs := -1, 0
		for ei, e := range s.edges {
			if inT[e.u] != inT[e.v] {
				if sl := s.slack(ei); best < 0 || sl < bs {
					best, bs = ei, sl
				}
			}
		}
		if best < 0 {
			return errors.New("rank: graph is not connected")
		}
		d := bs
		if !inT[s.edges[best].u] { // head side is in tree: moving tree up means rank -= ... tail outside
			d = -d
		}
		// tree node is e.v (head) when tail is outside: need rank[v]-rank[u] smaller => lower tree ranks
		for v := 0; v < s.n; v++ {
			if inT[v] {
				s.rank[v] += d
			}
		}
		grow()
	}
	return nil
}

// root builds parent/low/lim over the current tree edges (root = node 0).
func (s *simplex) root() {
	if s.parent == nil {
		s.parent = make([]int, s.n)
		s.pedge = make([]int, s.n)
		s.low = make([]int, s.n)
		s.lim = make([]int, s.n)
		s.treeAdj = make([][]int, s.n)
		s.cut = make([]int, len(s.edges))
	}
	for v := range s.treeAdj {
		s.treeAdj[v] = s.treeAdj[v][:0]
	}
	for ei, e := range s.edges {
		if s.inTree[ei] {
			s.treeAdj[e.u] = append(s.treeAdj[e.u], ei)
			s.treeAdj[e.v] = append(s.treeAdj[e.v], ei)
		}
	}
	s.order = s.order[:0]
	for i := range s.parent {
		s.parent[i] = -2
	}
	type fr struct{ v, i int }
	counter := 1
	s.parent[0], s.pedge[0] = -1, -1
	s.low[0] = counter
	st := []fr{{0, 0}}
	for len(st) > 0 {
		f := &st[len(st)-1]
		if f.i < len(s.treeAdj[f.v]) {
			ei := s.treeAdj[f.v][f.i]
			f.i++
			e := s.edges[ei]
			w := e.u
			if w == f.v {
				w = e.v
			}
			if s.parent[w] == -2 {
				s.parent[w], s.pedge[w] = f.v, ei
				s.low[w] = counter
				st = append(st, fr{w, 0})
			}
			continue
		}
		s.lim[f.v] = counter
		counter++
		s.order = append(s.order, f.v)
		st = st[:len(st)-1]
	}
}

func (s *simplex) inSub(v, x int) bool { return s.low[v] <= s.lim[x] && s.lim[x] <= s.lim[v] }

// cutValues recomputes the cut value of every tree edge in O(E·depth).
func (s *simplex) cutValues() {
	outW := make([]int, s.n)
	inW := make([]int, s.n)
	lcaW := make([]int, s.n)
	for _, e := range s.edges {
		outW[e.u] += e.w
		inW[e.v] += e.w
		a := e.u
		for !s.inSub(a, e.v) {
			a = s.parent[a]
		}
		lcaW[a] += e.w
	}
	// subtree sums in postorder
	sumOut := make([]int, s.n)
	sumIn := make([]int, s.n)
	for _, v := range s.order {
		sumOut[v] += outW[v] - lcaW[v]
		sumIn[v] += inW[v] - lcaW[v]
		if p := s.parent[v]; p >= 0 {
			sumOut[p] += sumOut[v]
			sumIn[p] += sumIn[v]
		}
	}
	for v := 0; v < s.n; v++ {
		ei := s.pedge[v]
		if ei < 0 {
			continue
		}
		e := s.edges[ei]
		if e.v == v { // tree edge p -> v: subtree is the head component
			s.cut[ei] = sumIn[v] - sumOut[v]
		} else { // v -> p: subtree is the tail component
			s.cut[ei] = sumOut[v] - sumIn[v]
		}
	}
}

// enterEdge picks the non-tree edge of minimum slack that reconnects the two
// components created by removing tree edge le, oriented from the head
// component to the tail component.
func (s *simplex) enterEdge(le int) int {
	e := s.edges[le]
	v := e.v
	if s.parent[e.u] == e.v && s.pedge[e.u] == le {
		v = e.u
	}
	// subtree of v is S. Head component is S iff v == e.v.
	headIsSub := v == e.v
	best, bs := -1, 0
	for ei, f := range s.edges {
		if s.inTree[ei] {
			continue
		}
		uIn, vIn := s.inSub(v, f.u), s.inSub(v, f.v)
		if uIn == vIn {
			continue
		}
		// need edge from head comp to tail comp
		fromHead := uIn == headIsSub
		if !fromHead {
			continue
		}
		if sl := s.slack(ei); best < 0 || sl < bs {
			best, bs = ei, sl
		}
	}
	return best
}

func (s *simplex) exchange(le, ee int) {
	e := s.edges[le]
	v := e.v
	if s.parent[e.u] == e.v && s.pedge[e.u] == le {
		v = e.u
	}
	headIsSub := v == e.v
	delta := s.slack(ee)
	if delta != 0 {
		for x := 0; x < s.n; x++ {
			if s.inSub(v, x) == headIsSub { // head component
				s.rank[x] += delta
			}
		}
	}
	s.inTree[le] = false
	s.inTree[ee] = true
	s.root()
	s.cutValues()
}

func (s *simplex) normalize() {
	m := s.rank[0]
	for _, r := range s.rank {
		if r < m {
			m = r
		}
	}
	for i := range s.rank {
		s.rank[i] -= m
	}
}

// balance moves nodes whose in-weight equals out-weight to the feasible rank
// holding the fewest nodes (cost-neutral), narrowing wide layers.
func (s *simplex) balance() {
	inW := make([]int, s.n)
	outW := make([]int, s.n)
	for _, e := range s.edges {
		outW[e.u] += e.w
		inW[e.v] += e.w
	}
	maxR := 0
	for _, r := range s.rank {
		if r > maxR {
			maxR = r
		}
	}
	cnt := make([]int, maxR+1)
	for _, r := range s.rank {
		cnt[r]++
	}
	nodes := make([]int, 0, s.n)
	for v := 0; v < s.n; v++ {
		if inW[v] == outW[v] {
			nodes = append(nodes, v)
		}
	}
	sort.Ints(nodes)
	for _, v := range nodes {
		lo, hi := 0, maxR
		for _, ei := range s.adj[v] {
			e := s.edges[ei]
			if e.u == v {
				if r := s.rank[e.v] - e.minlen; r < hi {
					hi = r
				}
			} else if r := s.rank[e.u] + e.minlen; r > lo {
				lo = r
			}
		}
		best := s.rank[v]
		for r := lo; r <= hi; r++ {
			if cnt[r] < cnt[best] {
				best = r
			}
		}
		if best != s.rank[v] && cnt[best] < cnt[s.rank[v]] {
			cnt[s.rank[v]]--
			cnt[best]++
			s.rank[v] = best
		}
	}
}

// RankCost is Σ w·span for a rank assignment (exported for tests and tools).
func rankCost(edges []rankEdge, rank []int) int {
	c := 0
	for _, e := range edges {
		c += e.w * (rank[e.v] - rank[e.u])
	}
	return c
}
