package lang

import (
	"strings"
	"testing"

	"milner/internal/syntax"
)

// value runs src and returns the Show-ed value of the last declaration's expression (or first binding).
func value(t *testing.T, src string) string {
	t.Helper()
	s, out := newSession(t)
	outs, err := s.Run(src, true)
	if err != nil {
		if d, ok := err.(*syntax.Diag); ok {
			t.Fatalf("error running %q:\n%s", src, d.Render(src, "t"))
		}
		t.Fatalf("error running %q: %v", src, err)
	}
	_ = out
	o := outs[len(outs)-1]
	f := strings.TrimSpace(o.Format())
	lines := strings.Split(f, "\n")
	last := lines[len(lines)-1]
	i := strings.Index(last, " = ")
	if i < 0 {
		t.Fatalf("no value in %q", last)
	}
	return last[i+3:]
}

func TestEvaluation(t *testing.T) {
	cases := []struct{ src, want string }{
		{`1 + 2 * 3`, "7"},
		{`(1 + 2) * 3`, "9"},
		{`10 - 2 - 3`, "5"},
		{`17 / 5`, "3"},
		{`(-17) / 5`, "-3"},
		{`17 mod 5`, "2"},
		{`-3 + 1`, "-2"},
		{`- (2 + 3)`, "-5"},
		{`"a" ^ "b" ^ "c"`, `"abc"`},
		{`1 < 2 && 2 < 3`, "true"},
		{`1 > 2 || false`, "false"},
		{`if 1 = 1 then "y" else "n"`, `"y"`},
		{`let x = 5 in let y = x * 2 in x + y`, "15"},
		{`let x = 1 in let x = x + 1 in x`, "2"},
		{`(fun x y -> x - y) 10 3`, "7"},
		{`let add x y = x + y in let inc = add 1 in inc 41`, "42"},
		{`let k x y = x in k 1 2`, "1"},
		{`(fun f -> f 1 2) (fun a b -> a + b)`, "3"},
		{`let f x = fun y -> x + y in f 1 2`, "3"}, // over-application of a 1-ary closure
		{`let rec fact n = if n <= 1 then 1 else n * fact (n - 1) in fact 10`, "3628800"},
		{`let rec fib n = if n < 2 then n else fib (n-1) + fib (n-2) in fib 20`, "6765"},
		{`let rec even n = if n = 0 then true else odd (n-1) and odd n = if n = 0 then false else even (n-1) in (even 10, odd 7, even 7)`, "(true, true, false)"},
		{`[1; 2; 3]`, "[1; 2; 3]"},
		{`1 :: 2 :: []`, "[1; 2]"},
		{`[1; 2] @ [3]`, "[1; 2; 3]"},
		{`(1, "a", [true])`, `(1, "a", [true])`},
		{`Some (1, 2)`, "Some (1, 2)"},
		{`Some (Some (-1))`, "Some (Some (-1))"},
		{`[Some 1; None]`, "[Some 1; None]"},
		{`map (fun x -> x * x) [1; 2; 3]`, "[1; 4; 9]"},
		{`filter (fun x -> x mod 2 = 0) (range 0 10)`, "[0; 2; 4; 6; 8]"},
		{`fold_left (+) 0 [1; 2; 3; 4]`, "10"},
		{`fold_right (fun x acc -> x :: acc) [1;2;3] []`, "[1; 2; 3]"},
		{`rev [1; 2; 3]`, "[3; 2; 1]"},
		{`length [1; 2; 3]`, "3"},
		{`sort compare [3; 1; 2; 5; 4]`, "[1; 2; 3; 4; 5]"},
		{`sort (fun a b -> compare b a) ["b"; "a"; "c"]`, `["c"; "b"; "a"]`},
		{`zip [1; 2; 3] ["a"; "b"]`, `[(1, "a"); (2, "b")]`},
		{`join ", " ["a"; "b"; "c"]`, `"a, b, c"`},
		{`take 2 [1; 2; 3]`, "[1; 2]"},
		{`drop 2 [1; 2; 3]`, "[3]"},
		{`assoc_opt 2 [(1, "a"); (2, "b")]`, `Some "b"`},
		{`find_opt (fun x -> x > 2) [1; 2; 3; 4]`, "Some 3"},
		{`let r = ref 0 in r := !r + 5; r := !r * 2; !r`, "10"},
		{`let (a, b) = (1, 2) in a + b`, "3"},
		{`let [x; y] = [1; 2] in x * y`, "2"},
		{`match [1; 2; 3] with x :: _ -> x | [] -> 0`, "1"},
		{`match (1, "a") with (1, s) -> s | _ -> "?"`, `"a"`},
		{`match Some 5 with Some n when n > 10 -> "big" | Some _ -> "small" | None -> "none"`, `"small"`},
		{`(function 0 -> "zero" | n -> if n < 0 then "neg" else "pos") (-4)`, `"neg"`},
		{`match [1;2] with [a; b] | [a; b; _] -> a + b | _ -> 0`, "3"},
		{`match Some 1 with Some _ as o -> o | None -> None`, "Some 1"},
		{`match "hi" with "hi" -> 1 | _ -> 0`, "1"},
		{`1 |> succ |> succ`, "3"},
		{`compose succ (fun x -> x * 2) 5`, "11"},
		{`string_length "héllo"`, "5"},
		{`string_sub "hello" 1 3`, `"ell"`},
		{`string_explode "abc"`, `["a"; "b"; "c"]`},
		{`char_code "A"`, "65"},
		{`char_of_code 97`, `"a"`},
		{`int_of_string_opt "42"`, "Some 42"},
		{`int_of_string_opt "4x"`, "None"},
		{`string_of_int (-5)`, `"-5"`},
		{`compare 1 2`, "-1"},
		{`compare "b" "a"`, "1"},
		{`(1, "a") < (1, "b")`, "true"},
		{`[1; 2] = [1; 2]`, "true"},
		{`Some 1 <> None`, "true"},
		{`Ok 1 = (Ok 1 : (int, string) result)`, "true"},
		{`let x = 1;; let x = x + 1;; x`, "2"},
		{`let f () = 7 in f ()`, "7"},
		{`let (x, _) = (3, 4) in x`, "3"},
		{`let f (x : int) : int = x + 1 in f 2`, "3"},
		{`min 3 2 + max 3 2`, "5"},
		{`(!) (ref 4)`, "4"},
		{`let swap (a, b) = (b, a) in swap (1, "x")`, `("x", 1)`},
		{`print_string "x"; 5`, "5"},
		{`option_map (fun x -> x + 1) (Some 1)`, "Some 2"},
		{`let r = ref [] in r := 1 :: !r; r := 2 :: !r; !r`, "[2; 1]"},
		{`let rec go i acc = if i = 0 then acc else go (i - 1) (acc + i) in go 1000000 0`, "500000500000"}, // proper tail calls
		{`sum (range 0 100000)`, "4999950000"},
		{`length (map succ (range 0 200000))`, "200000"},
		{`let rec count n = match n with 0 -> 0 | _ -> 1 + count (n - 1) in count 50000`, "50000"},
	}
	for _, c := range cases {
		if got := value(t, c.src); got != c.want {
			t.Errorf("%q:\n  got  %s\n  want %s", c.src, got, c.want)
		}
	}
}

func TestStaticScopingAcrossRedefinition(t *testing.T) {
	// g captured the *first* f; redefining f later must not change g
	got := value(t, `let f x = x + 1
let g y = f y;;
let f x = x * 100;;
g 5`)
	if got != "6" {
		t.Errorf("late binding bug: got %s want 6", got)
	}
	got = value(t, `let x = 1;; let f () = x;; let x = 2;; f ()`)
	if got != "1" {
		t.Errorf("got %s", got)
	}
}

func TestOutputAndEffects(t *testing.T) {
	s, out := newSession(t)
	_, err := s.Run(`let () = print_string "a"; print_endline "b"; print_int 3; print_endline ""`, true)
	if err != nil {
		t.Fatal(err)
	}
	if out.String() != "ab\n3\n" {
		t.Errorf("output %q", out.String())
	}
}

func runtimeErr(t *testing.T, src string) string {
	t.Helper()
	s, _ := newSession(t)
	_, err := s.Run(src, true)
	if err == nil {
		t.Fatalf("expected a runtime error for %q", src)
	}
	d, ok := err.(*syntax.Diag)
	if !ok || d.Kind != "runtime" {
		t.Fatalf("expected a runtime diag for %q, got %v", src, err)
	}
	return d.Msg
}

func TestRuntimeErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{`1 / 0`, "Division_by_zero"},
		{`1 mod 0`, "Division_by_zero"},
		{`failwith "boom"`, "Failure: boom"},
		{`string_sub "abc" 2 5`, "Invalid_argument"},
		{`char_code ""`, "Invalid_argument"},
		{`match Some 1 with None -> 0`, "Match_failure"},
		{`let (Some x) = None in x`, "Match_failure"},
		{`(fun (Some x) -> x) None`, "Match_failure"},
		{`let rec f n = 1 + f n in f 0`, "stack overflow"},
		{`(fun x -> x) = (fun x -> x)`, "functional values"},
		{`char_of_code (-1)`, "Invalid_argument"},
	}
	for _, c := range cases {
		if got := runtimeErr(t, c.src); !strings.Contains(got, c.want) {
			t.Errorf("%q: got %q want substring %q", c.src, got, c.want)
		}
	}
}

func TestFailedExecLeavesGlobalsIntact(t *testing.T) {
	s, _ := newSession(t)
	if _, err := s.Run(`let x = 1`, true); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Run(`let x = 1 / 0`, true); err == nil {
		t.Fatal("expected failure")
	}
	outs, err := s.Run(`x`, true)
	if err != nil {
		t.Fatal(err)
	}
	if got := outs[0].Format(); !strings.Contains(got, "= 1") {
		t.Errorf("x changed after failed redefinition: %s", got)
	}
}

func TestStepLimit(t *testing.T) {
	s, _ := newSession(t)
	s.Interp.M.MaxSteps = 10000
	_, err := s.Run(`let rec spin n = spin (n + 1) in spin 0`, true)
	if err == nil || !strings.Contains(err.Error(), "step limit") {
		t.Fatalf("got %v", err)
	}
}
