package plan

import (
	"math"
	"testing"

	"wayfinder/grid"
)

func TestFuzzOptimalAgreement(t *testing.T) {
	kinds := []string{"random", "maze", "rooms", "caves", "open"}
	n := 0
	for seed := int64(0); seed < 1500; seed++ {
		kind := kinds[int(seed)%len(kinds)]
		w, h := 8+int(seed%37), 8+int(seed*7%29)
		g, err := grid.Generate(kind, w, h, seed, 0.1+float64(seed%5)*0.08, 0)
		if err != nil {
			continue
		}
		d, _ := Dijkstra(g, g.Start, g.Goal)
		a, _ := AStar(g, g.Start, g.Goal)
		j, err := JPS(g, g.Start, g.Goal)
		if err != nil {
			t.Fatal(err)
		}
		if !d.Found || !a.Found || !j.Found {
			t.Fatalf("seed %d: found d=%v a=%v j=%v (endpoints are in one component)", seed, d.Found, a.Found, j.Found)
		}
		if math.Abs(d.Cost-a.Cost) > 1e-9 || math.Abs(d.Cost-j.Cost) > 1e-9 {
			t.Fatalf("seed %d %s %dx%d: costs differ d=%v a=%v j=%v\n%s", seed, kind, w, h, d.Cost, a.Cost, j.Cost, g.Format())
		}
		c, err := g.PathCost(Densify(j.Path))
		if err != nil || math.Abs(c-j.Cost) > 1e-9 {
			t.Fatalf("seed %d: jps path invalid: %v cost %v vs %v", seed, err, c, j.Cost)
		}
		n++
	}
	if n < 1000 {
		t.Fatalf("only %d maps exercised", n)
	}
}

func TestExploreMatchesAStar(t *testing.T) {
	kinds := []string{"random", "maze", "rooms", "caves", "open"}
	reached, stuck := 0, 0
	for seed := int64(0); seed < 300; seed++ {
		g, err := grid.Generate(kinds[int(seed)%5], 12+int(seed%30), 12+int(seed*3%25), seed, 0.25, float64(seed%3)*0.3)
		if err != nil {
			continue
		}
		ex, err := Explore(g, 1+int(seed%4))
		if err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if ex.Reached {
			reached++
			if len(ex.Trail) < 2 && g.Start != g.Goal {
				t.Fatalf("seed %d: no trail", seed)
			}
			if _, err := g.PathCost(ex.Trail); err != nil {
				t.Fatalf("seed %d: trail illegal in true world: %v", seed, err)
			}
		}
		if ex.Stuck {
			stuck++
		}
	}
	if reached < 250 {
		t.Fatalf("only %d/300 runs reached the goal (stuck=%d)", reached, stuck)
	}
}
