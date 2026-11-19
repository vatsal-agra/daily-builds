package layout

import (
	"math/rand"
	"testing"
)

// bruteMinCost enumerates all rank assignments in [0,maxR] satisfying the
// constraints and returns the minimum Σ w·span.
func bruteMinCost(n int, edges []rankEdge, maxR int) int {
	rank := make([]int, n)
	best := -1
	var rec func(i int)
	rec = func(i int) {
		if i == n {
			for _, e := range edges {
				if rank[e.v]-rank[e.u] < e.minlen {
					return
				}
			}
			if c := rankCost(edges, rank); best < 0 || c < best {
				best = c
			}
			return
		}
		for r := 0; r <= maxR; r++ {
			rank[i] = r
			rec(i + 1)
		}
	}
	rec(0)
	return best
}

func TestNetworkSimplexMatchesBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	checked := 0
	for it := 0; it < 400; it++ {
		n := 2 + rng.Intn(5)
		var edges []rankEdge
		for i := 0; i < n*2; i++ {
			a, b := rng.Intn(n), rng.Intn(n)
			if a >= b {
				continue
			}
			edges = append(edges, rankEdge{a, b, 1 + rng.Intn(3), 1 + rng.Intn(2)})
		}
		// connect: chain any isolated pieces with a spanning path in the DAG order
		uf := make([]int, n)
		for i := range uf {
			uf[i] = i
		}
		var find func(int) int
		find = func(x int) int {
			if uf[x] != x {
				uf[x] = find(uf[x])
			}
			return uf[x]
		}
		for _, e := range edges {
			uf[find(e.u)] = find(e.v)
		}
		for i := 1; i < n; i++ {
			if find(i) != find(0) {
				edges = append(edges, rankEdge{i - 1, i, 1, 1})
				uf[find(i)] = find(0)
			}
		}
		got, err := networkSimplexRanks(n, edges)
		if err != nil {
			t.Fatalf("iter %d: %v", it, err)
		}
		for _, e := range edges {
			if got[e.v]-got[e.u] < e.minlen {
				t.Fatalf("iter %d: infeasible ranks %v for %+v", it, got, e)
			}
		}
		want := bruteMinCost(n, edges, 2*n)
		if c := rankCost(edges, got); c != want {
			t.Fatalf("iter %d: simplex cost %d, brute force %d (n=%d edges=%+v ranks=%v)", it, c, want, n, edges, got)
		}
		checked++
	}
	t.Logf("verified %d random graphs", checked)
}
