package lang

import (
	"strings"
	"testing"
)

// warnings runs src (type-check only) and returns all warning messages with their labels.
func warnings(t *testing.T, src string) []string {
	t.Helper()
	s, _ := newSession(t)
	outs, err := s.Run(src, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var ws []string
	for _, o := range outs {
		for _, w := range o.Warnings {
			ws = append(ws, w.Msg+" | "+w.Label+" | "+strings.Join(w.Notes, " "))
		}
	}
	return ws
}

const shapes = `type shape = Circle of int | Rect of int * int | Tri of int * int * int | Dot
type color = Red | Green | Blue
`

func TestExhaustiveness(t *testing.T) {
	cases := []struct {
		name, src string
		missing   string // expected witness substring; "" = exhaustive & no redundancy
		redundant bool
	}{
		{"all constructors", shapes + `let f s = match s with Circle r -> r | Rect (a, b) -> a | Tri (a, _, _) -> a | Dot -> 0`, "", false},
		{"missing nullary", shapes + `let f c = match c with Red -> 1 | Green -> 2`, "Blue", false},
		{"missing with payload", shapes + `let f s = match s with Circle _ -> 1 | Dot -> 0`, "Rect (_, _)", false},
		{"wildcard covers", shapes + `let f c = match c with Red -> 1 | _ -> 2`, "", false},
		{"redundant after wildcard", shapes + `let f c = match c with _ -> 1 | Red -> 2`, "", true},
		{"duplicate arm", shapes + `let f c = match c with Red -> 1 | Green -> 2 | Blue -> 3 | Red -> 4`, "", true},
		{"bool exhaustive", `let f b = match b with true -> 1 | false -> 0`, "", false},
		{"bool missing", `let f b = match b with true -> 1`, "false", false},
		{"int needs default", `let f n = match n with 0 -> 1 | 1 -> 2`, "_", false},
		{"int with default", `let f n = match n with 0 -> 1 | _ -> 2`, "", false},
		{"string literals", `let f s = match s with "a" -> 1 | "b" -> 2`, "_", false},
		{"list exhaustive", `let f l = match l with [] -> 0 | _ :: _ -> 1`, "", false},
		{"list missing nil", `let f l = match l with _ :: _ -> 1`, "[]", false},
		{"list missing singleton", `let f l = match l with [] -> 0 | _ :: _ :: _ -> 2`, "_ :: []", false},
		{"list length 2 pattern", `let f l = match l with [] -> 0 | [_] -> 1 | _ :: _ :: _ -> 2`, "", false},
		{"nested option", `let f o = match o with Some (Some _) -> 1 | None -> 0`, "Some None", false},
		{"tuple of bools", `let f p = match p with (true, _) -> 1 | (_, true) -> 2`, "(false, false)", false},
		{"tuple of bools full", `let f p = match p with (true, _) -> 1 | (false, true) -> 2 | (false, false) -> 3`, "", false},
		{"or pattern covers", shapes + `let f c = match c with Red | Green -> 1 | Blue -> 2`, "", false},
		{"or pattern redundant alt", shapes + `let f c = match c with Red | Red -> 1 | _ -> 2`, "", true},
		{"as pattern", `let f o = match o with Some _ as x -> x | None -> None`, "", false},
		{"guard does not count", `let f n = match n with x when x > 0 -> 1`, "_", false},
		{"guard then default", `let f n = match n with x when x > 0 -> 1 | _ -> 0`, "", false},
		{"guarded arm is not redundant", `let f n = match n with 0 -> 0 | x when x > 5 -> 1 | _ -> 2`, "", false},
		{"unit", `let f u = match u with () -> 1`, "", false},
		{"function keyword", shapes + `let f = function Red -> 1 | Green -> 2`, "Blue", false},
		{"deep tuple of constructors", shapes + `let f p = match p with (Red, Red) -> 1 | (Green, _) -> 2 | (_, Blue) -> 3`, "(Blue, Red)", false},
		{"result type", `let f r = match r with Ok x -> x | Error _ -> 0`, "", false},
		{"nested list of option", `let f l = match l with [] -> 0 | Some _ :: _ -> 1`, "None :: _", false},
	}
	for _, c := range cases {
		ws := warnings(t, c.src)
		var gotMissing, gotRedundant bool
		for _, w := range ws {
			if strings.Contains(w, "not exhaustive") {
				gotMissing = true
				if c.missing == "" || !strings.Contains(w, "`"+c.missing+"`") {
					t.Errorf("%s: unexpected/wrong exhaustiveness warning (want witness %q): %s", c.name, c.missing, w)
				}
			}
			if strings.Contains(w, "never match") {
				gotRedundant = true
			}
		}
		if c.missing != "" && !gotMissing {
			t.Errorf("%s: expected a missing-case warning containing %q, got %v", c.name, c.missing, ws)
		}
		if gotRedundant != c.redundant {
			t.Errorf("%s: redundant=%v want %v (%v)", c.name, gotRedundant, c.redundant, ws)
		}
	}
}

func TestRefutableBindings(t *testing.T) {
	ws := warnings(t, `let (Some x) = Some 1`)
	if len(ws) != 1 || !strings.Contains(ws[0], "refutable") || !strings.Contains(ws[0], "None") {
		t.Errorf("got %v", ws)
	}
	if ws := warnings(t, `let (a, b) = (1, 2)`); len(ws) != 0 {
		t.Errorf("tuple destructuring is irrefutable, got %v", ws)
	}
	ws = warnings(t, `let f (Some x) = x`)
	if len(ws) != 1 || !strings.Contains(ws[0], "parameter") {
		t.Errorf("got %v", ws)
	}
	if ws := warnings(t, `let f = fun (a, _) [] -> a`); len(ws) != 1 {
		t.Errorf("list parameter pattern [] is refutable: %v", ws)
	}
}

func TestPreludeIsWarningFree(t *testing.T) {
	// the prelude is analysed on load; re-run to make sure it produces no warnings of its own
	s, _ := newSession(t)
	outs, err := s.Run(preludeSrc, false)
	_ = s
	if err != nil {
		// re-declaring the prelude in a session that already has it is fine
		t.Fatal(err)
	}
	for _, o := range outs {
		if len(o.Warnings) > 0 {
			t.Errorf("prelude warning: %v", o.Warnings[0].Msg)
		}
	}
}
