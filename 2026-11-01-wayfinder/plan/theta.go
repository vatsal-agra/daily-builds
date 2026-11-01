package plan

import (
	"fmt"
	"math"
	"time"

	"wayfinder/grid"
)

// ThetaStar is basic Theta* (Nash et al. 2007): A* in which a node's parent may
// be a non-adjacent ancestor with line of sight, giving any-angle paths. Path
// cost is the Euclidean length times the (uniform) cell cost. Like JPS it needs
// a uniform-cost map, because the cost of an arbitrary straight segment across
// mixed terrain is not defined by the cell-pair step model.
func ThetaStar(g *grid.Grid, s, t grid.Point) (*Result, error) {
	if err := checkEndpoints(g, s, t); err != nil {
		return nil, err
	}
	if !g.Uniform() {
		return nil, fmt.Errorf("theta* requires a uniform-cost map (this map has mixed terrain); use astar")
	}
	t0 := time.Now()
	unit := g.MinCost()
	n := g.W * g.H
	gs := make([]float64, n)
	for i := range gs {
		gs[i] = math.Inf(1)
	}
	parent := make([]int32, n)
	closed := make([]bool, n)
	hp := NewHeap(n)
	res := &Result{Algo: "theta*"}
	si, ti := g.Idx(s.X, s.Y), g.Idx(t.X, t.Y)
	h := func(p grid.Point) float64 { return grid.Euclid(p, t) * unit }
	gs[si], parent[si] = 0, int32(si) // start is its own parent
	hp.Update(si, Key{h(s), 0})
	for hp.Len() > 0 {
		u := hp.Pop()
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
			np := grid.Point{X: up.X + d[0], Y: up.Y + d[1]}
			v := g.Idx(np.X, np.Y)
			if closed[v] {
				continue
			}
			pp := g.Pt(int(parent[u]))
			var cand float64
			var cp int32
			if g.LineOfSight(pp, np) {
				cand, cp = gs[parent[u]]+grid.Euclid(pp, np)*unit, parent[u]
			} else {
				cand, cp = gs[u]+g.StepCost(up.X, up.Y, d[0], d[1]), int32(u)
			}
			if cand < gs[v]-1e-12 {
				gs[v], parent[v] = cand, cp
				res.Generated++
				hp.Update(v, Key{cand + h(np), -cand})
			}
		}
	}
	if res.Found {
		res.Cost = gs[ti]
		for i := ti; ; i = int(parent[i]) {
			res.Path = append(res.Path, g.Pt(i))
			if int(parent[i]) == i {
				break
			}
		}
		reverse(res.Path)
	}
	res.Dur = time.Since(t0)
	return res, nil
}

// ValidAnyAngle checks every segment of a waypoint path has line of sight and
// returns the Euclidean length × cell cost (uniform maps).
func ValidAnyAngle(g *grid.Grid, p []grid.Point) (float64, error) {
	if len(p) == 0 {
		return 0, fmt.Errorf("empty path")
	}
	total := 0.0
	for i := 1; i < len(p); i++ {
		if !g.LineOfSight(p[i-1], p[i]) {
			return 0, fmt.Errorf("segment %d: %v -> %v has no line of sight", i, p[i-1], p[i])
		}
		total += grid.Euclid(p[i-1], p[i]) * g.MinCost()
	}
	return total, nil
}
