package lang

import (
	"io"
	"strings"
	"testing"

	"milner/internal/syntax"
)

func newSession(t *testing.T) (*Session, *strings.Builder) {
	t.Helper()
	var out strings.Builder
	s, err := NewSession(&out)
	if err != nil {
		t.Fatal(err)
	}
	return s, &out
}

// typeOf returns the type string of the final expression/binding.
func typeOf(t *testing.T, src string) string {
	t.Helper()
	s, _ := newSession(t)
	s.Interp.M.Out = io.Discard
	outs, err := s.Run(src, false)
	if err != nil {
		t.Fatalf("unexpected error for %q: %v", src, err)
	}
	o := outs[len(outs)-1]
	if o.IsExpr {
		return typeStr(o)
	}
	return typeStr(o)
}

func typeStr(o *DeclOut) string {
	if o.IsExpr {
		return strings.TrimSpace(strings.SplitN(o.Format(), ":", 2)[1])
	}
	f := strings.TrimSpace(o.Format())
	lines := strings.Split(f, "\n")
	last := lines[len(lines)-1]
	return strings.TrimSpace(strings.SplitN(last, ":", 2)[1])
}

func TestInferredTypes(t *testing.T) {
	cases := []struct{ src, want string }{
		{`1`, "int"},
		{`"a" ^ "b"`, "string"},
		{`fun x -> x`, "'a -> 'a"},
		{`fun x y -> x`, "'a -> 'b -> 'a"},
		{`fun f g x -> f (g x)`, "('a -> 'b) -> ('c -> 'a) -> 'c -> 'b"},
		{`fun f x -> f (f x)`, "('a -> 'a) -> 'a -> 'a"},
		{`let id x = x in (id 1, id "s")`, "int * string"},
		{`let rec fib n = if n < 2 then n else fib (n-1) + fib (n-2) in fib`, "int -> int"},
		{`[1; 2; 3]`, "int list"},
		{`[]`, "'a list"},
		{`[[1]; []]`, "int list list"},
		{`(1, "a", true)`, "int * string * bool"},
		{`fun (a, b) -> (b, a)`, "'a * 'b -> 'b * 'a"},
		{`Some 1`, "int option"},
		{`None`, "'a option"},
		{`fun x -> match x with Some y -> y | None -> 0`, "int option -> int"},
		{`map`, "('a -> 'b) -> 'a list -> 'b list"},
		{`fold_left`, "('a -> 'b -> 'a) -> 'a -> 'b list -> 'a"},
		{`fun f -> map (map f)`, "('a -> 'b) -> 'a list list -> 'b list list"},
		{`(fun x -> x : int -> int)`, "int -> int"},
		{`compose`, "('a -> 'b) -> ('c -> 'a) -> 'c -> 'b"},
		{`ref 0`, "int ref"},
		{`let r = ref [] in r`, "'_a list ref"},
		{`fun x -> if x then 1 else 2`, "bool -> int"},
		{`fun x -> x + 1`, "int -> int"},
		{`fun x y -> x = y`, "'a -> 'a -> bool"},
		{`fun f -> f 1 |> f`, "(int -> int) -> int"},
		{`sort`, "('a -> 'a -> int) -> 'a list -> 'a list"},
		{`fun () -> 1`, "unit -> int"},
		{`let (a, b) = (1, "x") in a`, "int"},
		{`let rec even n = if n = 0 then true else odd (n - 1) and odd n = if n = 0 then false else even (n - 1) in even`, "int -> bool"},
		{`fun x -> (x, x)`, "'a -> 'a * 'a"},
		{`fun f -> fun x -> f x`, "('a -> 'b) -> 'a -> 'b"},
		{`Ok 1`, "(int, 'a) result"},
		{`fun (x, y) z -> x + y + z`, "int * int -> int -> int"},
	}
	for _, c := range cases {
		if got := typeOf(t, c.src); got != c.want {
			t.Errorf("type of %q:\n  got  %s\n  want %s", c.src, got, c.want)
		}
	}
}

func TestLetPolymorphismAndValueRestriction(t *testing.T) {
	// generalised: can be used at two types
	if got := typeOf(t, `let pair x = (x, x)
let a = pair 1
let b = pair "s";;
(a, b)`); got != "(int * int) * (string * string)" {
		t.Errorf("got %s", got)
	}
	// value restriction: `ref []` is weak, so using it at two types is rejected
	s, _ := newSession(t)
	_, err := s.Run(`let r = ref []
let _ = r := [1]
let _ = r := ["a"]`, false)
	if err == nil || !strings.Contains(err.Error(), "type") {
		t.Fatalf("expected a type error from the value restriction, got %v", err)
	}
	// weak var at top level is printed with an underscore
	s2, _ := newSession(t)
	outs, err := s2.Run(`let r = ref []`, false)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(outs[0].Format(), "'_a list ref") {
		t.Errorf("weak variable not shown: %s", outs[0].Format())
	}
	// ... and is refined by later use
	outs, err = s2.Run(`let _ = r := [1];;
r`, false)
	if err != nil {
		t.Fatal(err)
	}
	if got := typeStr(outs[1]); got != "int list ref" {
		t.Errorf("weak var not refined: %s", got)
	}
	// an eta-expanded version generalises
	if got := typeOf(t, `let f = fun x -> ref x;;
f`); got != "'a -> 'a ref" {
		t.Errorf("got %s", got)
	}
}

func TestTypeErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{`1 + "a"`, "expected `int`, found `string`"},
		{`if 1 then 2 else 3`, "expected `bool`, found `int`"},
		{`if true then 1 else "s"`, "expected `int`, found `string`"},
		{`fun x -> x x`, "infinite type"},
		{`undefined`, "unbound variable `undefined`"},
		{`let x = 1 in y`, "unbound variable `y`"},
		{`[1; "a"]`, "expected `int`, found `string`"},
		{`1 2`, "cannot be applied"},
		{`fun (a, b) -> a + b |> 1`, "cannot be applied"},
		{`let (a, b) = (1, 2, 3) in a`, "mismatched types"},
		{`Foo`, "unknown constructor `Foo`"},
		{`Some`, ""}, // constructor as function is fine -> no error expected below
		{`None 1`, "takes no argument"},
		{`match 1 with true -> 1 | _ -> 2`, "expected `int`, found `bool`"},
		{`match Some 1 with Some x -> x | None -> "a"`, "expected `int`, found `string`"},
		{`(1 : string)`, "expected `string`, found `int`"},
		{`fun x -> (x : int) + (x : string)`, "mismatched"},
		{`let rec x = 1 in x`, "must be a function"},
		{`fun (x, x) -> x`, "more than once"},
		{`match Some 1 with Some x | None -> 1`, "not on the right"},
		{`print_endline 5`, "expected `string`, found `int`"},
		{`1; 2`, "must have type `unit`"},
		{`let (Some a) = None in a + ""`, "mismatched"},
		{`map 1 [1]`, "mismatched"},
		{`(fun x -> x) 1 2`, "cannot be applied"},
		{`let f (x : 'a) (y : 'a) = x + y in f 1 "a"`, "mismatched"},
		{`type t = A of bar`, "unknown type `bar`"},
		{`type t = A of 'a`, "not declared"},
		{`type 'a t = A of t`, "expects 1 argument"},
		{`type t = A | A`, "defined twice"},
		{`let x : int = "a"`, "mismatched"},
	}
	for _, c := range cases {
		s, _ := newSession(t)
		_, err := s.Run(c.src, false)
		if c.want == "" {
			if err != nil {
				t.Errorf("%q: unexpected error %v", c.src, err)
			}
			continue
		}
		d, ok := err.(*syntax.Diag)
		if !ok {
			t.Errorf("%q: expected a diagnostic containing %q, got %v", c.src, c.want, err)
			continue
		}
		if !strings.Contains(d.Msg+" "+strings.Join(d.Notes, " ")+d.Label, c.want) {
			t.Errorf("%q: diagnostic %q (notes %v) lacks %q", c.src, d.Msg, d.Notes, c.want)
		}
	}
}

func TestFailedDeclLeavesNoTrace(t *testing.T) {
	s, _ := newSession(t)
	if _, err := s.Run(`let r = ref []`, false); err != nil {
		t.Fatal(err)
	}
	// this declaration refines the weak variable to int and then fails: the refinement must be undone
	if _, err := s.Run(`let bad = (r := [1]; 1 + "x")`, false); err == nil {
		t.Fatal("expected failure")
	}
	if _, err := s.Run(`let ok = r := ["fine"]`, false); err != nil {
		t.Fatalf("weak variable was polluted by a failed declaration: %v", err)
	}
}

func TestTypeDecls(t *testing.T) {
	src := `type 'a tree = Leaf | Node of 'a tree * 'a * 'a tree
type shape = Circle of int | Rect of int * int
type expr = Num of int | Add of expr * expr | Neg of expr
and env = Env of (string * int) list
let rec size t = match t with Leaf -> 0 | Node (l, _, r) -> size l + 1 + size r;;
size`
	if got := typeOf(t, src); got != "'a tree -> int" {
		t.Errorf("got %s", got)
	}
	// mutual recursion through `and`
	got := typeOf(t, `type a = A of b | ANil
and b = B of a | BNil
let x = A (B ANil);;
x`)
	if got != "a" {
		t.Errorf("got %s", got)
	}
	// constructors are first-class
	if got := typeOf(t, `map Some [1;2]`); got != "int option list" {
		t.Errorf("got %s", got)
	}
	if got := typeOf(t, `type p = P of int * string
let mk = P;;
mk`); got != "int * string -> p" {
		t.Errorf("got %s", got)
	}
	// redefinition makes a distinct type
	s, _ := newSession(t)
	if _, err := s.Run(`type t = A
let a = A
type t = B
let _ = (a : t)`, false); err == nil {
		t.Fatal("expected redefined type to be distinct")
	}
}
