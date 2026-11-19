package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func runCLI(stdin string, args ...string) (int, string, string) {
	var o, e bytes.Buffer
	c := run(args, strings.NewReader(stdin), &o, &e)
	return c, o.String(), e.String()
}

func TestLayoutSVGAndFlagsAfterFile(t *testing.T) {
	dir := t.TempDir()
	out := filepath.Join(dir, "o.svg")
	code, _, e := runCLI("", "layout", "../../examples/build.dot", "-o", out, "-rankdir", "lr")
	if code != 0 {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(out)
	s := string(b)
	if !strings.Contains(s, "<svg") || strings.Count(s, `class="n"`) != 12 || !strings.Contains(s, "marker-end") {
		t.Fatalf("bad svg (%d bytes)", len(s))
	}
}

func TestJSONFormat(t *testing.T) {
	code, o, e := runCLI("digraph{a->b->c; a->c}", "layout", "-format", "json", "-")
	if code != 0 {
		t.Fatal(e)
	}
	var v struct {
		Nodes []struct{ ID string }
		Edges []struct{ Points []struct{ X, Y float64 } }
	}
	if err := json.Unmarshal([]byte(o), &v); err != nil || len(v.Nodes) != 3 || len(v.Edges) != 3 || len(v.Edges[2].Points) != 3 {
		t.Fatalf("%v %+v", err, v)
	}
}

func TestMetricsAndExact(t *testing.T) {
	code, o, _ := runCLI("digraph{a->b;a->c;b->d;c->d}", "metrics", "-")
	if code != 0 || !strings.Contains(o, "crossings    0") {
		t.Fatalf("%d %s", code, o)
	}
	code, o, _ = runCLI("digraph{a->c;a->d;b->c;b->d}", "exact", "-")
	if code != 0 || !strings.Contains(o, "optimal crossings   1") || !strings.Contains(o, "gap                 0") {
		t.Fatalf("%d %s", code, o)
	}
}

func TestReportContainsAllVariants(t *testing.T) {
	code, o, e := runCLI("", "report", "../../examples/states.dot")
	if code != 0 {
		t.Fatal(e)
	}
	if strings.Count(o, `<section class="card`) != 5 || !strings.Contains(o, "Longest-path layering") || strings.Contains(o, "NaN") {
		t.Fatal("report malformed")
	}
}

func TestGenIsReproducibleAndLaysOut(t *testing.T) {
	for _, k := range []string{"layered", "dag", "cyclic", "tree"} {
		_, a, _ := runCLI("", "gen", "-kind", k, "-n", "60", "-seed", "4")
		_, b, _ := runCLI("", "gen", "-kind", k, "-n", "60", "-seed", "4")
		if a != b || a == "" {
			t.Fatalf("%s not reproducible", k)
		}
		if code, _, e := runCLI(a, "metrics", "-"); code != 0 {
			t.Fatalf("%s: %s", k, e)
		}
	}
	if code, _, _ := runCLI("", "gen", "-kind", "nope"); code == 0 {
		t.Fatal("bad kind accepted")
	}
	if code, _, _ := runCLI("", "gen", "-n", "0"); code == 0 {
		t.Fatal("n=0 accepted")
	}
}

func TestErrorPaths(t *testing.T) {
	for _, tc := range []struct {
		in   string
		args []string
		want string
	}{
		{"x", []string{"metrics", "-"}, "<stdin>: line 1"},
		{"", []string{"layout"}, "exactly one input"},
		{"", []string{"layout", "/no/such.dot"}, "no such file"},
		{"digraph{a}", []string{"layout", "-ranker", "zzz", "-"}, "unknown ranker"},
		{"digraph{a}", []string{"layout", "-format", "png", "-"}, "unknown -format"},
		{"", []string{"bogus"}, "unknown command"},
	} {
		code, _, e := runCLI(tc.in, tc.args...)
		if code == 0 || !strings.Contains(e, tc.want) {
			t.Errorf("%v: code %d stderr %q want %q", tc.args, code, e, tc.want)
		}
	}
	if code, _, _ := runCLI(""); code != 2 {
		t.Fatal("no args should exit 2")
	}
}

func TestEmptyGraphIsFine(t *testing.T) {
	if code, o, _ := runCLI("digraph{}", "layout", "-"); code != 0 || !strings.Contains(o, "<svg") {
		t.Fatal("empty graph failed")
	}
}
