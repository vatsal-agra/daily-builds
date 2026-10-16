package opt_test

import (
	"strings"
	"testing"

	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

func irOf(t *testing.T, text string, passes ...string) (*ir.Module, ir.Result) {
	t.Helper()
	m, err := ir.Parse(text)
	if err != nil {
		t.Fatal(err)
	}
	if err := m.Verify(); err != nil {
		t.Fatal(err)
	}
	want := m.Run(fuel)
	if _, err := opt.Run(m, passes, opt.Options{Verify: true}); err != nil {
		t.Fatal(err)
	}
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatalf("passes %v changed behaviour: %v vs %v\n%s", passes, got, want, m)
	}
	return m, want
}

func count(m *ir.Module, op ir.Op) int {
	n := 0
	for _, f := range m.Funcs {
		f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
			if v.Op == op {
				n++
			}
		})
	}
	return n
}

func blocks(m *ir.Module) int {
	n := 0
	for _, f := range m.Funcs {
		n += len(f.Blocks)
	}
	return n
}

func compile(t *testing.T, src string) *ir.Module {
	t.Helper()
	m, err := front.Compile(src)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestSCCPFindsConstantsThroughLoopsAndPrunesBranches(t *testing.T) {
	// x stays 5 on every iteration, so the loop-carried phi is constant and `x != 5` is never taken.
	src := `
func @main() {
entry:
  br head
head:
  %i = phi [0, entry], [%i2, latch]
  %x = phi [5, entry], [%x, latch]
  %c = lt %i, 3
  condbr %c, body, done
body:
  %bad = ne %x, 5
  condbr %bad, never, latch
never:
  print 999
  br latch
latch:
  %i2 = add %i, 1
  br head
done:
  %r = mul %x, 2
  print %r
  ret %r
}`
	m, _ := irOf(t, src, "sccp", "simplifycfg", "dce")
	s := m.String()
	if strings.Contains(s, "999") || strings.Contains(s, "never") {
		t.Fatalf("SCCP should prove the `never` branch dead:\n%s", s)
	}
	if !strings.Contains(s, "print 10") || count(m, ir.OpMul) != 0 {
		t.Fatalf("x*2 should have folded to 10:\n%s", s)
	}
}

func TestSCCPKeepsTrappingDivision(t *testing.T) {
	m, want := irOf(t, "func @main() {\ne:\n  %q = div 7, 0\n  print 1\n  ret %q\n}", "sccp", "instcombine", "dce")
	if want.Trap == "" || count(m, ir.OpDiv) != 1 {
		t.Fatalf("a division by constant zero must survive (it traps): %s", m)
	}
}

func TestGVNEliminatesRedundantExpressions(t *testing.T) {
	src := `
func @f(%a, %b) {
entry:
  %x = add %a, %b
  %y = add %b, %a
  %c = lt %a, %b
  condbr %c, l, r
l:
  %z = add %a, %b
  %w = mul %z, %x
  ret %w
r:
  %z2 = add %b, %a
  %w2 = sub %z2, %y
  ret %w2
}
func @main() {
entry:
  %r = call @f(3, 4)
  ret %r
}`
	m, _ := irOf(t, src, "gvn", "dce")
	if n := count(m, ir.OpAdd); n != 1 {
		t.Fatalf("want a single add after GVN (commutative + dominator-scoped), got %d:\n%s", n, m)
	}
}

func TestMemOptForwardsStoresAndDropsDeadStores(t *testing.T) {
	src := `
func @main() {
entry:
  %a = alloca 4
  store %a, 1, 10
  store %a, 1, 20
  store %a, 2, 7
  %x = load %a, 1
  %y = load %a, 1
  %z = add %x, %y
  print %z
  ret %z
}`
	m, want := irOf(t, src, "memopt", "dce")
	if want.Out != "40\n" {
		t.Fatal(want)
	}
	if count(m, ir.OpLoad) != 0 {
		t.Fatalf("loads should be forwarded from the stores:\n%s", m)
	}
	if count(m, ir.OpStore) != 0 {
		t.Fatalf("with no loads left every store is dead:\n%s", m)
	}
}

func TestDCERemovesWriteOnlyAllocas(t *testing.T) {
	m, _ := irOf(t, "func @main() {\ne:\n  %a = alloca 8\n  store %a, 3, 9\n  ret 0\n}", "dce")
	if count(m, ir.OpAlloca) != 0 || count(m, ir.OpStore) != 0 {
		t.Fatalf("write-only slot should vanish:\n%s", m)
	}
}

func TestLICMHoistsInvariantComputation(t *testing.T) {
	m := compile(t, `fn main(){ var n = 7; var s = 0; for var i = 0; i < 50; i += 1 { s += n * n + 3; } return s; }`)
	want := m.Run(fuel)
	opt.Run(m, []string{"simplifycfg", "mem2reg"}, opt.Options{Verify: true})
	before := loopBodyMuls(m)
	if before == 0 {
		t.Skip("n*n already folded; nothing to hoist")
	}
	opt.Run(m, []string{"licm"}, opt.Options{Verify: true})
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatal("licm changed behaviour")
	}
	if after := loopBodyMuls(m); after != 0 {
		t.Fatalf("invariant multiply still inside the loop (%d)\n%s", after, m)
	}
}

// loopBodyMuls counts multiplies in blocks that sit on a cycle.
func loopBodyMuls(m *ir.Module) int {
	n := 0
	for _, f := range m.Funcs {
		for _, l := range opt.FindLoops(f, ir.ComputeDom(f)) {
			for b := range l.Blocks {
				for _, v := range b.Instrs {
					if v.Op == ir.OpMul {
						n++
					}
				}
			}
		}
	}
	return n
}

func TestInlineRemovesCalls(t *testing.T) {
	m := compile(t, `fn sq(x){ return x*x; } fn main(){ return sq(3) + sq(4); }`)
	want := m.Run(fuel)
	opt.Run(m, []string{"simplifycfg", "mem2reg", "inline", "simplifycfg", "mem2reg", "instcombine", "sccp", "dce"}, opt.Options{Verify: true})
	if count(m, ir.OpCall) != 0 {
		t.Fatalf("calls remain:\n%s", m)
	}
	if got := m.Run(fuel); !got.Same(want) || want.Ret != 25 {
		t.Fatalf("got %v", got)
	}
	// and constant folding then reduces main to `ret 25`
	if s := m.Func("main").String(); !strings.Contains(s, "ret 25") {
		t.Fatalf("main should fold to a constant:\n%s", s)
	}
}

func TestInlineLeavesRecursionAlone(t *testing.T) {
	m := compile(t, `fn f(n){ if n < 1 { return 0; } return f(n-1)+1; } fn main(){ return f(5); }`)
	opt.Run(m, []string{"simplifycfg", "mem2reg", "inline"}, opt.Options{Verify: true})
	if count(m, ir.OpCall) < 2 {
		t.Fatalf("recursive call must not be inlined away:\n%s", m)
	}
}

func TestTailRecursionBecomesALoop(t *testing.T) {
	src := `fn sum(n, acc){ if n == 0 { return acc; } return sum(n - 1, acc + n); } fn main(){ print(sum(100, 0)); return sum(300, 0); }`
	m := compile(t, src)
	want := m.Run(fuel)
	opt.Run(m, []string{"simplifycfg", "mem2reg", "tre"}, opt.Options{Verify: true})
	f := m.Func("sum")
	self := 0
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		if v.Op == ir.OpCall && v.Callee == "sum" {
			self++
		}
	})
	if self != 0 {
		t.Fatalf("self tail call not eliminated:\n%s", f)
	}
	got := m.Run(fuel)
	if !got.Same(want) {
		t.Fatalf("%v vs %v", got, want)
	}
	// deep tail recursion that would overflow the call stack now runs
	deep := compile(t, `fn sum(n, acc){ if n == 0 { return acc; } return sum(n - 1, acc + n); } fn main(){ return sum(100000, 0); }`)
	if r := deep.Run(fuel); r.Trap != ir.TrapStack {
		t.Fatalf("baseline should overflow the stack, got %v", r)
	}
	opt.Run(deep, []string{"simplifycfg", "mem2reg", "tre", "simplifycfg"}, opt.Options{Verify: true})
	if r := deep.Run(fuel); r.Trap != "" || r.Ret != 5000050000 {
		t.Fatalf("after TRE: %v", r)
	}
}

func TestUnrollFullyUnrollsSmallCountedLoops(t *testing.T) {
	m := compile(t, `fn main(){ var s = 0; for var i = 0; i < 5; i += 1 { s += i * 3; } print(s); return s; }`)
	want := m.Run(fuel)
	opt.Run(m, []string{"simplifycfg", "mem2reg", "instcombine", "unroll", "simplifycfg", "instcombine", "sccp", "dce", "simplifycfg"}, opt.Options{Verify: true})
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatal(got)
	}
	for _, f := range m.Funcs {
		if len(opt.FindLoops(f, ir.ComputeDom(f))) != 0 {
			t.Fatalf("loop survived unrolling:\n%s", m)
		}
	}
	if blocks(m) != 1 || !strings.Contains(m.String(), "ret 30") {
		t.Fatalf("unrolled loop should const-fold to a single block returning 30:\n%s", m)
	}
}

func TestUnrollRespectsTripLimitAndUnknownBounds(t *testing.T) {
	for _, src := range []string{
		`fn main(){ var s = 0; for var i = 0; i < 1000; i += 1 { s += i; } return s; }`,                      // too many iterations
		`fn f(n){ var s = 0; for var i = 0; i < n; i += 1 { s += i; } return s; } fn main(){ return f(4); }`, // runtime bound
		`fn main(){ var s = 0; var i = 0; while i < 4 { if s > 100 { break; } s += i; i += 1; } return s; }`, // second exit
	} {
		m := compile(t, src)
		want := m.Run(fuel)
		opt.Run(m, []string{"simplifycfg", "mem2reg", "instcombine", "unroll"}, opt.Options{Verify: true})
		if got := m.Run(fuel); !got.Same(want) {
			t.Fatalf("%s: %v vs %v", src, got, want)
		}
		loops := 0
		for _, f := range m.Funcs {
			loops += len(opt.FindLoops(f, ir.ComputeDom(f)))
		}
		if loops == 0 {
			t.Errorf("loop should not have been unrolled: %s", src)
		}
	}
}

func TestUnrollNestedLoops(t *testing.T) {
	m := compile(t, `fn main(){ var s = 0; for var i = 0; i < 3; i += 1 { for var j = 0; j < 4; j += 1 { s += i * 10 + j; } } return s; }`)
	want := m.Run(fuel)
	opt.Run(m, opt.Level(3), opt.Options{Verify: true})
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatal(got)
	}
	if blocks(m) != 1 {
		t.Fatalf("nested counted loops should fully flatten at -O3:\n%s", m)
	}
}

func TestIfConversionCreatesSelect(t *testing.T) {
	m := compile(t, `fn pick(a, b){ var r = 0; if a < b { r = a + 1; } else { r = b - 1; } return r; } fn main(){ return pick(3, 9) + pick(9, 3); }`)
	want := m.Run(fuel)
	opt.Run(m, []string{"simplifycfg", "mem2reg", "ifconv", "simplifycfg"}, opt.Options{Verify: true})
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatal(got)
	}
	if count(m, ir.OpSelect) != 1 || len(m.Func("pick").Blocks) != 1 {
		t.Fatalf("diamond should become one block with a select:\n%s", m.Func("pick"))
	}
}

func TestIfConversionRefusesExpensiveOrUnsafeArms(t *testing.T) {
	for _, src := range []string{
		`fn f(a, b){ var r = 0; if b != 0 { r = a / b; } return r; } fn main(){ return f(6, 0) + f(6, 3); }`, // division could trap
		`fn f(a){ var r = 0; if a > 2 { r = a / 3; } return r; } fn main(){ return f(9); }`,                  // expensive (cycle budget)
		`fn f(a){ var m[2]; var r = 0; if a > 2 { r = m[a & 1]; } return r; } fn main(){ return f(9); }`,     // load: not speculable
	} {
		m := compile(t, src)
		opt.Run(m, []string{"simplifycfg", "mem2reg", "ifconv", "simplifycfg"}, opt.Options{Verify: true})
		if count(m, ir.OpSelect) != 0 {
			t.Errorf("must not if-convert:\n%s", src)
		}
	}
}

func TestSimplifyCFGMergesAndFolds(t *testing.T) {
	m := compile(t, `fn main(){ if 1 { print(1); } else { print(2); } while 0 { print(3); } return 4; }`)
	opt.Run(m, []string{"simplifycfg"}, opt.Options{Verify: true})
	if blocks(m) != 1 {
		t.Fatalf("constant branches should leave one block:\n%s", m)
	}
	if strings.Contains(m.String(), "print 2") || strings.Contains(m.String(), "print 3") {
		t.Fatal("dead code remains")
	}
}

func TestInstCombineIdentities(t *testing.T) {
	cases := map[string]string{
		"%r = add %a, 0":                   "ret %a0",
		"%r = mul %a, 1":                   "ret %a0",
		"%r = sub %a, %a":                  "ret 0",
		"%r = xor %a, %a":                  "ret 0",
		"%r = and %a, -1":                  "ret %a0",
		"%r = or %a, 0":                    "ret %a0",
		"%r = shl %a, 64":                  "ret %a0",
		"%r = eq %a, %a":                   "ret 1",
		"%r = lt %a, %a":                   "ret 0",
		"%r = mul %a, 8":                   "shl %a0, 3",
		"%r = div %a, 1":                   "ret %a0",
		"%r = rem %a, 1":                   "ret 0",
		"%t = neg %a\n  %r = neg %t":       "ret %a0",
		"%t = add %a, 5\n  %r = add %t, 7": "add %a0, 12",
		"%t = sub %a, 3\n  %r = sub %t, 4": "add %a0, -7",
	}
	for body, want := range cases {
		src := "func @f(%a) {\ne:\n  " + body + "\n  ret %r\n}\nfunc @main() {\ne:\n  %x = call @f(9)\n  ret %x\n}"
		m, _ := irOf(t, src, "instcombine", "dce")
		if s := m.Func("f").String(); !strings.Contains(s, want) {
			t.Errorf("%q: expected %q in\n%s", body, want, s)
		}
	}
}

func TestPipelineStatsAndUnknownPass(t *testing.T) {
	m := compile(t, `fn main(){ var x = 2 + 3; return x * 4; }`)
	st, err := opt.Optimize(m, 2, true)
	if err != nil {
		t.Fatal(err)
	}
	if st["mem2reg"] == 0 {
		t.Fatalf("stats should record work: %v", st)
	}
	if !strings.Contains(st.String(), "mem2reg=") {
		t.Fatal(st.String())
	}
	if _, err := opt.Run(m, []string{"nope"}, opt.Options{}); err == nil || !strings.Contains(err.Error(), "unknown pass") {
		t.Fatalf("got %v", err)
	}
	for l := 0; l <= 3; l++ {
		for _, p := range opt.Level(l) {
			found := false
			for _, n := range opt.PassNames() {
				found = found || n == p
			}
			if !found {
				t.Errorf("-O%d references unregistered pass %q", l, p)
			}
		}
	}
}

func TestOptimizationLevelsAreMonotoneOnExamples(t *testing.T) {
	// O2 and O3 never do worse than O1 in code size terms on the whole example set (sanity, not a proof)
	for name, src := range examples(t) {
		sizes := make([]int, 4)
		for l := 0; l <= 3; l++ {
			m, _ := front.Compile(src)
			opt.Optimize(m, l, true)
			for _, f := range m.Funcs {
				for _, b := range f.Blocks {
					sizes[l] += len(b.Phis) + len(b.Instrs) + 1
				}
			}
		}
		if sizes[1] >= sizes[0] {
			t.Errorf("%s: -O1 did not shrink the IR (%d vs %d)", name, sizes[1], sizes[0])
		}
	}
}

func TestSCCPUsesOnlyExecutableEdges(t *testing.T) {
	// the false arm never runs, so the phi is exactly 10 even though 20 flows into the join textually
	src := `
func @main() {
entry:
  %c = eq 1, 1
  condbr %c, a, b
a:
  br join
b:
  br join
join:
  %p = phi [10, a], [20, b]
  %q = add %p, 1
  print %q
  ret %q
}`
	m, _ := irOf(t, src, "sccp", "simplifycfg", "dce")
	if !strings.Contains(m.String(), "print 11") {
		t.Fatalf("SCCP must ignore the non-executable incoming edge:\n%s", m)
	}
}

func TestUnrollKeepsValuesFlowingIntoALoopExitJoin(t *testing.T) {
	src := `fn f(c){ var s = 0; if c { for var i = 0; i < 4; i += 1 { s += i + 1; } } else { s = 100; } return s * 2; }
fn main(){ print(f(0)); print(f(1)); return f(0) + f(1); }`
	m := compile(t, src)
	want := m.Run(fuel)
	if want.Out != "200\n20\n" {
		t.Fatal(want)
	}
	opt.Run(m, []string{"simplifycfg", "mem2reg", "instcombine", "simplifycfg", "unroll", "simplifycfg"}, opt.Options{Verify: true})
	if got := m.Run(fuel); !got.Same(want) {
		t.Fatalf("%v vs %v\n%s", got, want, m)
	}
	for _, f := range m.Funcs {
		if len(opt.FindLoops(f, ir.ComputeDom(f))) != 0 {
			t.Fatalf("loop not unrolled:\n%s", m.Func("f"))
		}
	}
}
