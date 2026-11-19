package dot

import (
	"strings"
	"testing"
	"tier/layout"
)

func TestParseBasics(t *testing.T) {
	g, err := Parse(`/* c */ strict digraph "G" { rankdir=LR; node [shape=box]; a -> b -> c [label="x\"y"];
# hash comment at column 1
 d; a -> b; }`)
	if err != nil {
		t.Fatal(err)
	}
	if !g.Directed || !g.Strict || g.Name != "G" || g.Attrs["rankdir"] != "LR" {
		t.Fatalf("header: %+v", g)
	}
	if len(g.Nodes) != 4 || len(g.Edges) != 2 { // strict dedups a->b
		t.Fatalf("nodes %d edges %d", len(g.Nodes), len(g.Edges))
	}
	if g.Edges[1].Attrs["label"] != `x"y` || g.Nodes[0].Attrs["shape"] != "box" {
		t.Fatalf("attrs: %+v %+v", g.Edges[1], g.Nodes[0])
	}
}

func TestParseErrorsArePositioned(t *testing.T) {
	cases := map[string]string{
		"digraph { a -> }":           "line 1, col 16",
		"digraph { a -> b -- c }":    "not valid in a digraph",
		"graph { a -> b }":           "not valid in a graph",
		"digraph { a -> b":           "missing '}'",
		"digraph { subgraph s { } }": "subgraphs",
		"digraph { a:p -> b }":       "ports",
		"digraph { a [label=<b>] }":  "HTML",
		"digraph { a [label=\"x] }":  "unterminated string",
		"/* x":                       "unterminated /*",
		"digraph { a } extra":        "after closing",
		"":                           "expected 'digraph'",
		"digraph {\n\n  a -> ;\n}":   "line 3",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: got %v, want substring %q", src, err, want)
		}
	}
}

func TestToLayoutAttrs(t *testing.T) {
	g, _ := Parse(`digraph { rankdir=LR; a [label="id \N\nline2" shape=ellipse]; a -> b [weight=3 minlen=2 label=hi]; }`)
	lg, o, err := g.ToLayout(layoutOpts())
	if err != nil {
		t.Fatal(err)
	}
	if o.RankDir != "LR" || lg.Nodes[0].Label != "id a\\nline2" && lg.Nodes[0].Label != "id a\nline2" {
		t.Fatalf("%+v %+v", o, lg.Nodes[0])
	}
	if lg.Edges[0].Weight != 3 || lg.Edges[0].MinLen != 2 || lg.Edges[0].Label != "hi" {
		t.Fatalf("%+v", lg.Edges[0])
	}
	for _, bad := range []string{`digraph{a->b[weight=x]}`, `digraph{a->b[minlen=0]}`, `digraph{a[shape=star]}`, `digraph{rankdir=BT;a}`, `digraph{a[width=-1]}`} {
		g, err := Parse(bad)
		if err != nil {
			t.Fatal(err)
		}
		if _, _, err := g.ToLayout(layoutOpts()); err == nil {
			t.Errorf("%s accepted", bad)
		}
	}
}

func layoutOpts() (o layout.Options) { return }
