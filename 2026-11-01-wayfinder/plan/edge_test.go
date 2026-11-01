package plan

import (
	"math"
	"testing"
	"time"

	"wayfinder/grid"
)

func mustParse(t *testing.T, s string) *grid.Grid {
	t.Helper()
	g, err := grid.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return g
}

func TestStartEqualsGoalIsRejectedAtParseButHandledByAPI(t *testing.T) {
	g := grid.New(5, 5)
	g.Start, g.Goal = grid.Point{X: 2, Y: 2}, grid.Point{X: 2, Y: 2}
	for _, f := range []func(*grid.Grid, grid.Point, grid.Point) (*Result, error){Dijkstra, AStar, JPS} {
		r, err := f(g, g.Start, g.Goal)
		if err != nil || !r.Found || r.Cost != 0 || len(r.Path) != 1 {
			t.Fatalf("start==goal: %+v %v", r, err)
		}
	}
	ex, err := Explore(g, 2)
	if err != nil || !ex.Reached || len(ex.Trail) != 1 {
		t.Fatalf("explore start==goal: %+v %v", ex, err)
	}
}

func TestUnreachableGoal(t *testing.T) {
	g := mustParse(t, "S..#...\n...#.G.\n...#...\n")
	for name, f := range map[string]func(*grid.Grid, grid.Point, grid.Point) (*Result, error){"dij": Dijkstra, "astar": AStar, "jps": JPS} {
		r, err := f(g, g.Start, g.Goal)
		if err != nil || r.Found {
			t.Fatalf("%s: want clean not-found, got %+v %v", name, r, err)
		}
	}
	ex, err := Explore(g, 2)
	if err != nil {
		t.Fatal(err)
	}
	if ex.Reached || !ex.Stuck {
		t.Fatalf("explore should report stuck: %+v", ex)
	}
}

func TestEndpointValidation(t *testing.T) {
	g := mustParse(t, "S#G\n...\n")
	if _, err := AStar(g, grid.Point{X: 1, Y: 0}, g.Goal); err == nil {
		t.Fatal("wall start accepted")
	}
	if _, err := AStar(g, g.Start, grid.Point{X: 9, Y: 9}); err == nil {
		t.Fatal("out-of-range goal accepted")
	}
	if _, err := Explore(g, 0); err == nil {
		t.Fatal("radius 0 accepted")
	}
}

func TestJPSOnUniformTerrainMatchesAStar(t *testing.T) {
	for seed := int64(0); seed < 200; seed++ {
		g, err := grid.Generate("random", 25, 25, seed, 0.3, 0)
		if err != nil {
			continue
		}
		for i, c := range g.Cost {
			if c != 0 {
				g.Cost[i] = 5
			}
		}
		a, _ := AStar(g, g.Start, g.Goal)
		j, err := JPS(g, g.Start, g.Goal)
		if err != nil || math.Abs(a.Cost-j.Cost) > 1e-9 {
			t.Fatalf("seed %d: a=%v j=%+v err=%v", seed, a.Cost, j, err)
		}
	}
}

func TestJPSRejectsMixedTerrain(t *testing.T) {
	g := mustParse(t, "S.~G\n")
	if _, err := JPS(g, g.Start, g.Goal); err == nil {
		t.Fatal("jps accepted mixed terrain")
	}
}

func TestHugeRadiusIsFast(t *testing.T) {
	g, _ := grid.Generate("rooms", 40, 40, 2, 0, 0)
	st := time.Now()
	if _, err := Explore(g, 1_000_000); err != nil {
		t.Fatal(err)
	}
	if time.Since(st) > 3*time.Second {
		t.Fatalf("huge radius took %v", time.Since(st))
	}
}

func TestTerrainAStarPrefersCheapDetour(t *testing.T) {
	g := mustParse(t, "S&&&G\n.....\n")
	r, _ := AStar(g, g.Start, g.Goal)
	if r.Path[1].Y != 1 && r.Path[1].X != 1 {
		t.Fatalf("unexpected path %v", r.Path)
	}
	for _, p := range r.Path {
		if g.At(p.X, p.Y) == 9 {
			t.Fatalf("walked through deep terrain: %v", r.Path)
		}
	}
}

func TestExploreTrailAlwaysLegalOnTruth(t *testing.T) {
	for seed := int64(0); seed < 120; seed++ {
		g, err := grid.Generate("caves", 30, 30, seed, 0, 0.3)
		if err != nil {
			continue
		}
		ex, err := Explore(g, 1)
		if err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if _, err := g.PathCost(ex.Trail); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if ex.Reached && ex.Trail[len(ex.Trail)-1] != g.Goal {
			t.Fatal("reached but trail does not end at goal")
		}
	}
}
