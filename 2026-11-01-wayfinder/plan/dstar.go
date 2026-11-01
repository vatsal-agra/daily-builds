package plan

import (
	"math"

	"wayfinder/grid"
)

// DStarLite is an incremental, backward A* (Koenig & Likhachev 2002). It keeps
// g/rhs values for every cell so that when edge costs change only the affected
// part of the search tree is repaired instead of searching from scratch.
type DStarLite struct {
	G        *grid.Grid // the planner's current belief about the world (mutated via CellChanged)
	goal     grid.Point
	start    grid.Point // current agent position
	last     grid.Point // position at the time of the previous key-modifier update
	km       float64
	g, rhs   []float64
	u        *Heap
	hscale   float64
	Expanded int     // total vertex expansions so far
	Order    []int32 // expansion trace since last ResetTrace
}

var inf = math.Inf(1)

// NewDStarLite plans from start to goal on belief grid g and computes the first plan.
func NewDStarLite(g *grid.Grid, start, goal grid.Point) (*DStarLite, error) {
	if err := checkEndpoints(g, start, goal); err != nil {
		return nil, err
	}
	n := g.W * g.H
	d := &DStarLite{G: g, goal: goal, start: start, last: start, u: NewHeap(n), hscale: g.MinCost(),
		g: make([]float64, n), rhs: make([]float64, n)}
	for i := range d.g {
		d.g[i], d.rhs[i] = inf, inf
	}
	gi := g.Idx(goal.X, goal.Y)
	d.rhs[gi] = 0
	d.u.Update(gi, d.key(gi))
	d.compute()
	return d, nil
}

func (d *DStarLite) h(a, b grid.Point) float64 { return grid.Octile(a, b) * d.hscale }

func (d *DStarLite) key(i int) Key {
	m := math.Min(d.g[i], d.rhs[i])
	return Key{m + d.h(d.start, d.G.Pt(i)) + d.km, m}
}

func (d *DStarLite) cost(a grid.Point, dir [2]int) float64 {
	if !d.G.CanMove(a.X, a.Y, dir[0], dir[1]) {
		return inf
	}
	return d.G.StepCost(a.X, a.Y, dir[0], dir[1])
}

func (d *DStarLite) updateVertex(i int) {
	if i != d.G.Idx(d.goal.X, d.goal.Y) {
		p := d.G.Pt(i)
		best := inf
		for _, dir := range grid.Dirs {
			c := d.cost(p, dir)
			if c == inf {
				continue
			}
			if v := c + d.g[d.G.Idx(p.X+dir[0], p.Y+dir[1])]; v < best {
				best = v
			}
		}
		d.rhs[i] = best
	}
	if !eq(d.g[i], d.rhs[i]) {
		d.u.Update(i, d.key(i))
	} else {
		d.u.Remove(i)
	}
}

func (d *DStarLite) preds(i int, f func(j int)) {
	p := d.G.Pt(i)
	for _, dir := range grid.Dirs {
		if d.G.CanMove(p.X, p.Y, dir[0], dir[1]) { // edge costs are symmetric
			f(d.G.Idx(p.X+dir[0], p.Y+dir[1]))
		}
	}
}

func (d *DStarLite) compute() {
	si := d.G.Idx(d.start.X, d.start.Y)
	for d.u.Len() > 0 {
		top, kold := d.u.Peek()
		if !kold.lessTol(d.key(si)) && eq(d.rhs[si], d.g[si]) {
			return
		}
		knew := d.key(top)
		d.Expanded++
		d.Order = append(d.Order, int32(top))
		switch {
		case kold.lessTol(knew):
			d.u.Update(top, knew)
		case d.g[top] > d.rhs[top]+1e-9:
			d.g[top] = d.rhs[top]
			d.u.Remove(top)
			d.preds(top, d.updateVertex)
		default:
			d.g[top] = inf
			d.updateVertex(top)
			d.preds(top, d.updateVertex)
		}
	}
}

// ResetTrace clears the expansion trace (the Expanded counter keeps running).
func (d *DStarLite) ResetTrace() { d.Order = d.Order[:0] }

// CellChanged tells the planner that the belief grid's cell (x,y) was modified
// (the caller has already edited d.G). Call Replan after reporting all changes.
func (d *DStarLite) CellChanged(x, y int) {
	if d.last != d.start {
		d.km += d.h(d.last, d.start)
		d.last = d.start
	}
	for dy := -1; dy <= 1; dy++ {
		for dx := -1; dx <= 1; dx++ {
			if d.G.In(x+dx, y+dy) {
				d.updateVertex(d.G.Idx(x+dx, y+dy))
			}
		}
	}
}

// Replan repairs the plan after CellChanged calls.
func (d *DStarLite) Replan() { d.compute() }

// MoveTo records that the agent is now at p.
func (d *DStarLite) MoveTo(p grid.Point) { d.start = p }

// Cost is the current best cost-to-go from the agent's position (Inf if blocked).
func (d *DStarLite) Cost() float64 { return d.g[d.G.Idx(d.start.X, d.start.Y)] }

// Next returns the best next cell for the agent, or false if no path is known.
func (d *DStarLite) Next() (grid.Point, bool) {
	if d.start == d.goal {
		return d.start, false
	}
	best, bp := inf, d.start
	for _, dir := range grid.Dirs {
		c := d.cost(d.start, dir)
		if c == inf {
			continue
		}
		n := grid.Point{X: d.start.X + dir[0], Y: d.start.Y + dir[1]}
		if v := c + d.g[d.G.Idx(n.X, n.Y)]; v < best {
			best, bp = v, n
		}
	}
	return bp, best < inf
}

// PathFromHere follows greedy descent on g to produce the currently planned path.
func (d *DStarLite) PathFromHere() []grid.Point {
	saved := d.start
	defer func() { d.start = saved }()
	path := []grid.Point{d.start}
	for steps := 0; d.start != d.goal && steps <= d.G.W*d.G.H; steps++ {
		n, ok := d.Next()
		if !ok {
			return nil
		}
		d.start = n
		path = append(path, n)
	}
	return path
}

// eq compares costs tolerant to float rounding (and treats Inf == Inf).
func eq(a, b float64) bool { return a == b || math.Abs(a-b) < 1e-9 }
