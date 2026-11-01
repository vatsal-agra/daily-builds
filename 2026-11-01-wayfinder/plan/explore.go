package plan

import (
	"fmt"
	"math"

	"wayfinder/grid"
)

// Event is one replanning episode during an exploration run.
type Event struct {
	Step       int // agent step index at which the replan happened (0 = initial plan)
	Pos        grid.Point
	Changed    int     // newly discovered cells that changed the belief map
	DStarExp   int     // D* Lite expansions for this repair
	AStarExp   int     // expansions a from-scratch A* needed on the same belief map
	PlanCost   float64 // cost-to-go reported by D* Lite after repair
	Order      []int32 // cells D* Lite expanded during this repair
	Plan       []grid.Point
	Discovered []grid.Point // cells whose belief changed
}

// Exploration is the full record of a D* Lite run in an initially unknown world.
type Exploration struct {
	Reached    bool
	Stuck      bool
	Trail      []grid.Point
	Travelled  float64
	Events     []Event
	DStarTotal int // total D* Lite expansions
	AStarTotal int // total expansions of from-scratch A* at every replan
	Radius     int
	Known      *grid.Grid // final belief map
}

// Explore drives an agent from true.Start to true.Goal through a world it
// initially believes to be empty (cost-1 everywhere). Each step it senses all
// cells within radius (Euclidean), updates its belief, repairs its plan with D*
// Lite and walks one step. At every replan the result is cross-checked against
// a from-scratch A* on the same belief map; any disagreement is returned as an
// error, so a successful run is itself a correctness proof for that run.
func Explore(truth *grid.Grid, radius int) (*Exploration, error) {
	if radius < 1 {
		return nil, fmt.Errorf("sensor radius must be >= 1, got %d", radius)
	}
	if err := checkEndpoints(truth, truth.Start, truth.Goal); err != nil {
		return nil, err
	}
	radius = min(radius, truth.W+truth.H) // anything larger already sees the whole map
	known := grid.New(truth.W, truth.H)
	known.Start, known.Goal = truth.Start, truth.Goal
	seen := make([]bool, len(truth.Cost))

	// sense reveals cells within radius; returns those whose belief changed.
	sense := func(p grid.Point) []grid.Point {
		var ch []grid.Point
		for y := p.Y - radius; y <= p.Y+radius; y++ {
			for x := p.X - radius; x <= p.X+radius; x++ {
				if !truth.In(x, y) {
					continue
				}
				// The 8 adjacent cells are always felt, whatever the radius, so the
				// agent never steps onto a cell it has not perceived.
				adjacent := abs(x-p.X) <= 1 && abs(y-p.Y) <= 1
				if !adjacent && (x-p.X)*(x-p.X)+(y-p.Y)*(y-p.Y) > radius*radius {
					continue
				}
				i := truth.Idx(x, y)
				seen[i] = true
				if known.Cost[i] != truth.Cost[i] {
					known.Cost[i] = truth.Cost[i]
					ch = append(ch, grid.Point{X: x, Y: y})
				}
			}
		}
		return ch
	}
	ex := &Exploration{Radius: radius, Known: known}
	pos := truth.Start
	first := sense(pos)
	// The start and goal cells are always open, so planning cannot be refused.
	t0 := truth.Start
	d, err := NewDStarLite(known, t0, truth.Goal)
	if err != nil {
		return nil, err
	}
	record := func(step int, ch []grid.Point) error {
		ref, err := AStar(known, pos, truth.Goal)
		if err != nil {
			return err
		}
		ev := Event{Step: step, Pos: pos, Changed: len(ch), DStarExp: len(d.Order), AStarExp: ref.Expanded,
			PlanCost: d.Cost(), Order: append([]int32(nil), d.Order...), Discovered: ch}
		if ev.PlanCost != inf {
			ev.Plan = d.PathFromHere()
		}
		d.ResetTrace()
		ex.Events = append(ex.Events, ev)
		ex.DStarTotal += ev.DStarExp
		ex.AStarTotal += ev.AStarExp
		switch {
		case ref.Found != (ev.PlanCost != inf):
			return fmt.Errorf("step %d: D* Lite found=%v but A* found=%v", step, ev.PlanCost != inf, ref.Found)
		case ref.Found && math.Abs(ref.Cost-ev.PlanCost) > 1e-6:
			return fmt.Errorf("step %d: D* Lite cost %.6f != A* cost %.6f", step, ev.PlanCost, ref.Cost)
		}
		return nil
	}
	// Initial plan was computed against an all-open belief; apply what the first scan revealed.
	// (Order of the initial compute is attributed to the first event.)
	initialOrder := append([]int32(nil), d.Order...)
	d.ResetTrace()
	for _, c := range first {
		d.CellChanged(c.X, c.Y)
	}
	d.Replan()
	d.Order = append(initialOrder, d.Order...)
	ex.Trail = []grid.Point{pos}
	if err := record(0, first); err != nil {
		return ex, err
	}
	limit := 4 * truth.W * truth.H
	for step := 1; pos != truth.Goal; step++ {
		if step > limit {
			return ex, fmt.Errorf("exceeded step limit %d (planner oscillating?)", limit)
		}
		nxt, ok := d.Next()
		if !ok {
			ex.Stuck = true
			break
		}
		if !truth.CanMove(pos.X, pos.Y, nxt.X-pos.X, nxt.Y-pos.Y) {
			// Belief said the move was fine but the world disagrees: it must have been sensed first.
			return ex, fmt.Errorf("step %d: planner chose illegal move %v -> %v", step, pos, nxt)
		}
		ex.Travelled += truth.StepCost(pos.X, pos.Y, nxt.X-pos.X, nxt.Y-pos.Y)
		pos = nxt
		d.MoveTo(pos)
		ex.Trail = append(ex.Trail, pos)
		ch := sense(pos)
		if len(ch) > 0 {
			for _, c := range ch {
				d.CellChanged(c.X, c.Y)
			}
			d.Replan()
			if err := record(step, ch); err != nil {
				return ex, err
			}
		}
	}
	ex.Reached = pos == truth.Goal
	return ex, nil
}

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
