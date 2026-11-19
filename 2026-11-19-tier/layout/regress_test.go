package layout

import "testing"

func box(id string) InNode { return InNode{ID: id, W: 40, H: 24, Shape: "box"} }

func TestR1ManyComponentsWrapIntoRows(t *testing.T) {
	var g Graph
	for i := 0; i < 150; i++ {
		g.Nodes = append(g.Nodes, box("n"))
	}
	r, err := Layout(g, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if r.Rows < 4 || r.Width > 3*r.Height {
		t.Fatalf("components not wrapped: rows=%d size=%gx%g", r.Rows, r.Width, r.Height)
	}
	checkInvariants(t, g, r)
}

func TestR2SelfLoopsNest(t *testing.T) {
	g := Graph{Nodes: []InNode{box("a")}, Edges: []InEdge{{From: 0, To: 0}, {From: 0, To: 0}, {From: 0, To: 0}}}
	r, err := Layout(g, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if !(r.Edges[0].Points[1].X < r.Edges[1].Points[1].X && r.Edges[1].Points[1].X < r.Edges[2].Points[1].X) {
		t.Fatalf("loops not nested: %+v", r.Edges)
	}
	checkInvariants(t, g, r)
}

func TestR3HugeSizeRejected(t *testing.T) {
	g := Graph{Nodes: []InNode{{ID: "a", W: 1e9, H: 10}}}
	if _, err := Layout(g, Options{}); err == nil {
		t.Fatal("expected error for huge node")
	}
}

func TestR4RanksAlignAcrossComponents(t *testing.T) {
	g := Graph{Nodes: []InNode{box("a"), box("b"), {ID: "c", W: 40, H: 90}, box("d")},
		Edges: []InEdge{{From: 0, To: 1}, {From: 2, To: 3}}}
	r, err := Layout(g, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if r.Rows == 1 && (r.Nodes[1].Y != r.Nodes[3].Y || r.Nodes[0].Y != r.Nodes[2].Y) {
		t.Fatalf("rank rows misaligned: %+v", r.Nodes)
	}
}

func TestR9LabelsReserveRoomAndDontOverlap(t *testing.T) {
	g := Graph{Nodes: []InNode{box("a"), box("b")}}
	for i := 0; i < 4; i++ {
		g.Edges = append(g.Edges, InEdge{From: 0, To: 1, Label: "label-number-long"})
	}
	for _, rd := range []string{"TB", "LR"} {
		r, err := Layout(g, Options{RankDir: rd})
		if err != nil {
			t.Fatal(err)
		}
		for i := range r.Edges {
			if !r.Edges[i].HasLabel {
				t.Fatalf("edge %d has no label position", i)
			}
			for j := i + 1; j < len(r.Edges); j++ {
				a, b := r.Edges[i].LabelPos, r.Edges[j].LabelPos
				lw := labelW("label-number-long")
				ox := abs(a.X-b.X) < lw && abs(a.Y-b.Y) < labelH
				if ox {
					t.Fatalf("%s: labels %d and %d overlap: %+v %+v", rd, i, j, a, b)
				}
			}
		}
		checkInvariants(t, g, r)
	}
}

func abs(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}

func TestEmptyAndSingle(t *testing.T) {
	if r, err := Layout(Graph{}, Options{}); err != nil || len(r.Nodes) != 0 {
		t.Fatalf("empty: %v", err)
	}
	g := Graph{Nodes: []InNode{box("a")}}
	r, err := Layout(g, Options{})
	if err != nil {
		t.Fatal(err)
	}
	checkInvariants(t, g, r)
}

func TestBadOptionsAndEdges(t *testing.T) {
	g := Graph{Nodes: []InNode{box("a")}, Edges: []InEdge{{From: 0, To: 3}}}
	if _, err := Layout(g, Options{}); err == nil {
		t.Fatal("out-of-range edge accepted")
	}
	if _, err := Layout(Graph{}, Options{RankDir: "BT"}); err == nil {
		t.Fatal("bad rankdir accepted")
	}
}

func TestFeedbackSetBreaksAllCycles(t *testing.T) {
	for _, s := range []string{"greedy", "dfs"} {
		es := []InEdge{{From: 0, To: 1, Weight: 1}, {From: 1, To: 2, Weight: 1}, {From: 2, To: 0, Weight: 1}, {From: 2, To: 3, Weight: 1}, {From: 3, To: 1, Weight: 1}}
		rev := feedbackSet(4, es, s)
		_, err := longestPathRanks(4, func() []rankEdge {
			var r []rankEdge
			for i, e := range es {
				u, v := e.From, e.To
				if rev[i] {
					u, v = v, u
				}
				r = append(r, rankEdge{u, v, 1, 1})
			}
			return r
		}())
		if err != nil {
			t.Fatalf("%s left a cycle", s)
		}
	}
}
