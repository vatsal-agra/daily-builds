package learn

import (
	"math"
	"math/rand"
	"sort"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/parse"
)

func parentsOf(n *bn.Network) [][]int {
	p := make([][]int, len(n.Vars))
	for v := range n.Vars {
		p[v] = append([]int(nil), n.Vars[v].Parents...)
		sort.Ints(p[v])
	}
	return p
}

func TestCPDAGTextbook(t *testing.T) {
	// chain 0→1→2: all edges undirected; collider 0→1←2: both directed
	chain := CPDAG([][]int{{}, {0}, {1}})
	if chain[0][1] != Und || chain[1][2] != Und || chain[0][2] != None {
		t.Fatalf("chain: %v", chain)
	}
	col := CPDAG([][]int{{}, {0, 2}, {}})
	if col[0][1] != Fwd || col[2][1] != Fwd || col[1][0] != Bwd {
		t.Fatalf("collider: %v", col)
	}
	// Meek R1: 0→1←2 plus 1→3 with 0,3 nonadjacent... 3 child of 1 is compelled (1→3)
	r1 := CPDAG([][]int{{}, {0, 2}, {}, {1}})
	if r1[1][3] != Fwd {
		t.Fatalf("R1 should compel 1→3: %v", r1)
	}
	// R2: 0→1→2 and 0→2 (triangle, no v-structure): all undirected
	tri := CPDAG([][]int{{}, {0}, {0, 1}})
	if tri[0][1] != Und || tri[1][2] != Und || tri[0][2] != Und {
		t.Fatalf("triangle: %v", tri)
	}
}

// Property: reversing a *covered* edge (parents(b) = parents(a) ∪ {a}) yields a
// Markov-equivalent DAG, so the CPDAG must not change, and BIC/BDeu must agree.
func TestCoveredEdgeReversalPreservesCPDAGAndScore(t *testing.T) {
	rng := rand.New(rand.NewSource(21))
	n := load(t, "student.bn")
	ds := Simulate(n, 4000, rng, 0, nil)
	checked := 0
	for trial := 0; trial < 400 && checked < 60; trial++ {
		g := bn.Random(rng, bn.RandomOpts{Vars: 6, MaxParents: 3, MaxCard: 2, EdgeProb: 0.6})
		par := parentsOf(g)
		// find a covered edge a→b
		for b := range par {
			for _, a := range par[b] {
				if !sameSet(remove(par[b], a), par[a]) {
					continue
				}
				rev := cloneParents(par)
				rev[b] = remove(rev[b], a)
				rev[a] = insertSorted(rev[a], b)
				d, _ := Compare(par, rev)
				if d.SHD != 0 {
					t.Fatalf("covered reversal changed the CPDAG: %v → %v", par, rev)
				}
				checked++
				// scores on arbitrary data over 6 binary vars
				net6 := bn.New("six")
				for i := 0; i < 6; i++ {
					net6.AddVar(string(rune('A'+i)), []string{"0", "1"})
				}
				data := Simulate(g, 3000, rng, 0, nil)
				for _, sc := range []Score{BIC, BDeu} {
					x, err1 := ScoreStructure(g, data, par, StructureOptions{Score: sc, ESS: 2})
					y, err2 := ScoreStructure(g, data, rev, StructureOptions{Score: sc, ESS: 2})
					if err1 != nil || err2 != nil {
						t.Fatal(err1, err2)
					}
					if sc == BDeu && math.Abs(x-y) > 1e-6 {
						t.Fatalf("BDeu must be score-equivalent: %g vs %g", x, y)
					}
					if sc == BIC && math.Abs(x-y) > 1e-6 {
						t.Fatalf("BIC must be score-equivalent: %g vs %g", x, y)
					}
				}
				_ = ds
				_ = net6
				break
			}
		}
	}
	if checked < 30 {
		t.Fatalf("only %d covered edges exercised", checked)
	}
}

func sameSet(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	x, y := append([]int(nil), a...), append([]int(nil), b...)
	sort.Ints(x)
	sort.Ints(y)
	for i := range x {
		if x[i] != y[i] {
			return false
		}
	}
	return true
}

func TestHillClimbRecoversKnownStructures(t *testing.T) {
	for _, tc := range []struct {
		file  string
		rows  int
		score Score
		maxSH int
	}{
		{"student.bn", 30000, BIC, 0},
		{"sprinkler.bn", 30000, BIC, 0},
		{"burglar.bn", 200000, BDeu, 0},
		{"car.bn", 40000, BIC, 0},
		{"asia.bn", 20000, BDeu, 0}, // deterministic OR node, rare disease: needs the likelihood-equivalent prior
	} {
		truth := load(t, tc.file)
		ds := Simulate(truth, tc.rows, rand.New(rand.NewSource(31)), 0, nil)
		res, err := HillClimb(truth, ds, StructureOptions{Score: tc.score, MaxParents: 3, ESS: 1})
		if err != nil {
			t.Fatal(err)
		}
		d, _ := Compare(parentsOf(truth), res.Parents)
		t.Logf("%s (%v, %d rows): SHD %d (missing %d extra %d misoriented %d of %d edges), %d steps", tc.file, tc.score, tc.rows, d.SHD, d.Missing, d.Extra, d.Misoriented, d.TrueEdges, len(res.Steps))
		if d.SHD > tc.maxSH {
			t.Errorf("%s: SHD %d > %d", tc.file, d.SHD, tc.maxSH)
		}
		// learned graph must be a valid DAG and obey MaxParents
		g := truth.Clone()
		for v := range g.Vars {
			g.SetParents(v, res.Parents[v])
			if len(res.Parents[v]) > 3 {
				t.Fatal("max parents violated")
			}
		}
		if g.FindCycle() != nil {
			t.Fatal("learned graph has a cycle")
		}
	}
}

func TestHillClimbScoreNeverBelowEmptyGraphAndMovesAreGains(t *testing.T) {
	truth := load(t, "student.bn")
	ds := Simulate(truth, 5000, rand.New(rand.NewSource(3)), 0, nil)
	opt := StructureOptions{Score: BIC}
	res, _ := HillClimb(truth, ds, opt)
	empty, _ := ScoreStructure(truth, ds, make([][]int, len(truth.Vars)), opt)
	if res.Score < empty {
		t.Fatalf("learned score %g below empty graph %g", res.Score, empty)
	}
	sum := empty
	for _, m := range res.Steps {
		sum += m.Gain
	}
	if math.Abs(sum-res.Score) > 1e-6 {
		t.Fatalf("empty score + gains = %g but final score %g", sum, res.Score)
	}
	again, _ := ScoreStructure(truth, ds, res.Parents, opt)
	if math.Abs(again-res.Score) > 1e-6 {
		t.Fatalf("reported score %g, recomputed %g", res.Score, again)
	}
}

func TestIndependentDataLearnsNoEdges(t *testing.T) {
	n := bn.New("indep")
	for i := 0; i < 6; i++ {
		n.AddVar(string(rune('A'+i)), []string{"0", "1", "2"})
	}
	ds := Simulate(n, 3000, rand.New(rand.NewSource(1)), 0, nil)
	for _, sc := range []Score{BIC, BDeu} {
		res, err := HillClimb(n, ds, StructureOptions{Score: sc})
		if err != nil {
			t.Fatal(err)
		}
		edges := 0
		for _, p := range res.Parents {
			edges += len(p)
		}
		if edges != 0 {
			t.Errorf("%v hallucinated %d edges in independent data", sc, edges)
		}
	}
}

func TestStructureErrorsAndMissingRows(t *testing.T) {
	n := load(t, "sprinkler.bn")
	ds := Simulate(n, 400, rand.New(rand.NewSource(1)), 0.05, nil)
	res, err := HillClimb(n, ds, StructureOptions{Score: BIC})
	if err != nil {
		t.Fatal(err)
	}
	if res.Dropped == 0 || res.Rows+res.Dropped != 400 {
		t.Fatalf("rows %d dropped %d", res.Rows, res.Dropped)
	}
	if _, err := HillClimb(n, &parse.Dataset{Cols: []int{0, 1}, Rows: [][]int{{0, 1}, {1, 0}}}, StructureOptions{}); err == nil {
		t.Fatal("missing columns accepted")
	}
	if _, err := HillClimb(n, &parse.Dataset{Cols: []int{0, 1, 2, 3}, Rows: [][]int{{0, 0, 0, 0}}}, StructureOptions{}); err == nil {
		t.Fatal("one row accepted")
	}
	if _, err := ParseScore("aic"); err == nil {
		t.Fatal("bad score name accepted")
	}
}

func TestMaxParentsAndRestarts(t *testing.T) {
	truth := load(t, "car.bn")
	ds := Simulate(truth, 20000, rand.New(rand.NewSource(5)), 0, nil)
	one, _ := HillClimb(truth, ds, StructureOptions{Score: BIC, MaxParents: 1})
	for v, p := range one.Parents {
		if len(p) > 1 {
			t.Fatalf("variable %d has %d parents with MaxParents=1", v, len(p))
		}
	}
	base, _ := HillClimb(truth, ds, StructureOptions{Score: BIC, MaxParents: 3})
	more, _ := HillClimb(truth, ds, StructureOptions{Score: BIC, MaxParents: 3, Restarts: 5, Seed: 2})
	if more.Score < base.Score-1e-9 {
		t.Fatalf("restarts made the score worse: %g < %g", more.Score, base.Score)
	}
}

func TestApplyFitsParameters(t *testing.T) {
	truth := load(t, "student.bn")
	ds := Simulate(truth, 30000, rand.New(rand.NewSource(8)), 0, nil)
	res, _ := HillClimb(truth, ds, StructureOptions{Score: BIC})
	learned, err := res.Apply(truth, ds, 1)
	if err != nil {
		t.Fatal(err)
	}
	if errs := learned.Validate(); len(errs) > 0 {
		t.Fatal(errs)
	}
	ll, _ := LogLikelihood(learned, ds)
	llTruth, _ := LogLikelihood(truth, ds)
	if ll < llTruth-30 {
		t.Fatalf("learned model explains the data far worse (%g vs %g)", ll, llTruth)
	}
}
