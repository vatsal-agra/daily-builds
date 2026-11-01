package plan

import (
	"fmt"
	"math"
	"time"

	"wayfinder/grid"
)

// JPS runs Jump Point Search (Harabor & Grastien 2011), adapted to the
// no-corner-cutting movement rule used throughout Wayfinder. It requires a
// uniform-cost map (JPS prunes symmetric paths, which only exist when all
// open cells cost the same). The returned path holds the jump points; use
// Densify to expand it to unit steps.
func JPS(g *grid.Grid, s, t grid.Point) (*Result, error) {
	if err := checkEndpoints(g, s, t); err != nil {
		return nil, err
	}
	if !g.Uniform() {
		return nil, fmt.Errorf("jps requires a uniform-cost map (this map has mixed terrain); use astar")
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
	res := &Result{Algo: "jps"}
	si, ti := g.Idx(s.X, s.Y), g.Idx(t.X, t.Y)
	gs[si], parent[si] = 0, -1
	hp.Update(si, Key{Heuristic(g, s, t), 0})

	// forced reports whether a straight-moving arrival at (x,y) has a forced neighbour.
	forced := func(x, y, dx, dy int) bool {
		if dy == 0 { // horizontal travel
			for _, sd := range [2]int{1, -1} {
				if !g.Open(x-dx, y+sd) && g.Open(x, y+sd) {
					return true
				}
			}
			return false
		}
		for _, sd := range [2]int{1, -1} {
			if !g.Open(x+sd, y-dy) && g.Open(x+sd, y) {
				return true
			}
		}
		return false
	}
	var jump func(x, y, dx, dy int) (int, int, bool)
	jump = func(x, y, dx, dy int) (int, int, bool) {
		for {
			if !g.CanMove(x, y, dx, dy) {
				return 0, 0, false
			}
			x, y = x+dx, y+dy
			if x == t.X && y == t.Y {
				return x, y, true
			}
			if dx != 0 && dy != 0 {
				if _, _, ok := jump(x, y, dx, 0); ok {
					return x, y, true
				}
				if _, _, ok := jump(x, y, 0, dy); ok {
					return x, y, true
				}
			} else if forced(x, y, dx, dy) {
				return x, y, true
			}
		}
	}
	sign := func(v int) int {
		switch {
		case v > 0:
			return 1
		case v < 0:
			return -1
		}
		return 0
	}
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
		var dirs [][2]int
		if parent[u] < 0 {
			dirs = grid.Dirs[:]
		} else {
			pp := g.Pt(int(parent[u]))
			dx, dy := sign(up.X-pp.X), sign(up.Y-pp.Y)
			if dx != 0 && dy != 0 {
				dirs = [][2]int{{dx, 0}, {0, dy}, {dx, dy}}
			} else {
				dirs = [][2]int{{dx, dy}}
				for _, sd := range [2]int{1, -1} {
					if dy == 0 && !g.Open(up.X-dx, up.Y+sd) {
						dirs = append(dirs, [2]int{0, sd}, [2]int{dx, sd})
					}
					if dx == 0 && !g.Open(up.X+sd, up.Y-dy) {
						dirs = append(dirs, [2]int{sd, 0}, [2]int{sd, dy})
					}
				}
			}
		}
		for _, d := range dirs {
			jx, jy, ok := jump(up.X, up.Y, d[0], d[1])
			if !ok {
				continue
			}
			v := g.Idx(jx, jy)
			if closed[v] {
				continue
			}
			steps := math.Max(math.Abs(float64(jx-up.X)), math.Abs(float64(jy-up.Y)))
			l := 1.0
			if d[0] != 0 && d[1] != 0 {
				l = grid.Sqrt2
			}
			ng := gs[u] + steps*l*unit
			if ng < gs[v] {
				gs[v], parent[v] = ng, int32(u)
				res.Generated++
				hp.Update(v, Key{ng + Heuristic(g, grid.Point{X: jx, Y: jy}, t), -ng})
			}
		}
	}
	if res.Found {
		res.Cost = gs[ti]
		for i := ti; ; i = int(parent[i]) {
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

// Densify expands waypoints joined by straight or pure-diagonal runs into unit steps.
func Densify(p []grid.Point) []grid.Point {
	if len(p) == 0 {
		return nil
	}
	out := []grid.Point{p[0]}
	for i := 1; i < len(p); i++ {
		a, b := p[i-1], p[i]
		dx, dy := b.X-a.X, b.Y-a.Y
		sx, sy := sgn(dx), sgn(dy)
		for a != b {
			if a.X != b.X {
				a.X += sx
			}
			if a.Y != b.Y {
				a.Y += sy
			}
			out = append(out, a)
		}
	}
	return out
}

func sgn(v int) int {
	switch {
	case v > 0:
		return 1
	case v < 0:
		return -1
	}
	return 0
}
