package ir

import (
	"strings"
	"testing"
)

func mustParse(t *testing.T, s string) *Module {
	t.Helper()
	m, err := Parse(s)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return m
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"func @f() {\nentry:\n  ret 0\n":                                     "unterminated function",
		"func @f() {\nentry:\n  %x = add 1\n  ret %x\n}":                     "takes 2 operands",
		"func @f() {\nentry:\n  ret %nope\n}":                                "undefined value",
		"func @f() {\nentry:\n  br nowhere\n}":                               "unknown block",
		"func @f() {\nentry:\n  %x = add 1, 2\n  %x = add 1, 2\n  ret %x\n}": "redefinition",
		"func @f() {\nentry:\n  %x = bogus 1, 2\n  ret %x\n}":                "unknown opcode",
		"func @f() {\nentry:\n  print 1\n}":                                  "no terminator",
		"func @f() {\nentry:\n  ret 0\n  print 1\n}":                         "after terminator",
		"func @f() {\nentry:\n  %x = alloca 0\n  ret 0\n}":                   "bad alloca size",
		"func @f() {\n}": "no blocks",
		"func @f() {\na:\n  ret 0\na:\n  ret 1\n}":                            "duplicate block",
		"func @f() {\na:\n  br b\nb:\n  %p = phi [1, a], [2, c]\n  ret %p\n}": "entries",
		"nonsense": "expected 'func",
		"func @f() {\na:\n  ret 0\n}\nfunc @f() {\na:\n  ret 0\n}": "duplicate function",
		"func @f() {\na:\n  %x = store 1, 2, 3\n  ret 0\n}":        "must not have a destination",
		"func @f() {\na:\n  ret 1.5\n}":                            "bad operand",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: got %v, want error containing %q", src, err, want)
		}
	}
}

func TestVerifierRejects(t *testing.T) {
	cases := map[string]string{
		// use before def in one block
		"func @f() {\nentry:\n  %b = add %a, 1\n  %a = add 1, 1\n  ret %b\n}": "before its definition",
		// def does not dominate use
		"func @f(%c) {\nentry:\n  condbr %c, l, r\nl:\n  %x = add 1, 1\n  br j\nr:\n  br j\nj:\n  ret %x\n}": "does not dominate",
		// alloca escapes as a value
		"func @f() {\nentry:\n  %a = alloca 1\n  %b = add %a, 1\n  ret %b\n}": "slots may only be load/store",
		"func @f() {\nentry:\n  %a = alloca 1\n  ret %a\n}":                   "terminator operand",
		// both targets identical
		"func @f(%c) {\nentry:\n  condbr %c, x, x\nx:\n  ret 0\n}": "identical targets",
		// call arity
		"func @g(%a) {\nentry:\n  ret %a\n}\nfunc @f() {\nentry:\n  %r = call @g(1, 2)\n  ret %r\n}": "want 1",
		"func @f() {\nentry:\n  %r = call @missing()\n  ret %r\n}":                                   "undefined function",
		// entry with predecessor
		"func @f() {\nentry:\n  br entry\n}": "predecessors",
		// alloca outside entry
		"func @f() {\nentry:\n  br b\nb:\n  %a = alloca 1\n  ret 0\n}": "alloca must be in entry",
	}
	for src, want := range cases {
		m, err := Parse(src)
		if err != nil {
			t.Errorf("%q: parse failed: %v", src, err)
			continue
		}
		err = m.Verify()
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: verify = %v, want error containing %q", src, err, want)
		}
	}
}

func TestPrintParseRoundTrip(t *testing.T) {
	src := `func @f(%x) {
entry:
  %c = lt %x, 10
  condbr %c, a, b
a:
  %s = select %c, 1, 2
  br j
b:
  br j
j:
  %p = phi [%s, a], [7, b]
  ret %p
}
`
	m := mustParse(t, src)
	if err := m.Verify(); err != nil {
		t.Fatal(err)
	}
	m2 := mustParse(t, m.String())
	if m.String() != m2.String() {
		t.Fatalf("print/parse not a fixed point:\n%s\n---\n%s", m, m2)
	}
}

// A graph with a known dominator tree (the example from Cooper-Harvey-Kennedy, fig. 4).
func TestDominatorsClassicGraph(t *testing.T) {
	src := `func @f(%c) {
b6:
  condbr %c, b5, b4
b5:
  br b1
b4:
  br b2
b1:
  br b2
b2:
  condbr %c, b1, b3
b3:
  condbr %c, b2, b7
b7:
  ret 0
}
`
	m := mustParse(t, src)
	if err := m.Verify(); err != nil {
		t.Fatal(err)
	}
	f := m.Funcs[0]
	d := ComputeDom(f)
	byName := map[string]*Block{}
	for _, b := range f.Blocks {
		byName[b.Name] = b
	}
	want := map[string]string{"b5": "b6", "b4": "b6", "b1": "b6", "b2": "b6", "b3": "b2", "b7": "b3"}
	for n, idom := range want {
		if got := d.Idom[byName[n]].Name; got != idom {
			t.Errorf("idom(%s) = %s, want %s", n, got, idom)
		}
	}
	if !d.Dominates(byName["b6"], byName["b7"]) || d.Dominates(byName["b1"], byName["b2"]) || !d.Dominates(byName["b2"], byName["b7"]) {
		t.Error("Dominates() disagrees with the idom tree")
	}
	// dominance frontiers: DF(b1)={b2}, DF(b2)={b1,b2}, DF(b3)={b2}, DF(b4)={b2}, DF(b5)={b1}
	df := d.Frontiers()
	names := func(bs []*Block) string {
		var s []string
		for _, b := range bs {
			s = append(s, b.Name)
		}
		return strings.Join(sorted(s), ",")
	}
	for n, w := range map[string]string{"b1": "b2", "b2": "b1,b2", "b3": "b2", "b4": "b2", "b5": "b1"} {
		if got := names(df[byName[n]]); got != w {
			t.Errorf("DF(%s) = {%s}, want {%s}", n, got, w)
		}
	}
}

func sorted(s []string) []string {
	for i := range s {
		for j := i + 1; j < len(s); j++ {
			if s[j] < s[i] {
				s[i], s[j] = s[j], s[i]
			}
		}
	}
	return s
}

func TestInterpreterTraps(t *testing.T) {
	for src, want := range map[string]string{
		"func @main() {\ne:\n  %q = div 1, 0\n  ret %q\n}":                    TrapDivZero,
		"func @main() {\ne:\n  %a = alloca 2\n  %v = load %a, 2\n  ret %v\n}": TrapOOB,
		"func @main() {\ne:\n  %a = alloca 2\n  store %a, -1, 5\n  ret 0\n}":  TrapOOB,
		"func @main() {\ne:\n  br e2\ne2:\n  br e2\n}":                        TrapFuel,
		"func @main() {\ne:\n  %r = call @main()\n  ret %r\n}":                TrapStack,
	} {
		m := mustParse(t, src)
		if err := m.Verify(); err != nil {
			t.Fatal(err)
		}
		if r := m.Run(10000); r.Trap != want {
			t.Errorf("%q: trap %q, want %q", src, r.Trap, want)
		}
	}
}

func TestEvalSemantics(t *testing.T) {
	const min = -1 << 63
	type c struct {
		op      Op
		x, y, z int64
		want    int64
		ok      bool
	}
	for _, k := range []c{
		{OpDiv, min, -1, 0, min, true}, {OpRem, min, -1, 0, 0, true}, {OpDiv, -7, 2, 0, -3, true}, {OpRem, -7, 2, 0, -1, true},
		{OpDiv, 1, 0, 0, 0, false}, {OpRem, 1, 0, 0, 0, false},
		{OpShl, 1, 64, 0, 1, true}, {OpShl, 1, -1, 0, min, true}, {OpShr, -8, 1, 0, -4, true}, {OpShr, -1, 200, 0, -1, true},
		{OpSelect, 0, 5, 6, 6, true}, {OpSelect, 9, 5, 6, 5, true}, {OpNeg, min, 0, 0, min, true}, {OpNot, 0, 0, 0, -1, true},
		{OpLt, -1, 0, 0, 1, true}, {OpGe, 3, 3, 0, 1, true}, {OpMul, 1 << 62, 4, 0, 0, true},
	} {
		got, ok := Eval(k.op, k.x, k.y, k.z)
		if ok != k.ok || (ok && got != k.want) {
			t.Errorf("Eval(%s,%d,%d,%d) = %d,%v want %d,%v", k.op, k.x, k.y, k.z, got, ok, k.want, k.ok)
		}
	}
}
