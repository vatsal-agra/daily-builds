package plan

import (
	"math"
	"math/rand"
	"testing"

	"wayfinder/grid"
)

func TestThetaStarValidAndShortest(t *testing.T) {
	shorter, n := 0, 0
	for seed := int64(0); seed < 400; seed++ {
		g, err := grid.Generate(grid.Kinds[int(seed)%5], 15+int(seed%30), 15+int(seed*3%25), seed, 0.2, 0)
		if err != nil {
			continue
		}
		a, _ := AStar(g, g.Start, g.Goal)
		th, err := ThetaStar(g, g.Start, g.Goal)
		if err != nil || th.Found != a.Found {
			t.Fatalf("seed %d: %v found %v/%v", seed, err, th.Found, a.Found)
		}
		c, err := ValidAnyAngle(g, th.Path)
		if err != nil || math.Abs(c-th.Cost) > 1e-6 {
			t.Fatalf("seed %d: invalid theta path: %v (%v vs %v)", seed, err, c, th.Cost)
		}
		if th.Cost < grid.Euclid(g.Start, g.Goal)*g.MinCost()-1e-9 {
			t.Fatalf("seed %d: shorter than straight line", seed)
		}
		n++
		if th.Cost < a.Cost-1e-9 {
			shorter++
		}
		if th.Cost > a.Cost*1.05+1e-9 {
			t.Fatalf("seed %d: theta cost %v much worse than grid-optimal %v", seed, th.Cost, a.Cost)
		}
	}
	if shorter < n/4 {
		t.Fatalf("theta* beat the grid optimum on only %d/%d maps; any-angle shortcuts not working", shorter, n)
	}
}

func TestThetaStraightLineOnOpenMap(t *testing.T) {
	g := grid.New(30, 20)
	g.Start, g.Goal = grid.Point{X: 0, Y: 0}, grid.Point{X: 29, Y: 19}
	th, _ := ThetaStar(g, g.Start, g.Goal)
	if len(th.Path) != 2 || math.Abs(th.Cost-grid.Euclid(g.Start, g.Goal)) > 1e-9 {
		t.Fatalf("open map should give one straight segment, got %v cost %v", th.Path, th.Cost)
	}
}

func TestThetaRejectsMixedTerrain(t *testing.T) {
	g := mustParse(t, "S.~G\n")
	if _, err := ThetaStar(g, g.Start, g.Goal); err == nil {
		t.Fatal("accepted mixed terrain")
	}
}

func TestHPAFoundIffAStarAndNearOptimal(t *testing.T) {
	worst, sum, cnt := 1.0, 0.0, 0
	for seed := int64(0); seed < 300; seed++ {
		g, err := grid.Generate(grid.Kinds[int(seed)%5], 20+int(seed%40), 20+int(seed*3%30), seed, 0.2, float64(seed%2)*0.3)
		if err != nil {
			continue
		}
		a, _ := AStar(g, g.Start, g.Goal)
		for _, cs := range []int{4, 8, 16} {
			h, err := HPA(g, g.Start, g.Goal, cs)
			if err != nil || h.Found != a.Found {
				t.Fatalf("seed %d cs %d: %v found %v vs %v", seed, cs, err, h.Found, a.Found)
			}
			c, err := g.PathCost(h.Path)
			if err != nil || math.Abs(c-h.Cost) > 1e-6 {
				t.Fatalf("seed %d cs %d: bad path %v (%v vs %v)", seed, cs, err, c, h.Cost)
			}
			if h.Cost < a.Cost-1e-9 {
				t.Fatalf("seed %d: hpa %v beat optimum %v", seed, h.Cost, a.Cost)
			}
			r := h.Cost / math.Max(a.Cost, 1e-9)
			sum, cnt = sum+r, cnt+1
			if r > worst {
				worst = r
			}
			if h.Path[0] != g.Start || h.Path[len(h.Path)-1] != g.Goal {
				t.Fatalf("hpa path endpoints wrong")
			}
		}
	}
	// HPA* is a trade-off: on tiny maps with short paths a path can be ~1.8x optimal
	// (documented in the README); on average it stays within ~12%.
	if mean := sum / float64(cnt); mean > 1.12 || worst > 2.0 {
		t.Fatalf("hpa* suboptimality too high: mean %.3f worst %.3f", mean, worst)
	}
	t.Logf("hpa suboptimality: mean %.3f worst %.3f", sum/float64(cnt), worst)
}

func TestHPAGraphReuseLeavesNoResidue(t *testing.T) {
	g, _ := grid.Generate("rooms", 60, 40, 3, 0, 0)
	h := BuildHPA(g, 8)
	nodes := len(h.cells)
	edges := 0
	for _, a := range h.adj {
		edges += len(a)
	}
	rng := rand.New(rand.NewSource(1))
	comp := g.Component(g.Start)
	var first *Result
	for i := 0; i < 40; i++ {
		s, tt := comp[rng.Intn(len(comp))], comp[rng.Intn(len(comp))]
		r, err := h.Query(s, tt)
		if err != nil || !r.Found {
			t.Fatalf("query %d: %v", i, err)
		}
		if i == 0 {
			first = r
		}
		e2 := 0
		for _, a := range h.adj {
			e2 += len(a)
		}
		if len(h.cells) != nodes || e2 != edges || len(h.idOf) != nodes {
			t.Fatalf("query %d leaked graph state: nodes %d->%d edges %d->%d", i, nodes, len(h.cells), edges, e2)
		}
	}
	again, _ := h.Query(first.Path[0], first.Path[len(first.Path)-1])
	if math.Abs(again.Cost-first.Cost) > 1e-9 {
		t.Fatal("repeat query changed result")
	}
}

func TestHPAInvalidClusterSize(t *testing.T) {
	g := grid.New(5, 5)
	if _, err := HPA(g, g.Start, g.Goal, 1); err == nil {
		t.Fatal("cluster size 1 accepted")
	}
}

func TestHeapOrderingAndUpdate(t *testing.T) {
	h := NewHeap(1000)
	rng := rand.New(rand.NewSource(3))
	want := map[int]float64{}
	for i := 0; i < 1000; i++ {
		v := rng.Float64() * 100
		h.Update(i, Key{v, 0})
		want[i] = v
	}
	for i := 0; i < 400; i++ { // decrease, increase, remove
		id := rng.Intn(1000)
		switch i % 3 {
		case 0, 1:
			v := rng.Float64() * 100
			h.Update(id, Key{v, 0})
			want[id] = v
		case 2:
			h.Remove(id)
			delete(want, id)
		}
	}
	prev := -1.0
	n := 0
	for h.Len() > 0 {
		_, k := h.Peek()
		id := h.Pop()
		if k[0] < prev-1e-9 || math.Abs(k[0]-want[id]) > 1e-12 {
			t.Fatalf("heap order broken: %v after %v (want %v)", k[0], prev, want[id])
		}
		prev = k[0]
		delete(want, id)
		n++
	}
	if len(want) != 0 {
		t.Fatalf("%d items lost", len(want))
	}
}

func TestDStarLiteSavesWorkWhereReplanningIsExpensive(t *testing.T) {
	// Mazes and room-and-corridor maps are where from-scratch A* is misled by the
	// heuristic on every replan; D* Lite's repairs must cost much less in aggregate.
	// (On sparse random maps A* is already cheap and the two are roughly even.)
	for _, kind := range []string{"maze", "rooms"} {
		ds, as := 0, 0
		for seed := int64(0); seed < 6; seed++ {
			g, err := grid.Generate(kind, 121, 121, seed, 0, 0)
			if err != nil {
				continue
			}
			ex, err := Explore(g, 2)
			if err != nil || !ex.Reached {
				t.Fatalf("%s seed %d: %v reached=%v", kind, seed, err, ex != nil && ex.Reached)
			}
			// exclude the initial plan: it is a full search by design
			ds += ex.DStarTotal - ex.Events[0].DStarExp
			as += ex.AStarTotal - ex.Events[0].AStarExp
		}
		if float64(as) < 2*float64(ds) {
			t.Fatalf("%s: D* Lite repairs %d vs A* replans %d — expected at least a 2x saving", kind, ds, as)
		}
		t.Logf("%s: repairs %d vs from-scratch %d (%.1fx)", kind, ds, as, float64(as)/float64(ds))
	}
}
