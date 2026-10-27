package graph

import (
	"math/rand"
	"sort"
	"testing"

	"bayou/internal/bn"
)

// chordal: a graph is chordal iff repeatedly removing a simplicial vertex empties it.
func isChordal(g *Undirected) bool {
	w := g.Clone()
	alive := map[int]bool{}
	for v := 0; v < g.N; v++ {
		alive[v] = true
	}
	for len(alive) > 0 {
		found := -1
		for v := range alive {
			nb := w.Neighbors(v)
			ok := true
			for i, a := range nb {
				for _, b := range nb[i+1:] {
					if !w.Has(a, b) {
						ok = false
					}
				}
			}
			if ok {
				found = v
				break
			}
		}
		if found < 0 {
			return false
		}
		for _, u := range w.Neighbors(found) {
			delete(w.Adj[u], found)
		}
		w.Adj[found] = map[int]bool{}
		delete(alive, found)
	}
	return true
}

func TestTriangulationIsChordalAndCoversMoralGraph(t *testing.T) {
	rng := rand.New(rand.NewSource(11))
	for trial := 0; trial < 300; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 2 + rng.Intn(25), MaxParents: 1 + rng.Intn(4), MaxCard: 3, EdgeProb: rng.Float64()})
		card := make([]int, len(n.Vars))
		for i := range card {
			card[i] = n.Card(i)
		}
		g := Moralize(n)
		for _, h := range []Heuristic{MinFill, MinWeight} {
			order := EliminationOrder(g, card, nil, h)
			if len(order) != len(n.Vars) {
				t.Fatal("order misses variables")
			}
			cl, fill := Triangulate(g, order)
			if !isChordal(fill) {
				t.Fatalf("trial %d: fill-in graph is not chordal", trial)
			}
			for u := 0; u < g.N; u++ {
				for v := range g.Adj[u] {
					if !fill.Has(u, v) {
						t.Fatal("fill graph lost a moral edge")
					}
				}
			}
			for _, c := range MaximalCliques(cl) {
				for i, a := range c {
					for _, b := range c[i+1:] {
						if !fill.Has(a, b) {
							t.Fatal("reported clique is not complete in the fill graph")
						}
					}
				}
			}
		}
	}
}

func TestJunctionTreeProperties(t *testing.T) {
	rng := rand.New(rand.NewSource(12))
	for trial := 0; trial < 300; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 1 + rng.Intn(25), MaxParents: 1 + rng.Intn(4), MaxCard: 3, EdgeProb: rng.Float64()})
		jt, err := BuildJunctionTree(n, MinFill)
		if err != nil {
			t.Fatal(err)
		}
		if len(jt.Edges) != len(jt.Cliques)-1 {
			t.Fatalf("not a tree: %d cliques, %d edges", len(jt.Cliques), len(jt.Edges))
		}
		// every family lies inside a clique
		for v, x := range n.Vars {
			fam := append([]int{v}, x.Parents...)
			sort.Ints(fam)
			ok := false
			for _, c := range jt.Cliques {
				if isSubset(fam, c) {
					ok = true
				}
			}
			if !ok {
				t.Fatalf("family of %s is in no clique", x.Name)
			}
		}
		// no clique contained in another (maximality)
		for i, a := range jt.Cliques {
			for j, b := range jt.Cliques {
				if i != j && isSubset(a, b) {
					t.Fatalf("clique %v ⊆ %v", a, b)
				}
			}
		}
		// separators are the clique intersections
		for _, e := range jt.Edges {
			if len(Intersect(jt.Cliques[e.A], jt.Cliques[e.B])) != len(e.Sep) {
				t.Fatal("separator is not the intersection")
			}
		}
	}
}

func TestKnownTreewidths(t *testing.T) {
	// a chain has treewidth 1
	n := bn.New("chain")
	for i := 0; i < 20; i++ {
		n.AddVar(string(rune('a'+i)), []string{"0", "1"})
		if i > 0 {
			n.SetParents(i, []int{i - 1})
		}
	}
	jt, _ := BuildJunctionTree(n, MinFill)
	if jt.TreeWidth() != 1 {
		t.Fatalf("chain treewidth %d", jt.TreeWidth())
	}
	// one child with 6 parents → clique of size 7
	m := bn.New("star")
	for i := 0; i < 7; i++ {
		m.AddVar(string(rune('a'+i)), []string{"0", "1"})
	}
	m.SetParents(6, []int{0, 1, 2, 3, 4, 5})
	jt, _ = BuildJunctionTree(m, MinFill)
	if jt.TreeWidth() != 6 {
		t.Fatalf("v-structure treewidth %d", jt.TreeWidth())
	}
}

func TestDSeparationTextbookCases(t *testing.T) {
	// chain a→b→c, fork a←b→c, collider a→b←c (+ descendant d)
	mk := func(edges [][2]int, n int) *bn.Network {
		net := bn.New("t")
		for i := 0; i < n; i++ {
			net.AddVar(string(rune('a'+i)), []string{"0", "1"})
		}
		ps := map[int][]int{}
		for _, e := range edges {
			ps[e[1]] = append(ps[e[1]], e[0])
		}
		for v, p := range ps {
			net.SetParents(v, p)
		}
		return net
	}
	chain := mk([][2]int{{0, 1}, {1, 2}}, 3)
	if DSeparated(chain, []int{0}, []int{2}, nil) || !DSeparated(chain, []int{0}, []int{2}, []int{1}) {
		t.Fatal("chain")
	}
	fork := mk([][2]int{{1, 0}, {1, 2}}, 3)
	if DSeparated(fork, []int{0}, []int{2}, nil) || !DSeparated(fork, []int{0}, []int{2}, []int{1}) {
		t.Fatal("fork")
	}
	col := mk([][2]int{{0, 1}, {2, 1}, {1, 3}}, 4)
	if !DSeparated(col, []int{0}, []int{2}, nil) || DSeparated(col, []int{0}, []int{2}, []int{1}) || DSeparated(col, []int{0}, []int{2}, []int{3}) {
		t.Fatal("collider: observing the child or its descendant must open the path")
	}
	// Markov blanket of a: parents none, child b, co-parent c
	if mb := MarkovBlanket(col, 0); len(mb) != 2 || mb[0] != 1 || mb[1] != 2 {
		t.Fatalf("blanket %v", mb)
	}
}
