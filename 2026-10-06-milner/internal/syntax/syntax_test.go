package syntax

import (
	"strings"
	"testing"
)

func TestLexer(t *testing.T) {
	toks, d := Lex(`let x' = 12_000 (* a (* nested *) comment *) "a\n\"b" 'a :: _ _x ;; |> <> ->`)
	if d != nil {
		t.Fatal(d)
	}
	var got []string
	for _, tk := range toks {
		got = append(got, tk.Text)
	}
	want := []string{"let", "x'", "=", "12000", "a\n\"b", "'a", "::", "_", "_x", ";;", "|>", "<>", "->", ""}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Errorf("tokens\n got  %q\n want %q", got, want)
	}
}

func TestLexerErrors(t *testing.T) {
	for src, want := range map[string]string{
		`"abc`:                 "unterminated string",
		`(* never closed`:      "unterminated comment",
		`let x = #`:            "unexpected character",
		`"a\q"`:                "unknown escape",
		`99999999999999999999`: "out of range",
		"\"line\nbreak":        "unterminated string",
	} {
		_, d := Lex(src)
		if d == nil || !strings.Contains(d.Msg, want) {
			t.Errorf("%q: got %v, want %q", src, d, want)
		}
	}
}

func TestParsePrecedence(t *testing.T) {
	// render expressions fully parenthesised to check precedence/associativity
	cases := map[string]string{
		`1 + 2 * 3`:              "(+ 1 (* 2 3))",
		`1 - 2 - 3`:              "(- (- 1 2) 3)",
		`a :: b :: c`:            "(:: (a, (:: (b, c))))",
		`f x y`:                  "(f x y)",
		`f x + g y`:              "(+ (f x) (g y))",
		`a && b || c`:            "(|| (&& a b) c)",
		`a = b && c < d`:         "(&& (= a b) (< c d))",
		`x |> f |> g`:            "(g (f x))",
		`-1 + 2`:                 "(+ -1 2)",
		`- x * 2`:                "(* (~- x) 2)",
		`a ^ b ^ c`:              "(^ a (^ b c))",
		`r := 1, 2`:              "(:= r (1, 2))",
		`!r + 1`:                 "(+ (! r) 1)",
		`f !r`:                   "(f (! r))",
		`Some x`:                 "Some(x)",
		`[1; 2]`:                 "(:: (1, (:: (2, []))))",
		`(f : int -> int)`:       "(f : int -> int)",
		`if a then b else c; d`:  "(seq (if a b c) d)",
		`1 + if a then 2 else 3`: "(+ 1 (if a 2 3))",
	}
	for src, want := range cases {
		e, d := ParseExpr(src)
		if d != nil {
			t.Errorf("%q: %v", src, d)
			continue
		}
		if got := dump(e); got != want {
			t.Errorf("%q:\n got  %s\n want %s", src, got, want)
		}
	}
}

func dump(e Expr) string {
	switch x := e.(type) {
	case *EInt:
		return itoa(x.Val)
	case *EVar:
		return x.Name
	case *EStr:
		return `"` + x.Val + `"`
	case *EApp:
		// flatten
		var args []string
		var f Expr = x
		for {
			a, ok := f.(*EApp)
			if !ok {
				break
			}
			args = append([]string{dump(a.Arg)}, args...)
			f = a.Fn
		}
		return "(" + dump(f) + " " + strings.Join(args, " ") + ")"
	case *ECon:
		if x.Arg == nil {
			if x.Name == "[]" {
				return "[]"
			}
			return x.Name
		}
		if x.Name == "::" {
			return "(:: " + dump(x.Arg) + ")"
		}
		return x.Name + "(" + dump(x.Arg) + ")"
	case *ETuple:
		var ps []string
		for _, el := range x.Elems {
			ps = append(ps, dump(el))
		}
		return "(" + strings.Join(ps, ", ") + ")"
	case *EAnd:
		return "(&& " + dump(x.L) + " " + dump(x.R) + ")"
	case *EOr:
		return "(|| " + dump(x.L) + " " + dump(x.R) + ")"
	case *EIf:
		return "(if " + dump(x.Cond) + " " + dump(x.Then) + " " + dump(x.Else) + ")"
	case *ESeq:
		return "(seq " + dump(x.A) + " " + dump(x.B) + ")"
	case *EAnnot:
		return "(" + dump(x.E) + " : " + tyDump(x.Ty) + ")"
	}
	return "?"
}

func tyDump(t TyExpr) string {
	switch x := t.(type) {
	case *TyCon:
		return x.Name
	case *TyArrow:
		return tyDump(x.From) + " -> " + tyDump(x.To)
	}
	return "?"
}

func itoa(n int64) string {
	if n < 0 {
		return "-" + itoa(-n)
	}
	if n < 10 {
		return string(rune('0' + n))
	}
	return itoa(n/10) + string(rune('0'+n%10))
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		`let x = `:               "expected an expression",
		`let = 5`:                "expected",
		`if a then b else`:       "expected an expression",
		`match x with`:           "expected a pattern",
		`(1, 2`:                  "expected `)`",
		`[1; 2`:                  "expected `]`",
		`fun -> 1`:               "needs at least one parameter",
		`let rec (a, b) = 1`:     "`let rec` must bind a function name",
		`type t = `:              "expected a type",
		`type T = A`:             "lower-case type name",
		`1 + `:                   "expected an expression",
		`let f x = x in`:         "expected an expression",
		`match x with A -> 1 | `: "expected a pattern",
	}
	for src, want := range cases {
		_, d := ParseProgram(src)
		if d == nil || !strings.Contains(d.Msg, want) {
			t.Errorf("%q: got %v, want %q", src, d, want)
		}
	}
}

func TestParseDecls(t *testing.T) {
	ds, d := ParseProgram(`type 'a t = A | B of 'a * int
and u = U
let x = 1
let rec f n = f n and g n = g n
let y = 2 in y;;
3 + 4;;
let z = 5`)
	if d != nil {
		t.Fatal(d)
	}
	kinds := ""
	for _, dc := range ds {
		switch dc.(type) {
		case *DType:
			kinds += "T"
		case *DLet:
			kinds += "L"
		case *DExpr:
			kinds += "E"
		}
	}
	if kinds != "TLLEEL" {
		t.Errorf("decl kinds %s", kinds)
	}
}

func TestDiagRender(t *testing.T) {
	src := "let x = 1\nlet y = oops\n"
	d := &Diag{Kind: "type", Msg: "unbound variable `oops`", Label: "not found",
		Span: Span{Pos{18, 2, 9}, Pos{22, 2, 13}}, Notes: []string{"did you mean `x`?"}}
	out := d.Render(src, "f.ml")
	for _, want := range []string{"error[type]: unbound variable", "--> f.ml:2:9", "2 | let y = oops", "^^^^ not found", "= did you mean"} {
		if !strings.Contains(out, want) {
			t.Errorf("render lacks %q:\n%s", want, out)
		}
	}
}

func TestLayoutRule(t *testing.T) {
	count := func(src string) int {
		ds, d := ParseProgram(src)
		if d != nil {
			t.Fatalf("%q: %v", src, d)
		}
		return len(ds)
	}
	cases := []struct {
		src  string
		want int
	}{
		{"let f x = x\nf 1", 2},                                      // new line at column 1 starts a declaration
		{"let f x = x\n  + 1\nlet y = f 2", 2},                       // indented continuation stays in the declaration
		{"let f x = match x with\n| 1 -> 2\n| _ -> 3\nlet g = 1", 2}, // `|` at column 1 continues the match
		{"let a = 1 in\nlet b = 2 in\na + b", 1},                     // `in` demands a continuation
		{"let f = fun x ->\nx + 1\nlet g = 2", 2},                    // `->` demands a continuation
		{"print_int 1\nprint_int 2", 2},
		{"let x = [1;\n2]\nx", 2},
		{"let x = 1 +\n2", 1},
		{"let x = f\n(1)", 2}, // documented: an expression starting at column 1 is a new declaration
	}
	for _, c := range cases {
		if got := count(c.src); got != c.want {
			t.Errorf("%q: %d declarations, want %d", c.src, got, c.want)
		}
	}
}

func TestRenderColor(t *testing.T) {
	d := &Diag{Kind: "type", Msg: "boom", Label: "here", Span: Span{Pos{0, 1, 1}, Pos{3, 1, 4}}}
	plain := d.Render("abc", "f")
	if strings.Contains(plain, "\x1b[") {
		t.Errorf("plain rendering must not contain escapes: %q", plain)
	}
	col := d.RenderColor("abc", "f", true)
	if !strings.Contains(col, "\x1b[1;31m") {
		t.Errorf("errors should be red: %q", col)
	}
	d.Warn = true
	if w := d.RenderColor("abc", "f", true); !strings.Contains(w, "\x1b[1;33m") || strings.Contains(w, "\x1b[1;31m") {
		t.Errorf("warnings should be yellow: %q", w)
	}
	// stripping the escapes gives exactly the plain rendering
	strip := func(s string) string {
		var b strings.Builder
		for i := 0; i < len(s); i++ {
			if s[i] == 0x1b {
				for i < len(s) && s[i] != 'm' {
					i++
				}
				continue
			}
			b.WriteByte(s[i])
		}
		return b.String()
	}
	if strip(d.RenderColor("abc", "f", true)) != d.Render("abc", "f") {
		t.Error("colour rendering differs from plain rendering beyond escapes")
	}
}

func TestParseRecordsAndTypes(t *testing.T) {
	good := []string{
		`{ x = 1; y = 2 }`, `{ x; y }`, `{ r with x = 1 }`, `{ r with x; y = 2; }`, `{ (f r) with x = 1 }`,
		`r.x.y`, `f r.x`, `{ a = { b = 1 } }.a.b`, `fun { a; b = (c, d) } -> a`, `fun ({ a } : { a : int; .. }) -> a`,
		`match r with { a = 1; .. } -> 1 | { a; b = Some x } -> x`,
	}
	for _, src := range good {
		if _, d := ParseExpr(src); d != nil {
			t.Errorf("%q: %v", src, d)
		}
	}
	if _, d := ParseProgram(`type p = { x : int; y : string }
type 'a box = { v : 'a; .. } list
type ('a, 'b) pair = 'a * 'b`); d != nil {
		t.Errorf("record/alias types: %v", d)
	}
	bad := map[string]string{
		`{ x = 1; 2 }`:      "field name",
		`{ r with }`:        "at least one",
		`{ }`:               "at least one field",
		`r.`:                "field name after `.`",
		`r.1`:               "field name after `.`",
		`fun { } -> 1`:      "at least one field",
		`fun { 3 } -> 1`:    "field name",
		`(1 : { x : })`:     "expected a type",
		`(1 : { 3 : int })`: "field name",
	}
	for src, want := range bad {
		_, d := ParseExpr(src)
		if d == nil || !strings.Contains(d.Msg, want) {
			t.Errorf("%q: got %v want %q", src, d, want)
		}
	}
}

func TestEndOfInputErrorAnchoredAfterLastToken(t *testing.T) {
	_, d := ParseProgram("let x = 5 +\n\n\n")
	if d == nil || d.Span.Start.Line != 1 || d.Span.Start.Col != 12 {
		t.Fatalf("got %v", d)
	}
	out := d.Render("let x = 5 +\n\n\n", "f")
	if strings.Contains(out, "2 |") || strings.Contains(out, "4 |") {
		t.Errorf("rendering should not show the blank trailing lines:\n%s", out)
	}
}
