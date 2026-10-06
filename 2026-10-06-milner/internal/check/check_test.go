package check

import (
	"strings"
	"testing"

	"milner/internal/syntax"
	"milner/internal/types"
)

func analyze(t *testing.T, budget int, src string) []*syntax.Diag {
	t.Helper()
	decls, d := syntax.ParseProgram(src)
	if d != nil {
		t.Fatal(d)
	}
	env := types.NewBaseEnv()
	c := New(env.Cons)
	c.Budget = budget
	var all []*syntax.Diag
	for _, decl := range decls {
		all = append(all, c.Decl(decl)...)
	}
	return all
}

func TestWitnessFormatting(t *testing.T) {
	cases := []struct{ src, want string }{
		{`let f x = match x with Some (Some _) -> 1 | None -> 0`, "Some None"},
		{`let f x = match x with [] -> 0 | [_] -> 1`, "_ :: _ :: _"},
		{`let f x = match x with (None, _) -> 0 | (_, None) -> 1`, "(Some _, Some _)"},
		{`let f x = match x with Some 0 -> 0`, "None"},
		{`let f x = match x with {a = true; b} -> b`, "{ a = false; b = _ }"},
		{`let f x = match x with () -> 0 | _ -> 1`, ""},
	}
	for _, c := range cases {
		ws := analyze(t, 0, c.src)
		got := ""
		for _, w := range ws {
			if strings.Contains(w.Msg, "not exhaustive") {
				got = w.Label
			}
		}
		if c.want == "" {
			if got != "" {
				t.Errorf("%q: unexpected warning %q", c.src, got)
			}
			continue
		}
		if !strings.Contains(got, "`"+c.want+"`") {
			t.Errorf("%q: label %q lacks witness %q", c.src, got, c.want)
		}
	}
}

func TestAnalysisBudget(t *testing.T) {
	src := `let f x = match x with (true, _, _) -> 1 | (_, true, _) -> 2 | (_, _, true) -> 3 | (false, false, false) -> 4`
	if ws := analyze(t, 0, src); len(ws) != 0 {
		t.Errorf("default budget should suffice: %v", ws[0].Msg)
	}
	ws := analyze(t, 3, src)
	if len(ws) != 1 || !strings.Contains(ws[0].Msg, "gave up") {
		t.Errorf("a tiny budget must make the analysis give up cleanly, got %v", ws)
	}
}

func TestRedundantAlternativeInOrPattern(t *testing.T) {
	ws := analyze(t, 0, `let f x = match x with None | Some _ | None -> 1`)
	if len(ws) != 1 || !strings.Contains(ws[0].Msg, "never match") {
		t.Errorf("got %v", ws)
	}
	// the warning points at the redundant alternative only
	if ws[0].Span.Start.Col != 40 {
		t.Errorf("span starts at column %d", ws[0].Span.Start.Col)
	}
}
