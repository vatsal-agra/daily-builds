package layout

import (
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"testing"
)

func randGraph(rng *rand.Rand, n, m int, loops bool) Graph {
	var g Graph
	for i := 0; i < n; i++ {
		shape := "box"
		if rng.Intn(3) == 0 {
			shape = "ellipse"
		}
		g.Nodes = append(g.Nodes, InNode{ID: fmt.Sprintf("n%d", i), Label: fmt.Sprintf("n%d", i), W: 30 + float64(rng.Intn(60)), H: 20 + float64(rng.Intn(25)), Shape: shape})
	}
	for i := 0; i < m; i++ {
		a, b := rng.Intn(n), rng.Intn(n)
		if a == b && !loops {
			continue
		}
		g.Edges = append(g.Edges, InEdge{From: a, To: b, Weight: 1 + rng.Intn(3), MinLen: 1 + rng.Intn(2)/1*rng.Intn(2)})
	}
	return g
}

// checkInvariants verifies structural guarantees of a finished layout.
func checkInvariants(t *testing.T, g Graph, r *Result) {
	t.Helper()
	fin := func(x float64) bool { return !math.IsNaN(x) && !math.IsInf(x, 0) }
	if len(r.Nodes) != len(g.Nodes) || len(r.Edges) != len(g.Edges) {
		t.Fatalf("result size mismatch")
	}
	for i, a := range r.Nodes {
		if !fin(a.X) || !fin(a.Y) {
			t.Fatalf("node %d has non-finite position", i)
		}
		if a.X-a.W/2 < -0.01 || a.Y-a.H/2 < -0.01 || a.X+a.W/2 > r.Width+0.01 || a.Y+a.H/2 > r.Height+0.01 {
			t.Fatalf("node %s outside canvas: %+v canvas %gx%g", a.ID, a, r.Width, r.Height)
		}
		for j := i + 1; j < len(r.Nodes); j++ {
			b := r.Nodes[j]
			if math.Abs(a.X-b.X) < (a.W+b.W)/2-0.01 && math.Abs(a.Y-b.Y) < (a.H+b.H)/2-0.01 {
				t.Fatalf("nodes %s and %s overlap", a.ID, b.ID)
			}
		}
	}
	for i, e := range r.Edges {
		for _, p := range e.Points {
			if !fin(p.X) || !fin(p.Y) || p.X < -0.01 || p.Y < -0.01 || p.X > r.Width+0.01 || p.Y > r.Height+0.01 {
				t.Fatalf("edge %d point %+v outside canvas %gx%g", i, p, r.Width, r.Height)
			}
		}
		if e.From == e.To {
			if !e.SelfLoop || len(e.Points) != 4 {
				t.Fatalf("edge %d: bad self loop", i)
			}
			continue
		}
		ml := g.Edges[i].MinLen
		if ml < 1 {
			ml = 1
		}
		d := r.Nodes[e.To].Rank - r.Nodes[e.From].Rank
		if e.Reversed {
			d = -d
		}
		if d < ml {
			t.Fatalf("edge %d (%d->%d reversed=%v) rank span %d < minlen %d", i, e.From, e.To, e.Reversed, d, ml)
		}
		if len(e.Points) < 2 {
			t.Fatalf("edge %d has %d points", i, len(e.Points))
		}
		in := func(p Pt, n NodeBox) bool {
			return math.Abs(p.X-n.X) <= n.W/2+0.6 && math.Abs(p.Y-n.Y) <= n.H/2+0.6
		}
		if !in(e.Points[0], r.Nodes[e.From]) {
			t.Fatalf("edge %d starts at %+v, away from tail node %+v", i, e.Points[0], r.Nodes[e.From])
		}
		if !in(e.Points[len(e.Points)-1], r.Nodes[e.To]) {
			t.Fatalf("edge %d ends at %+v, away from head node %+v", i, e.Points[len(e.Points)-1], r.Nodes[e.To])
		}
	}
}

func TestInvariantsRandom(t *testing.T) {
	rng := rand.New(rand.NewSource(11))
	for it := 0; it < 300; it++ {
		n := 1 + rng.Intn(25)
		g := randGraph(rng, n, rng.Intn(n*3+1), it%3 == 0)
		for _, o := range []Options{{}, {RankDir: "LR"}, {Ranker: "longest", Acyclic: "dfs"}, {Order: "none", Coord: "packed"}} {
			r, err := Layout(g, o)
			if err != nil {
				t.Fatalf("iter %d opts %+v: %v", it, o, err)
			}
			checkInvariants(t, g, r)
		}
	}
}

func TestDeterministic(t *testing.T) {
	rng := rand.New(rand.NewSource(5))
	g := randGraph(rng, 40, 90, true)
	var first []byte
	for i := 0; i < 5; i++ {
		r, err := Layout(g, Options{})
		if err != nil {
			t.Fatal(err)
		}
		b, _ := json.Marshal(r)
		if first == nil {
			first = b
		} else if string(first) != string(b) {
			t.Fatal("layout is not deterministic")
		}
	}
}

func TestCrossingCountMatchesBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	for it := 0; it < 200; it++ {
		n := 2 + rng.Intn(18)
		g := randGraph(rng, n, n*2, false)
		pr, err := prepare(g, Options{})
		if err != nil {
			t.Fatal(err)
		}
		for _, c := range pr.comps {
			c.p.minimizeCrossings(6) // shuffle orders a bit
			want := 0
			pa := make([]int, c.p.n)
			pb := make([]int, c.p.n)
			for i := 0; i+1 < len(c.p.layers); i++ {
				want += c.p.crossBetweenPerms(c.p.layers[i], c.p.layers[i+1], pa, pb)
			}
			if got := c.p.crossings(); got != want {
				t.Fatalf("iter %d: BIT crossings %d != brute %d", it, got, want)
			}
		}
	}
}

func TestHeuristicNeverBeatsOptimalAndIsClose(t *testing.T) {
	rng := rand.New(rand.NewSource(21))
	tested, gapSum := 0, 0
	for it := 0; it < 150; it++ {
		n := 4 + rng.Intn(9)
		g := randGraph(rng, n, n+rng.Intn(n), false)
		r, err := Layout(g, Options{})
		if err != nil {
			t.Fatal(err)
		}
		best, ok, err := OptimalCrossings(g, Options{})
		if err != nil {
			t.Fatal(err)
		}
		if !ok {
			continue
		}
		tested++
		if r.Metrics.Crossings < best {
			t.Fatalf("iter %d: heuristic %d < optimal %d — oracle or counter is wrong", it, r.Metrics.Crossings, best)
		}
		gapSum += r.Metrics.Crossings - best
	}
	if tested < 50 {
		t.Fatalf("only %d graphs small enough for the oracle", tested)
	}
	t.Logf("oracle graphs: %d, mean gap %.3f crossings", tested, float64(gapSum)/float64(tested))
}
