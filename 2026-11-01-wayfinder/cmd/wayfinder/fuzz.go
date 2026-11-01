package main

import (
	"fmt"
	"math"
	"time"

	"wayfinder/grid"
	"wayfinder/plan"
)

// validate cross-checks every planner on one map and returns the first
// disagreement as an error.
func validate(g *grid.Grid) error {
	d, err := plan.Dijkstra(g, g.Start, g.Goal)
	if err != nil {
		return err
	}
	a, err := plan.AStar(g, g.Start, g.Goal)
	if err != nil {
		return err
	}
	if d.Found != a.Found || math.Abs(d.Cost-a.Cost) > 1e-9 {
		return fmt.Errorf("dijkstra (%v,%.6f) != astar (%v,%.6f)", d.Found, d.Cost, a.Found, a.Cost)
	}
	if a.Found {
		if c, err := g.PathCost(a.Path); err != nil || math.Abs(c-a.Cost) > 1e-9 {
			return fmt.Errorf("astar path invalid or cost mismatch: %v (%v vs %v)", err, c, a.Cost)
		}
	}
	if g.Uniform() {
		j, err := plan.JPS(g, g.Start, g.Goal)
		if err != nil {
			return err
		}
		if j.Found != a.Found || math.Abs(j.Cost-a.Cost) > 1e-9 {
			return fmt.Errorf("jps (%v,%.6f) != astar (%v,%.6f)", j.Found, j.Cost, a.Found, a.Cost)
		}
		if j.Found {
			if c, err := g.PathCost(plan.Densify(j.Path)); err != nil || math.Abs(c-j.Cost) > 1e-9 {
				return fmt.Errorf("jps path invalid: %v", err)
			}
		}
		th, err := plan.ThetaStar(g, g.Start, g.Goal)
		if err != nil {
			return err
		}
		if th.Found != a.Found {
			return fmt.Errorf("theta* found=%v astar found=%v", th.Found, a.Found)
		}
		if th.Found {
			c, err := plan.ValidAnyAngle(g, th.Path)
			if err != nil || math.Abs(c-th.Cost) > 1e-6 {
				return fmt.Errorf("theta* path invalid: %v (len %v vs %v)", err, c, th.Cost)
			}
			if th.Cost < grid.Euclid(g.Start, g.Goal)*g.MinCost()-1e-9 {
				return fmt.Errorf("theta* cost %.6f is shorter than the straight line", th.Cost)
			}
		}
	}
	hp, err := plan.HPA(g, g.Start, g.Goal, 8)
	if err != nil {
		return err
	}
	if hp.Found != a.Found {
		return fmt.Errorf("hpa* found=%v astar found=%v", hp.Found, a.Found)
	}
	if hp.Found {
		c, err := g.PathCost(hp.Path)
		if err != nil || math.Abs(c-hp.Cost) > 1e-6 {
			return fmt.Errorf("hpa* path invalid: %v (%v vs %v)", err, c, hp.Cost)
		}
		if hp.Cost < a.Cost-1e-9 {
			return fmt.Errorf("hpa* cost %.6f beats the optimum %.6f", hp.Cost, a.Cost)
		}
	}
	return nil
}

func cmdFuzz(args []string) error {
	fs := newFlags("fuzz")
	n := fs.Int("n", 500, "number of random maps")
	seed := fs.Int64("seed", 1, "first seed")
	explore := fs.Int("explore-every", 5, "also run a D* Lite exploration (self-checking) every k maps (0 = never)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *n < 1 {
		return fmt.Errorf("-n must be >= 1")
	}
	t0 := time.Now()
	ran, explored, skipped := 0, 0, 0
	for i := 0; i < *n; i++ {
		sd := *seed + int64(i)
		kind := grid.Kinds[int(sd)%len(grid.Kinds)]
		terrain := 0.0
		if sd%3 == 0 {
			terrain = 0.35
		}
		w, h := 10+int(sd*7%50), 10+int(sd*11%40)
		g, err := grid.Generate(kind, w, h, sd, 0.1+float64(sd%5)*0.07, terrain)
		if err != nil {
			skipped++
			continue
		}
		if err := validate(g); err != nil {
			fmt.Printf("FAIL seed=%d kind=%s %dx%d terrain=%.2f: %v\n%s", sd, kind, w, h, terrain, err, g.Format())
			return fmt.Errorf("fuzz found a disagreement")
		}
		ran++
		if *explore > 0 && i%*explore == 0 {
			if _, err := plan.Explore(g, 1+int(sd%4)); err != nil {
				fmt.Printf("FAIL seed=%d kind=%s explore: %v\n%s", sd, kind, err, g.Format())
				return fmt.Errorf("fuzz found a disagreement")
			}
			explored++
		}
	}
	fmt.Printf("fuzz OK: %d maps cross-validated (%d skipped as ungeneratable), %d D* Lite explorations self-checked, in %v\n",
		ran, skipped, explored, time.Since(t0).Round(time.Millisecond))
	return nil
}
