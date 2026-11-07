package sable

import (
	"strings"
	"testing"
)

// Hostile programs found while attacking the compiler (see REVIEW.md).
var edgePrograms = map[string]string{
	"minint-div":          `func main() { var m = -9223372036854775807 - 1; print(m / -1); print(m % -1); print(m * -1); print(-m); var d = -1; print(m / d); print(m % d); return 0; }`,
	"shift-counts":        `func main() { var x = 1; var s = 64; print(x << s); print(x << 65); print(-1 >> 70); var n = -1; print(x << n); print(256 >> -60); return 0; }`,
	"empty-main":          `func main() { }`,
	"unreachable":         `func f(x) { return x; print(99); x = 5; while 1 { } } func main() { return f(3); }`,
	"break-continue-nest": `func main() { var c = 0; for var i = 0; i < 5; i = i + 1 { for var j = 0; j < 5; j = j + 1 { if j == 3 { break; } if (i + j) % 2 == 0 { continue; } c = c + 10 * i + j; } if i == 3 { continue; } c = c + 1000; } print(c); return c; }`,
	"eight-params":        `func f(a, b, c, d, e, f, g, h) { return a + 2*b + 3*c + 4*d + 5*e + 6*f + 7*g + 8*h; } func main() { return f(1,2,3,4,5,6,7,8) + f(8,7,6,5,4,3,2,1); }`,
	"swap-in-loop":        `func main() { var a = 1; var b = 2; for var i = 0; i < 5; i = i + 1 { var t = a; a = b; b = t + b; } print(a); print(b); return a - b; }`,
	"lost-copy":           `func main() { var x = 0; var y = 0; var i = 0; while i < 4 { y = x; x = i * 2; i = i + 1; } print(y); print(x); return y * 100 + x; }`,
	"pressure-across-calls": `func g(x) { print(x); return x + 1; }
func main() { var a = 1; var b = 2; var c = 3; var d = 4; var e = 5; var f = 6;
  for var i = 0; i < 3; i = i + 1 { a = g(a) + b; b = g(b) + c; c = g(c) + d; d = g(d) + e; e = g(e) + f; f = g(f) + a; }
  return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6; }`,
	"shadowing":               `func x() { return 7; } func main() { var x = 1; { var x = x + 1; print(x); { var x = x * 10; print(x); } print(x); } print(x); return x + x(); }`,
	"for-empty-clauses":       `func main() { var i = 0; for ; ; { i = i + 1; if i > 6 { break; } } for ; i < 10; { i = i + 1; } return i; }`,
	"param-modify":            `func f(n) { n = n * 2; if n > 10 { n = n - 3; } return n; } func main() { var n = 6; return f(n) + n; }`,
	"nested-calls-args":       `func add(a, b) { return a + b; } func main() { return add(add(1, 2), add(add(3, 4), add(5, add(6, 7)))); }`,
	"big-consts":              `func main() { var a = 9223372036854775807; var b = a + 1; print(b); print(a * a); print(0x7fffffffffffffff - 0xff); return b >> 62; }`,
	"deep-recursion":          `func f(n) { if n == 0 { return 0; } return 1 + f(n - 1); } func main() { return f(900); }`,
	"mutual-recursion":        `func even(n) { if n == 0 { return 1; } return odd(n - 1); } func odd(n) { if n == 0 { return 0; } return even(n - 1); } func main() { return even(50) * 10 + odd(7); }`,
	"div-zero-in-loop-unused": `func main() { var z = 0; var s = 0; for var i = 0; i < 3; i = i + 1 { s = s + i; var u = 5 / z; } return s; }`,
	"licm-no-hoist-div":       `func main() { var d = 0; var s = 0; var i = 0; while i < 3 { if d != 0 { s = s + 100 / d; } i = i + 1; } print(s); return s; }`,
	"phi-of-consts":           `func main() { var x = 0; var c = 3; if c > 2 { x = 1; } else { x = 2; } var y = x; if c < 2 { y = 5; } return x * 10 + y; }`,
	"not-bool":                `func main() { var a = 5; var b = !(a < 3); var c = !!a; var d = !(!(a < 3)); print(b); print(c); print(d); return b + c + d + (a == 0) + (a != 0); }`,
	"loop-exit-value":         `func main() { var i = 0; var last = 0; while i < 10 { last = i * i; i = i + 1; if last > 30 { break; } } print(i); return last; }`,
	"call-in-condition":       `func p(x) { print(x); return x; } func main() { var n = 0; while p(n) < 3 && n < 10 { n = n + 1; } return n; }`,
}

func TestEdgePrograms(t *testing.T) {
	for name, src := range edgePrograms {
		t.Run(name, func(t *testing.T) {
			res, err := CheckAll(src)
			if err != nil {
				t.Fatal(err)
			}
			for _, r := range res.Rows {
				if r.Skipped == "" && !r.Match {
					t.Errorf("%s: %v vs oracle %v", r.Name, r.Outcome, res.Oracle)
				}
			}
			if res.Oracle.Resource() {
				t.Errorf("oracle ended with %v", res.Oracle.Trap)
			}
		})
	}
}

func TestEdgeExpectedValues(t *testing.T) {
	want := map[string]string{
		"minint-div":        "[-9223372036854775808 0 -9223372036854775808 -9223372036854775808 -9223372036854775808 0] ret=0",
		"shift-counts":      "[1 2 -1 -9223372036854775808 16] ret=0",
		"empty-main":        "[] ret=0",
		"deep-recursion":    "[] ret=900",
		"mutual-recursion":  "[] ret=11",
		"nested-calls-args": "[] ret=28",
		"eight-params":      "[] ret=324",
	}
	for name, w := range want {
		p, err := Parse(edgePrograms[name])
		if err != nil {
			t.Fatal(err)
		}
		if got := RunAST(p, 1e7).String(); got != w {
			t.Errorf("%s: oracle says %s, want %s", name, got, w)
		}
	}
}

func TestParseErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{`func main() { return 1 }`, `expected ";"`},
		{`func main() { var x = ; }`, "expected expression"},
		{`func main() { x = 1; }`, `undefined variable "x"`},
		{`func main() { var x = 1; var x = 2; }`, "already declared"},
		{`func main() { return f(1); }`, `undefined function "f"`},
		{`func f(a) { return a; } func main() { return f(1, 2); }`, "takes 1 argument"},
		{`func f() {} `, "no 'main'"},
		{`func main(x) {}`, "no parameters"},
		{`func main() { break; }`, "outside a loop"},
		{`func main() { continue; }`, "outside a loop"},
		{`func main() { return 99999999999999999999; }`, "overflows"},
		{`func main() { return 9223372036854775808; }`, "overflows"},
		{`func main() { return 1 @ 2; }`, "unexpected character"},
		{`func main() { /* never closed`, "unterminated"},
		{`func main() { 1 + 2; }`, "must be a call"},
		{`func main() { if 1 { }`, "missing '}'"},
		{`func f() {} func f() {} func main() {}`, "declared twice"},
		{`func f(a, a) {} func main() {}`, "duplicate parameter"},
		{`func main() { var i = 0 }`, `expected ";"`},
		{`var x = 1;`, "expected 'func'"},
		{`func main() { return 0x; }`, "malformed hex"},
		{`func main() { return 12abc; }`, "malformed number"},
		{`func main() { for var i = 0; i < 3; var j = 1 { } }`, "cannot declare"},
		{"", "no 'main'"},
	}
	for _, c := range cases {
		_, err := Parse(c.src)
		if err == nil {
			t.Errorf("%q: expected error containing %q, got none", c.src, c.want)
			continue
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: error %q does not contain %q", c.src, err, c.want)
		}
	}
}

func TestStackOverflowAndFuel(t *testing.T) {
	p, _ := Parse(`func f(n) { return f(n + 1); } func main() { return f(0); }`)
	if o := RunAST(p, 1e9); o.Trap != TrapStack {
		t.Errorf("AST: %v", o)
	}
	c, err := CompileAST(p, Config{OptLevel: 2, Regs: 4, Alg: LinearScan})
	if err != nil {
		t.Fatal(err)
	}
	if o, _ := RunProgram(c.Prog, 1e9); o.Trap != TrapStack {
		t.Errorf("VM: %v", o)
	}
	p, _ = Parse(`func main() { while 1 { } return 0; }`)
	if o := RunAST(p, 10000); o.Trap != TrapFuel {
		t.Errorf("fuel: %v", o)
	}
	c, _ = CompileAST(p, Config{OptLevel: 2, Regs: 4, Alg: GraphColor})
	if o, _ := RunProgram(c.Prog, 10000); o.Trap != TrapFuel {
		t.Errorf("VM fuel: %v", o)
	}
}

// A true parallel-copy cycle: after SSA the loop's phis are phi(a)=b, phi(b)=a.
func TestPhiSwapCycle(t *testing.T) {
	src := `func main() { var a = 1; var b = 2; for var i = 0; i < 5; i = i + 1 { var t = a; a = b; b = t; } print(a); print(b); return a * 10 + b; }`
	res, err := CheckAll(src)
	if err != nil {
		t.Fatal(err)
	}
	if res.Oracle.String() != "[2 1] ret=21" {
		t.Fatalf("oracle: %v", res.Oracle)
	}
	for _, r := range res.Rows {
		if !r.Match {
			t.Errorf("%s: %v", r.Name, r.Outcome)
		}
	}
	// three-way rotation as well
	src = `func main() { var a = 1; var b = 2; var c = 3; for var i = 0; i < 4; i = i + 1 { var t = a; a = b; b = c; c = t; } return a * 100 + b * 10 + c; }`
	res, _ = CheckAll(src)
	for _, r := range res.Rows {
		if !r.Match {
			t.Errorf("rotate %s: %v vs %v", r.Name, r.Outcome, res.Oracle)
		}
	}
}

// Pruned SSA: a variable that is dead at the loop header must not get a phi there.
func TestPrunedPhis(t *testing.T) {
	p, _ := Parse(`func main() { var i = 0; while i < 10 { var t = i * 2; print(t); i = i + 1; } return i; }`)
	m := Lower(p)
	if err := BuildSSA(m); err != nil {
		t.Fatal(err)
	}
	phis := 0
	for _, b := range m.Funcs[0].Blocks {
		phis += b.NumPhis()
	}
	if phis != 1 {
		t.Errorf("expected exactly 1 phi (for i), got %d:\n%s", phis, m)
	}
}

// parallelCopy must implement simultaneous-assignment semantics.
func TestParallelCopySemantics(t *testing.T) {
	cases := [][]pcopy{
		{{0, VReg(1)}, {1, VReg(0)}},               // swap
		{{0, VReg(1)}, {1, VReg(2)}, {2, VReg(0)}}, // 3-cycle
		{{0, VReg(1)}, {1, VReg(0)}, {2, VReg(0)}}, // cycle + reader
		{{0, VReg(0)}, {1, Imm(7)}, {2, VReg(1)}},  // self copy, imm, chain
		{{1, VReg(0)}, {2, VReg(0)}, {0, VReg(2)}}, // fan-out into cycle
	}
	for ci, cs := range cases {
		s := &selector{mf: &MFunc{NVRegs: 3}, cur: &MBlock{}}
		s.parallelCopy(cs)
		regs := []int64{10, 20, 30, 0, 0, 0}
		orig := append([]int64(nil), regs...)
		for _, in := range s.cur.Instrs {
			switch in.Op {
			case MLi:
				regs[in.D.V] = in.A.V
			case MMov:
				regs[in.D.V] = regs[in.A.V]
			}
		}
		want := append([]int64(nil), orig...)
		for _, c := range cs {
			if c.src.K == OImm {
				want[c.dst] = c.src.V
			} else {
				want[c.dst] = orig[c.src.V]
			}
		}
		for r := 0; r < 3; r++ {
			if regs[r] != want[r] {
				t.Errorf("case %d: r%d = %d, want %d", ci, r, regs[r], want[r])
			}
		}
	}
}

// Pathological nesting must be a clean compile error, never a Go stack overflow.
func TestNestingLimits(t *testing.T) {
	n := 200000
	cases := map[string]string{
		"parens": "func main() { return " + strings.Repeat("(", n) + "1" + strings.Repeat(")", n) + "; }",
		"unary":  "func main() { return " + strings.Repeat("-", n) + "1; }",
		"blocks": "func main() { " + strings.Repeat("{", n) + strings.Repeat("}", n) + " }",
		"chain":  "func main() { return 1" + strings.Repeat("+1", n) + "; }",
		"calls":  "func f(x) { return x; } func main() { return " + strings.Repeat("f(", n) + "1" + strings.Repeat(")", n) + "; }",
		"elseif": "func main() { if 1 { } " + strings.Repeat("else if 1 { } ", 5000) + " }",
	}
	for name, src := range cases {
		_, err := Parse(src)
		if err == nil || !strings.Contains(err.Error(), "deep") {
			t.Errorf("%s: want a nesting error, got %v", name, err)
		}
	}
	// just under the limits still compiles and runs
	src := "func main() { return 1" + strings.Repeat("+1", 1500) + "; }"
	res, err := CheckAll(src)
	if err != nil || res.Oracle.Ret != 1501 {
		t.Fatalf("1500-term chain: %v %v", res, err)
	}
	for _, r := range res.Rows {
		if !r.Match {
			t.Errorf("%s: %v", r.Name, r.Outcome)
		}
	}
}
