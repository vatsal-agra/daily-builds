package plan

import (
	"fmt"
	"math"
	"time"

	"wayfinder/grid"
)

// Result is the outcome of a planning call, including the full expansion trace
// so the viewer can replay exactly what the algorithm did.
type Result struct {
	Algo      string
	Found     bool
	Path      []grid.Point // waypoints (dense for grid planners, sparse for JPS/Theta*/HPA*)
	Cost      float64
	Expanded  int     // nodes popped and expanded
	Generated int     // nodes pushed / relaxed
	Order     []int32 // cell index of each expansion, in order
	Dur       time.Duration
}

// String summarises a result on one line.
func (r *Result) String() string {
	if !r.Found {
		return fmt.Sprintf("%-9s no path   expanded=%d", r.Algo, r.Expanded)
	}
	return fmt.Sprintf("%-9s cost=%9.3f expanded=%7d generated=%7d waypoints=%4d time=%v",
		r.Algo, r.Cost, r.Expanded, r.Generated, len(r.Path), r.Dur.Round(time.Microsecond))
}

func checkEndpoints(g *grid.Grid, s, t grid.Point) error {
	if !g.In(s.X, s.Y) || !g.In(t.X, t.Y) {
		return fmt.Errorf("start %v or goal %v outside %dx%d map", s, t, g.W, g.H)
	}
	if !g.Open(s.X, s.Y) {
		return fmt.Errorf("start %v is a wall", s)
	}
	if !g.Open(t.X, t.Y) {
		return fmt.Errorf("goal %v is a wall", t)
	}
	return nil
}

// Dijkstra finds the cheapest path with no heuristic.
func Dijkstra(g *grid.Grid, s, t grid.Point) (*Result, error) {
	return search(g, s, t, false, "dijkstra")
}

// AStar finds the cheapest path guided by the scaled octile heuristic.
func AStar(g *grid.Grid, s, t grid.Point) (*Result, error) { return search(g, s, t, true, "astar") }

// Heuristic returns the admissible, consistent estimate used by A*, D* Lite and HPA*.
func Heuristic(g *grid.Grid, a, b grid.Point) float64 { return grid.Octile(a, b) * g.MinCost() }

func search(g *grid.Grid, s, t grid.Point, useH bool, name string) (*Result, error) {
	if err := checkEndpoints(g, s, t); err != nil {
		return nil, err
	}
	t0 := time.Now()
	hs := g.MinCost() // computed once: MinCost scans the whole grid
	n := g.W * g.H
	gs := make([]float64, n)
	for i := range gs {
		gs[i] = math.Inf(1)
	}
	parent := make([]int32, n)
	closed := make([]bool, n)
	h := NewHeap(n)
	res := &Result{Algo: name}
	si, ti := g.Idx(s.X, s.Y), g.Idx(t.X, t.Y)
	hf := func(p grid.Point) float64 {
		if useH {
			return grid.Octile(p, t) * hs
		}
		return 0
	}
	gs[si], parent[si] = 0, -1
	h.Update(si, Key{hf(s), 0})
	for h.Len() > 0 {
		u := h.Pop()
		if closed[u] {
			continue
		}
		closed[u] = true
		res.Expanded++
		res.Order = append(res.Order, int32(u))
		if u == ti {
			res.Found = true
			break
		}
		up := g.Pt(u)
		for _, d := range grid.Dirs {
			if !g.CanMove(up.X, up.Y, d[0], d[1]) {
				continue
			}
			v := g.Idx(up.X+d[0], up.Y+d[1])
			if closed[v] {
				continue
			}
			ng := gs[u] + g.StepCost(up.X, up.Y, d[0], d[1])
			if ng < gs[v] {
				gs[v], parent[v] = ng, int32(u)
				res.Generated++
				// Tie-break toward larger g (deeper nodes) by using -g as secondary key.
				h.Update(v, Key{ng + hf(grid.Point{X: up.X + d[0], Y: up.Y + d[1]}), -ng})
			}
		}
	}
	if res.Found {
		res.Cost = gs[ti]
		for i := ti; i >= 0; i = int(parent[i]) {
			res.Path = append(res.Path, g.Pt(i))
			if parent[i] < 0 {
				break
			}
		}
		reverse(res.Path)
	}
	res.Dur = time.Since(t0)
	return res, nil
}

func reverse(p []grid.Point) {
	for i, j := 0, len(p)-1; i < j; i, j = i+1, j-1 {
		p[i], p[j] = p[j], p[i]
	}
}
