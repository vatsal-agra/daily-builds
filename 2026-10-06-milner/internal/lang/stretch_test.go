package lang

import (
	"strings"
	"testing"

	"milner/internal/syntax"
)

func TestRecordTypes(t *testing.T) {
	cases := []struct{ src, want string }{
		{`{ x = 1; y = "a" }`, "{ x : int; y : string }"},
		{`{ y = "a"; x = 1 }`, "{ x : int; y : string }"}, // field order is irrelevant
		{`fun r -> r.x`, "{ x : 'a; .. } -> 'a"},
		{`fun r -> r.x + r.y`, "{ x : int; y : int; .. } -> int"},
		{`fun r -> (r.a, r.b)`, "{ a : 'a; b : 'b; .. } -> 'a * 'b"},
		{`fun r -> { r with x = 1 }`, "{ x : int; .. } -> { x : int; .. }"},
		{`fun { a; b } -> a + b`, "{ a : int; b : int; .. } -> int"},
		{`fun { a = (x, y); b } -> x + y + b`, "{ a : int * int; b : int; .. } -> int"},
		{`fun r -> r.next.value`, "{ next : { value : 'a; .. }; .. } -> 'a"},
		{`let get r = r.x in (get { x = 1 }, get { x = "s"; y = true })`, "int * string"},
		{`(fun (r : { x : int; .. }) -> r.x)`, "{ x : int; .. } -> int"},
		{`fun (r : { x : int }) -> r`, "{ x : int } -> { x : int }"},
		{`map (fun p -> p.n) [{ n = 1 }; { n = 2; m = 3 }]`, ""}, // different closed shapes: rejected below
	}
	for _, c := range cases[:len(cases)-1] {
		if got := typeOf(t, c.src); got != c.want {
			t.Errorf("type of %q:\n  got  %s\n  want %s", c.src, got, c.want)
		}
	}
	// a list whose elements are records of different shapes is a type error
	s, _ := newSession(t)
	if _, err := s.Run(`[{ n = 1 }; { n = 2; m = 3 }]`, false); err == nil {
		t.Error("expected closed records of different shapes to be rejected")
	}
}

func TestRecordErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{`{ x = 1 }.y`, "no field `y`"},
		{`(3).x`, "not a record"},
		{`{ x = 1; x = 2 }`, "defined twice"},
		{`{ r with x = 1 }`, "unbound variable"},
		{`let r = { x = 1 } in { r with x = "s" }`, "cannot change a field's type"},
		{`let r = { x = 1 } in { r with y = 2 }`, "no field `y`"},
		{`fun (r : { x : int }) -> r.y`, "no field `y`"},
		{`(fun (r : { x : int }) -> r.x) { x = 1; y = 2 }`, "closed"},
		{`(fun r -> r.x r)`, "infinite type"},
		{`type t = A of { x : int; .. }`, "only allowed in annotations"},
		{`let f { x; x } = x`, "appears twice"},
		{`fun { x = 1 } -> 2 + (fun (a : string) -> a)`, "mismatched"},
		{`{ }`, "at least one field"},
		{`(fun { a } -> a) 3`, "mismatched"},
	}
	for _, c := range cases {
		s, _ := newSession(t)
		_, err := s.Run(c.src, false)
		d, ok := err.(*syntax.Diag)
		if !ok {
			t.Errorf("%q: expected an error containing %q, got %v", c.src, c.want, err)
			continue
		}
		if all := d.Msg + " " + d.Label + " " + strings.Join(d.Notes, " "); !strings.Contains(all, c.want) {
			t.Errorf("%q: diagnostic %q lacks %q", c.src, all, c.want)
		}
	}
}

func TestRecordEvaluation(t *testing.T) {
	cases := []struct{ src, want string }{
		{`{ b = 2; a = 1 }`, "{ a = 1; b = 2 }"},
		{`let p = { x = 1; y = 2 } in p.x + p.y`, "3"},
		{`let p = { x = 1; y = 2 } in { p with y = 20 }`, "{ x = 1; y = 20 }"},
		{`let p = { x = 1; y = 2 } in let q = { p with x = 9 } in (p.x, q.x)`, "(1, 9)"},
		{`let x = 5 in let y = 6 in { x; y }`, "{ x = 5; y = 6 }"},
		{`(fun { a; b } -> a * b) { b = 4; a = 3; c = 0 }`, "12"},
		{`let r = { inner = { v = 7 } } in r.inner.v`, "7"},
		{`match { k = 1; v = "one" } with { k = 1; v } -> v | { v; .. } -> "other"`, `"one"`},
		{`match { k = 2; v = "two" } with { k = 1; v } -> v | { v; .. } -> "other:" ^ v`, `"other:two"`},
		{`{ a = 1; b = 2 } = { b = 2; a = 1 }`, "true"},
		{`compare { a = 1; b = 5 } { a = 1; b = 3 }`, "1"},
		{`sort (fun p q -> compare p.n q.n) [{ n = 3 }; { n = 1 }; { n = 2 }]`, "[{ n = 1 }; { n = 2 }; { n = 3 }]"},
		{`let c = { n = ref 0 } in c.n := !(c.n) + 5; !(c.n)`, "5"},
		{`map (fun { n; .. } -> n) [{ n = 1; z = () }; { n = 2; z = () }]`, "[1; 2]"},
		{`let f { a; b } = a - b in f { a = 10; b = 3 }`, "7"},
		{`fold_left (fun acc p -> acc + p.w) 0 [{ w = 1 }; { w = 2 }; { w = 3 }]`, "6"},
	}
	for _, c := range cases {
		if got := value(t, c.src); got != c.want {
			t.Errorf("%q:\n  got  %s\n  want %s", c.src, got, c.want)
		}
	}
}

func TestRecordPatternExhaustiveness(t *testing.T) {
	ws := warnings(t, `let f r = match r with { b = true; n } -> n | { b = false; n = 0 } -> 0`)
	if len(ws) != 1 || !strings.Contains(ws[0], "not exhaustive") || !strings.Contains(ws[0], "b = false") {
		t.Errorf("got %v", ws)
	}
	if ws := warnings(t, `let f r = match r with { b = true; n } -> n | { b = false; n } -> n + 1`); len(ws) != 0 {
		t.Errorf("exhaustive record match warned: %v", ws)
	}
	ws = warnings(t, `let f r = match r with { a = 0 } -> 1 | { a = 0; b } -> 2 | _ -> 3`)
	if len(ws) != 1 || !strings.Contains(ws[0], "never match") {
		t.Errorf("got %v", ws)
	}
	if ws := warnings(t, `let f { a; b } = a + b`); len(ws) != 0 {
		t.Errorf("record parameter is irrefutable: %v", ws)
	}
}

func TestTypeAliases(t *testing.T) {
	cases := []struct{ src, want string }{
		{`type point = { x : int; y : int };; let o : point = { x = 0; y = 0 };; o`, "{ x : int; y : int }"},
		{`type 'a pair = 'a * 'a;; let swap ((a, b) : 'a pair) = (b, a);; swap`, "'a * 'a -> 'a * 'a"},
		{`type ('k, 'v) table = ('k * 'v) list;; let find (k : 'k) (t : ('k, 'v) table) = assoc_opt k t;; find`, "'a -> ('a * 'b) list -> 'b option"},
		{`type id = int;; type ids = id list;; ([1; 2] : ids)`, "int list"},
		{`type shape = Circle of int | Poly of (int * int) list;; type canvas = shape list;; ([Circle 1] : canvas)`, "shape list"},
	}
	for _, c := range cases {
		if got := typeOf(t, c.src); got != c.want {
			t.Errorf("%q:\n  got  %s\n  want %s", c.src, got, c.want)
		}
	}
	for src, want := range map[string]string{
		`type t = t list`:                     "cannot be recursive",
		`type 'a p = 'a * 'b`:                 "not declared",
		`type p = int * ;; let x = 1`:         "expected a type",
		`type p = int;; let x : p = "s"`:      "mismatched",
		`type 'a p = 'a * 'a;; let x : p = 1`: "expects 1 argument",
	} {
		s, _ := newSession(t)
		_, err := s.Run(src, false)
		if err == nil || !strings.Contains(strings.ToLower(err.Error()+fmtDiag(err)), strings.ToLower(want)) {
			t.Errorf("%q: got %v want %q", src, err, want)
		}
	}
}

func fmtDiag(err error) string {
	if d, ok := err.(*syntax.Diag); ok {
		return d.Msg + " " + d.Label + " " + strings.Join(d.Notes, " ")
	}
	return ""
}

func TestExplainTrace(t *testing.T) {
	s, _ := newSession(t)
	lines, err := s.Explain(`let id x = x in (id 1, id "a")`)
	if err != nil {
		t.Fatal(err)
	}
	trace := strings.Join(lines, "\n")
	for _, want := range []string{
		"infer  let id x = x in",
		"generalize `id` : 'a -> 'a",
		"instantiate `id` : 'a -> 'a  ⟹  t",
		"unify t", "✓", ":= int", ":= string",
		"⊢ id 1, id \"a\" : int * string",
		"result: int * string",
	} {
		if !strings.Contains(trace, want) {
			t.Errorf("trace lacks %q:\n%s", want, trace)
		}
	}
	// the two instantiations of `id` must use different variables
	var insts []string
	for _, l := range lines {
		if strings.Contains(l, "instantiate `id`") {
			insts = append(insts, l)
		}
	}
	if len(insts) != 2 || insts[0] == insts[1] {
		t.Errorf("expected two distinct instantiations, got %v", insts)
	}

	// a failing inference still returns the partial trace plus the error
	lines, err = s.Explain(`fun x -> x + "a"`)
	if err == nil {
		t.Fatal("expected a type error")
	}
	if tr := strings.Join(lines, "\n"); !strings.Contains(tr, "✗ fails") {
		t.Errorf("trace should show the failing unification:\n%s", tr)
	}
	// multiple declarations
	lines, err = s.Explain("let a = 1\nlet b = a + 1")
	if err != nil || !strings.Contains(strings.Join(lines, "\n"), "── declaration 2 ──") {
		t.Errorf("err=%v lines=%v", err, lines)
	}
	if _, err := s.Explain(`let (`); err == nil {
		t.Error("syntax errors must be reported")
	}
}

func TestTypedHoles(t *testing.T) {
	s, _ := newSession(t)
	_, err := s.Run(`let f (n : int) (s : string) = n + _`, false)
	d, ok := err.(*syntax.Diag)
	if !ok || d.Kind != "hole" || !strings.Contains(d.Msg, "`int`") {
		t.Fatalf("got %v", err)
	}
	joined := strings.Join(d.Notes, "\n")
	if !strings.Contains(joined, "n : int") || strings.Contains(joined, "s : string") {
		t.Errorf("hole candidates should list `n` but not `s`:\n%s", joined)
	}
	// the hole's type is inferred from context, including function types
	_, err = s.Run(`let g xs = map _ xs;; let h = g [1; 2]`, false)
	d, _ = err.(*syntax.Diag)
	if d == nil || d.Kind != "hole" || !strings.Contains(d.Msg, "->") {
		t.Errorf("got %v", err)
	}
	// holes never reach the evaluator and never pollute the environment
	if _, err := s.Run(`let f = _`, true); err == nil {
		t.Error("expected a hole error")
	}
	if _, ok := s.Env.Lookup("f"); ok {
		t.Error("a failed declaration must not bind its name")
	}
}
