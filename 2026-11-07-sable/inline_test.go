package sable

import (
	"strings"
	"testing"
)

func optimized(t *testing.T, src string, noInline bool) *Module {
	t.Helper()
	p, err := Parse(src)
	if err != nil {
		t.Fatal(err)
	}
	m := Lower(p)
	if err := BuildSSA(m); err != nil {
		t.Fatal(err)
	}
	if _, err := Optimize(m, Options{Level: 2, Verify: true, NoInline: noInline}); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestInlineRemovesCallsAndFunctions(t *testing.T) {
	src := `func sq(x) { return x * x; }
func cube(x) { return sq(x) * x; }
func clamp(x, lo, hi) { if x < lo { return lo; } if x > hi { return hi; } return x; }
func main() { var s = 0; for var i = 0; i < 20; i = i + 1 { s = s + clamp(cube(i), 5, 3000); } print(s); return s; }`
	m := optimized(t, src, false)
	if len(m.Funcs) != 1 {
		t.Fatalf("expected only main to survive, got %d funcs:\n%s", len(m.Funcs), m)
	}
	for _, b := range m.Funcs[0].Blocks {
		for _, v := range b.Instrs {
			if v.Op == OpCall {
				t.Fatalf("call survived inlining:\n%s", m)
			}
		}
	}
	p, _ := Parse(src)
	want := RunAST(p, 1e7)
	if got := RunIR(m, 1e8); !got.Same(want) {
		t.Fatalf("got %v want %v", got, want)
	}
	// without inlining the functions stay
	if m2 := optimized(t, src, true); len(m2.Funcs) != 4 {
		t.Fatalf("-noinline must keep all 4 functions, got %d", len(m2.Funcs))
	}
}

func TestInlineRecursionNeverInlined(t *testing.T) {
	src := `func fact(n) { if n <= 1 { return 1; } return n * fact(n - 1); }
func even(n) { if n == 0 { return 1; } return odd(n - 1); }
func odd(n) { if n == 0 { return 0; } return even(n - 1); }
func main() { return fact(10) + even(10); }`
	m := optimized(t, src, false)
	names := []string{}
	for _, f := range m.Funcs {
		names = append(names, f.Name)
	}
	if got := strings.Join(names, ","); got != "fact,even,odd,main" {
		t.Fatalf("recursive functions must be kept: %s", got)
	}
	res, err := CheckAll(src)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range res.Rows {
		if !r.Match {
			t.Errorf("%s: %v", r.Name, r.Outcome)
		}
	}
}

func TestInlineShapes(t *testing.T) {
	progs := map[string]string{
		"multi-return":           `func sign(x) { if x < 0 { return -1; } if x == 0 { return 0; } return 1; } func main() { var s = 0; for var i = -3; i <= 3; i = i + 1 { s = s * 3 + sign(i); } return s; }`,
		"callee-loop":            `func sum(n) { var s = 0; for var i = 1; i <= n; i = i + 1 { s = s + i; } return s; } func main() { return sum(10) + sum(20); }`,
		"args-evaluated-once":    `func p(x) { print(x); return x; } func twice(a) { return a + a; } func main() { return twice(p(21)); }`,
		"noreturn-callee":        `func spin() { while 1 { } return 1; } func main() { print(1); if 0 { spin(); } print(2); return 3; }`,
		"callee-traps":           `func bad(x) { return 10 / x; } func main() { print(1); var r = bad(0); print(2); return r; }`,
		"call-in-phi":            `func f(x) { return x + 1; } func main() { var a = 0; if f(1) > 1 { a = f(10); } else { a = f(20); } return a + f(a); }`,
		"callee-params-modified": `func f(a, b) { a = a + b; b = a * 2; return a + b; } func main() { var x = 3; var y = 4; var r = f(x, y); return r * 1000 + x * 10 + y; }`,
		"chain-3-deep":           `func a(x) { return x + 1; } func b(x) { return a(x) * 2; } func c(x) { return b(x) - a(x); } func main() { return c(5) + c(c(1)); }`,
		"unused-result":          `func f(x) { print(x); return x; } func main() { f(1); f(2); return 0; }`,
	}
	for name, src := range progs {
		res, err := CheckAll(src)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		for _, r := range res.Rows {
			if r.Skipped == "" && !r.Match {
				t.Errorf("%s / %s: %v vs oracle %v", name, r.Name, r.Outcome, res.Oracle)
			}
		}
	}
}
