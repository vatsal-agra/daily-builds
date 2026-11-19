package render

import (
	"encoding/xml"
	"strings"
	"testing"

	"tier/layout"
)

func sample(t *testing.T, rd string) *layout.Result {
	g := layout.Graph{
		Nodes: []layout.InNode{{ID: "a<&>", Label: "a<&>\\nsecond", W: 60, H: 40, Shape: "box"}, {ID: "b", Label: "b", W: 50, H: 30, Shape: "ellipse"}, {ID: "c", Label: "c", W: 50, H: 30, Shape: "box"}},
		Edges: []layout.InEdge{{From: 0, To: 1, Label: "x & y"}, {From: 1, To: 2}, {From: 2, To: 0}, {From: 1, To: 1, Label: "me"}},
	}
	r, err := layout.Layout(g, layout.Options{RankDir: rd})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestSVGIsWellFormedXML(t *testing.T) {
	for _, rd := range []string{"TB", "LR"} {
		for _, o := range []Options{{Directed: true, Bands: true}, {Polyline: true}, {Inline: true, IDPrefix: "z"}} {
			s := SVG(sample(t, rd), o)
			d := xml.NewDecoder(strings.NewReader(s))
			for {
				if _, err := d.Token(); err != nil {
					if err.Error() != "EOF" {
						t.Fatalf("%s %+v: %v", rd, o, err)
					}
					break
				}
			}
			if strings.Contains(s, "NaN") || strings.Contains(s, "Inf") {
				t.Fatal("non-finite number in svg")
			}
		}
	}
}

func TestSVGContent(t *testing.T) {
	s := SVG(sample(t, "TB"), Options{Directed: true})
	for _, want := range []string{"a&lt;&amp;&gt;", "x &amp; y", "<ellipse", "class=\"e rev\"", "marker-end", "second"} {
		if !strings.Contains(s, want) {
			t.Errorf("missing %q", want)
		}
	}
	if strings.Contains(SVG(sample(t, "TB"), Options{}), "marker-end") {
		t.Error("undirected graph should have no arrowheads")
	}
}

func TestCatmullPassesThroughPoints(t *testing.T) {
	p := catmull([]layout.Pt{{X: 0, Y: 0}, {X: 10, Y: 20}, {X: 0, Y: 40}})
	if !strings.HasPrefix(p, "M0,0C") || !strings.HasSuffix(p, " 0,40") {
		t.Fatal(p)
	}
}
