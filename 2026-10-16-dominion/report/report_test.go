package report

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func extract(t *testing.T, html string) payload {
	t.Helper()
	i := strings.Index(html, "const D = ")
	j := strings.Index(html[i:], ";\nconst $")
	if i < 0 || j < 0 {
		t.Fatal("payload not found in report")
	}
	var p payload
	if err := json.Unmarshal([]byte(strings.ReplaceAll(html[i+len("const D = "):i+j], `<\/`, "</")), &p); err != nil {
		t.Fatalf("payload is not valid JSON: %v", err)
	}
	return p
}

func TestReportForEveryExample(t *testing.T) {
	files, _ := filepath.Glob("../examples/*.dom")
	if len(files) == 0 {
		t.Fatal("no examples")
	}
	for _, f := range files {
		src, _ := os.ReadFile(f)
		html, err := Build(filepath.Base(f), string(src), 3, 12)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		if !strings.HasPrefix(html, "<!doctype html>") || strings.Contains(html, "/*DATA*/") || strings.Contains(html, "%TITLE%") {
			t.Fatalf("%s: template not fully instantiated", f)
		}
		p := extract(t, html)
		if len(p.Stages) < 3 {
			t.Errorf("%s: only %d snapshots", f, len(p.Stages))
		}
		if len(p.Bench) != 4 {
			t.Fatalf("%s: bench rows = %d", f, len(p.Bench))
		}
		for _, b := range p.Bench {
			if !b.Ok {
				t.Errorf("%s: -O%d output mismatch in report", f, b.Level)
			}
		}
		if p.Bench[3].Cycles >= p.Bench[0].Cycles {
			t.Errorf("%s: -O3 not faster than -O0", f)
		}
		for si, st := range p.Stages {
			for _, fn := range st.Funcs {
				names := map[string]node{}
				for _, n := range fn.Nodes {
					names[n.Name] = n
					if n.W <= 0 || n.H <= 0 || n.X < 0 || n.Y < 0 || n.X+n.W > fn.Width || n.Y+n.H > fn.Height {
						t.Fatalf("%s stage %d @%s: node %s outside the canvas: %+v (canvas %vx%v)", f, si, fn.Name, n.Name, n, fn.Width, fn.Height)
					}
				}
				for _, e := range fn.Edges {
					if _, ok := names[e.From]; !ok {
						t.Fatalf("%s stage %d: dangling edge %s->%s", f, si, e.From, e.To)
					}
					if _, ok := names[e.To]; !ok {
						t.Fatalf("%s stage %d: dangling edge %s->%s", f, si, e.From, e.To)
					}
				}
				// no two nodes overlap
				for a := range fn.Nodes {
					for b := a + 1; b < len(fn.Nodes); b++ {
						x, y := fn.Nodes[a], fn.Nodes[b]
						if x.X < y.X+y.W && y.X < x.X+x.W && x.Y < y.Y+y.H && y.Y < x.Y+x.H {
							t.Fatalf("%s stage %d @%s: nodes %s and %s overlap", f, si, fn.Name, x.Name, y.Name)
						}
					}
				}
			}
		}
	}
}

func TestReportRejectsBadSourceAndEscapesScriptEnd(t *testing.T) {
	if _, err := Build("x", "fn main( {", 2, 12); err == nil {
		t.Fatal("syntax errors must be reported")
	}
	// a source containing "</script>" inside a comment must not break out of the data block
	html, err := Build("</title>", "// </script><b>x</b>\nfn main(){ return 1; }\n", 1, 12)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(html, "</script>") != 1 {
		t.Fatalf("data block terminated early (%d closing tags)", strings.Count(html, "</script>"))
	}
	if strings.Contains(html, "<title>Dominion — </title>") || !strings.Contains(html, "&lt;/title&gt;") {
		t.Fatal("title not HTML-escaped")
	}
	extract(t, html) // still parses
}
