package sable

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// bigProgram builds one long function: many live variables, many loops/branches.
func bigProgram(stmts int) string {
	var sb strings.Builder
	sb.WriteString("func main() {\n")
	for i := 0; i < 60; i++ {
		fmt.Fprintf(&sb, "  var a%d = %d;\n", i, i*7+1)
	}
	sb.WriteString("  var s = 0;\n")
	x := uint32(12345)
	rnd := func(n int) int { x = x*1664525 + 1013904223; return int(x>>8) % n }
	for k := 0; k < stmts; k++ {
		a, b, c := rnd(60), rnd(60), rnd(60)
		switch rnd(6) {
		case 0:
			fmt.Fprintf(&sb, "  a%d = a%d + a%d * %d;\n", a, b, c, k%9+1)
		case 1:
			fmt.Fprintf(&sb, "  if a%d > a%d { a%d = a%d ^ a%d; } else { a%d = a%d + 1; }\n", a, b, c, c, a, c, c)
		case 2:
			fmt.Fprintf(&sb, "  for var i%d = 0; i%d < 3; i%d = i%d + 1 { a%d = a%d + a%d - i%d; }\n", k, k, k, k, a, a, b, k)
		case 3:
			fmt.Fprintf(&sb, "  s = s + (a%d & 255);\n", a)
		case 4:
			fmt.Fprintf(&sb, "  a%d = (a%d | 1) %% 1000 + a%d;\n", a, b, c)
		default:
			fmt.Fprintf(&sb, "  a%d = a%d << 3 >> 2;\n", a, b)
		}
	}
	sb.WriteString("  print(s); return s;\n}\n")
	return sb.String()
}

// Regression: LICM used to recompute loops per loop and walk the dominator
// chain per query — 41 s for ~1500 statements. Everything must stay near-linear.
func TestCompileScales(t *testing.T) {
	src := bigProgram(1500)
	for _, alg := range []Alg{LinearScan, GraphColor} {
		start := time.Now()
		c, err := Compile(src, Config{OptLevel: 2, Regs: 8, Alg: alg})
		if err != nil {
			t.Fatal(err)
		}
		el := time.Since(start)
		t.Logf("%v: compiled 1500-statement function in %v", alg, el)
		if el > 8*time.Second {
			t.Errorf("%v: compile took %v", alg, el)
		}
		want := RunAST(c.AST, 1e9)
		got, _ := RunProgram(c.Prog, 1e9)
		if !got.Same(want) {
			t.Errorf("%v: %v vs %v", alg, got, want)
		}
	}
}

func TestCheckEndlessLoopReturnsQuickly(t *testing.T) {
	start := time.Now()
	res, err := CheckAll(`func main() { while 1 { } return 0; }`)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(start) > 3*time.Second {
		t.Errorf("check took %v", time.Since(start))
	}
	for _, r := range res.Rows {
		if r.Skipped == "" {
			t.Errorf("%s was not skipped", r.Name)
		}
	}
}
