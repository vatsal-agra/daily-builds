package plan

import (
	"fmt"
	"math"
	"time"

	"wayfinder/grid"
)

// HPA runs Hierarchical Path-finding A* (Botea, Müller & Schaeffer 2004).
// The map is cut into clusterSize×clusterSize clusters; each border between
// two clusters gets one entrance per maximal open run; entrance cells become
// nodes of an abstract graph whose edges are (a) the 1-step inter-cluster
// crossings and (b) intra-cluster shortest paths found by A* bounded to the
// cluster. A query inserts start and goal into that graph, searches the small
// abstract graph, then refines each abstract edge back into grid cells.
// The result is near-optimal (not optimal); Expanded counts abstract-graph
// expansions plus the bounded A* work done to insert start and goal (the
// one-off graph build is not charged to the query).
func HPA(g *grid.Grid, s, t grid.Point, clusterSize int) (*Result, error) {
	if err := checkEndpoints(g, s, t); err != nil {
		return nil, err
	}
	if clusterSize < 2 {
		return nil, fmt.Errorf("cluster size must be >= 2, got %d", clusterSize)
	}
	h := BuildHPA(g, clusterSize)
	return h.Query(s, t)
}

type hpaEdge struct {
	to   int
	cost float64
	path []grid.Point // refinement (cells, including both ends); nil for a crossing edge (2 cells)
}

// HPAGraph is a reusable abstract graph.
type HPAGraph struct {
	g     *grid.Grid
	hs    float64 // heuristic scale (min open-cell cost)
	cs    int
	cells []grid.Point // node id -> cell
	idOf  map[int]int  // cell index -> node id
	adj   [][]hpaEdge
	Build time.Duration
	Nodes int
}

func (h *HPAGraph) cluster(p grid.Point) (int, int) { return p.X / h.cs, p.Y / h.cs }

func (h *HPAGraph) bounds(cx, cy int) (x0, y0, x1, y1 int) {
	return cx * h.cs, cy * h.cs, min((cx+1)*h.cs, h.g.W) - 1, min((cy+1)*h.cs, h.g.H) - 1
}

func (h *HPAGraph) node(p grid.Point) int {
	k := h.g.Idx(p.X, p.Y)
	if id, ok := h.idOf[k]; ok {
		return id
	}
	id := len(h.cells)
	h.cells = append(h.cells, p)
	h.adj = append(h.adj, nil)
	h.idOf[k] = id
	return id
}

// BuildHPA constructs the abstract graph.
func BuildHPA(g *grid.Grid, cs int) *HPAGraph {
	t0 := time.Now()
	h := &HPAGraph{g: g, cs: cs, hs: g.MinCost(), idOf: map[int]int{}}
	ncx, ncy := (g.W+cs-1)/cs, (g.H+cs-1)/cs
	// entrances
	for cy := 0; cy < ncy; cy++ {
		for cx := 0; cx < ncx; cx++ {
			x0, y0, x1, y1 := h.bounds(cx, cy)
			if cx+1 < ncx { // vertical border with the cluster to the right
				h.border(func(i int) (grid.Point, grid.Point) {
					return grid.Point{X: x1, Y: y0 + i}, grid.Point{X: x1 + 1, Y: y0 + i}
				}, y1-y0+1)
			}
			if cy+1 < ncy { // horizontal border with the cluster below
				h.border(func(i int) (grid.Point, grid.Point) {
					return grid.Point{X: x0 + i, Y: y1}, grid.Point{X: x0 + i, Y: y1 + 1}
				}, x1-x0+1)
			}
		}
	}
	// intra-cluster edges
	members := map[[2]int][]int{}
	for id, c := range h.cells {
		cx, cy := h.cluster(c)
		members[[2]int{cx, cy}] = append(members[[2]int{cx, cy}], id)
	}
	for key, ids := range members {
		x0, y0, x1, y1 := h.bounds(key[0], key[1])
		for i := 0; i < len(ids); i++ {
			for j := i + 1; j < len(ids); j++ {
				p, c, _ := boundedAStar(g, h.hs, h.cells[ids[i]], h.cells[ids[j]], x0, y0, x1, y1)
				if p == nil {
					continue
				}
				h.adj[ids[i]] = append(h.adj[ids[i]], hpaEdge{ids[j], c, p})
				rev := append([]grid.Point(nil), p...)
				reverse(rev)
				h.adj[ids[j]] = append(h.adj[ids[j]], hpaEdge{ids[i], c, rev})
			}
		}
	}
	h.Build = time.Since(t0)
	h.Nodes = len(h.cells)
	return h
}

// border scans one cluster border, creating an entrance per maximal run of
// cell pairs that can be crossed with a straight step. Runs of 6+ get entrances
// at both ends (more routing options), shorter runs one in the middle.
func (h *HPAGraph) border(pair func(i int) (grid.Point, grid.Point), n int) {
	run := func(a, b int) {
		var picks []int
		if b-a+1 >= 6 {
			picks = []int{a, b}
		} else {
			picks = []int{(a + b) / 2}
		}
		for _, i := range picks {
			p, q := pair(i)
			u, v := h.node(p), h.node(q)
			c := h.g.StepCost(p.X, p.Y, q.X-p.X, q.Y-p.Y)
			h.adj[u] = append(h.adj[u], hpaEdge{v, c, []grid.Point{p, q}})
			h.adj[v] = append(h.adj[v], hpaEdge{u, c, []grid.Point{q, p}})
		}
	}
	start := -1
	for i := 0; i <= n; i++ {
		ok := false
		if i < n {
			p, q := pair(i)
			ok = h.g.CanMove(p.X, p.Y, q.X-p.X, q.Y-p.Y)
		}
		if ok && start < 0 {
			start = i
		}
		if !ok && start >= 0 {
			run(start, i-1)
			start = -1
		}
	}
}

// boundedAStar finds the cheapest path between two cells staying inside the
// rectangle; it returns the path (nil if none), its cost and the expansions.
func boundedAStar(g *grid.Grid, hs float64, s, t grid.Point, x0, y0, x1, y1 int) ([]grid.Point, float64, int) {
	if s == t {
		return []grid.Point{s}, 0, 0
	}
	w, hh := x1-x0+1, y1-y0+1
	idx := func(p grid.Point) int { return (p.Y-y0)*w + (p.X - x0) }
	gs := make([]float64, w*hh)
	for i := range gs {
		gs[i] = math.Inf(1)
	}
	par := make([]int32, w*hh)
	closed := make([]bool, w*hh)
	hp := NewHeap(w * hh)
	gs[idx(s)], par[idx(s)] = 0, -1
	hp.Update(idx(s), Key{grid.Octile(s, t) * hs, 0})
	exp := 0
	for hp.Len() > 0 {
		u := hp.Pop()
		if closed[u] {
			continue
		}
		closed[u] = true
		exp++
		up := grid.Point{X: x0 + u%w, Y: y0 + u/w}
		if up == t {
			var path []grid.Point
			for i := u; i >= 0; i = int(par[i]) {
				path = append(path, grid.Point{X: x0 + i%w, Y: y0 + i/w})
				if par[i] < 0 {
					break
				}
			}
			reverse(path)
			return path, gs[u], exp
		}
		for _, d := range grid.Dirs {
			nx, ny := up.X+d[0], up.Y+d[1]
			if nx < x0 || nx > x1 || ny < y0 || ny > y1 || !g.CanMove(up.X, up.Y, d[0], d[1]) {
				continue
			}
			np := grid.Point{X: nx, Y: ny}
			v := idx(np)
			if closed[v] {
				continue
			}
			if ng := gs[u] + g.StepCost(up.X, up.Y, d[0], d[1]); ng < gs[v] {
				gs[v], par[v] = ng, int32(u)
				hp.Update(v, Key{ng + grid.Octile(np, t)*hs, -ng})
			}
		}
	}
	return nil, 0, exp
}

// Query plans s -> t on the abstract graph and refines the result into cells.
func (h *HPAGraph) Query(s, t grid.Point) (*Result, error) {
	if err := checkEndpoints(h.g, s, t); err != nil {
		return nil, err
	}
	t0 := time.Now()
	res := &Result{Algo: "hpa*"}
	// Temporary extra nodes and edges for s and t (removed again afterwards).
	type tmp struct{ from, idx int }
	var added []tmp
	baseN := len(h.cells)
	addNode := func(p grid.Point) int {
		if id, ok := h.idOf[h.g.Idx(p.X, p.Y)]; ok {
			return id
		}
		id := h.node(p)
		return id
	}
	sID, tID := addNode(s), addNode(t)
	connect := func(id int) {
		p := h.cells[id]
		cx, cy := h.cluster(p)
		x0, y0, x1, y1 := h.bounds(cx, cy)
		for other := range h.cells {
			q := h.cells[other]
			if other == id {
				continue
			}
			if qx, qy := h.cluster(q); qx != cx || qy != cy {
				continue
			}
			path, c, e := boundedAStar(h.g, h.hs, p, q, x0, y0, x1, y1)
			res.Expanded += e
			if path == nil {
				continue
			}
			rev := append([]grid.Point(nil), path...)
			reverse(rev)
			h.adj[id] = append(h.adj[id], hpaEdge{other, c, path})
			added = append(added, tmp{id, len(h.adj[id]) - 1})
			h.adj[other] = append(h.adj[other], hpaEdge{id, c, rev})
			added = append(added, tmp{other, len(h.adj[other]) - 1})
		}
	}
	if sID >= baseN {
		connect(sID)
	}
	if tID >= baseN && tID != sID {
		connect(tID)
	}
	// Abstract A*.
	n := len(h.cells)
	gs := make([]float64, n)
	for i := range gs {
		gs[i] = math.Inf(1)
	}
	par := make([]int32, n)
	parEdge := make([]int32, n)
	closed := make([]bool, n)
	hp := NewHeap(n)
	gs[sID], par[sID] = 0, -1
	hp.Update(sID, Key{grid.Octile(s, t) * h.hs, 0})
	for hp.Len() > 0 {
		u := hp.Pop()
		if closed[u] {
			continue
		}
		closed[u] = true
		res.Expanded++
		res.Order = append(res.Order, int32(h.g.Idx(h.cells[u].X, h.cells[u].Y)))
		if u == tID {
			res.Found = true
			break
		}
		for ei, e := range h.adj[u] {
			if closed[e.to] {
				continue
			}
			if ng := gs[u] + e.cost; ng < gs[e.to] {
				gs[e.to], par[e.to], parEdge[e.to] = ng, int32(u), int32(ei)
				res.Generated++
				hp.Update(e.to, Key{ng + grid.Octile(h.cells[e.to], t)*h.hs, -ng})
			}
		}
	}
	if res.Found {
		res.Cost = gs[tID]
		var segs [][]grid.Point
		for v := tID; par[v] >= 0; v = int(par[v]) {
			segs = append(segs, h.adj[par[v]][parEdge[v]].path)
		}
		res.Path = []grid.Point{s}
		for i := len(segs) - 1; i >= 0; i-- {
			res.Path = append(res.Path, segs[i][1:]...)
		}
	}
	// Roll back temporary edges/nodes so the graph can be reused.
	for i := len(added) - 1; i >= 0; i-- {
		a := added[i]
		h.adj[a.from] = h.adj[a.from][:a.idx]
	}
	for len(h.cells) > baseN {
		last := len(h.cells) - 1
		delete(h.idOf, h.g.Idx(h.cells[last].X, h.cells[last].Y))
		h.cells = h.cells[:last]
		h.adj = h.adj[:last]
	}
	res.Dur = time.Since(t0)
	return res, nil
}
