package sp

import (
	"strings"
	"testing"
)

const loopSrc = `func f(1) {
e:
  n = arg 0
  a = const 1
  b = const 2
  c = const 3
  i = const 0
  jmp h
h:
  t = lt i, n
  br t, b1, d
b1:
  a = add a, b
  b = add b, c
  c = add c, a
  i = add i, 1
  jmp h
d:
  r = add a, b
  r = add r, c
  ret r
}`

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"func f(0) {\n}\n":                           "no blocks",
		"func f(0) {\ne:\n x = foo 1\n ret x\n}\n":   "unknown opcode",
		"func f(0) {\ne:\n x = add 1\n ret x\n}\n":   "takes 2",
		"func f(0) {\ne:\n jmp nowhere\n}\n":         "undefined label",
		"func f(0) {\ne:\n ret 1\ne:\n ret 2\n}\n":   "duplicate label",
		"func f(0) {\ne:\n x = const 1\n}\n":         "falls off",
		"func f(0) {\ne:\n ret 1\n x = const 2\n}\n": "after terminator",
		"x = const 1":                    "expected `func",
		"func f(0) {\n x = const 1\n}\n": "before first label",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: got %v, want substring %q", src, err, want)
		}
	}
	f, _ := Parse("func f(0) {\ne:\n x = add y, 1\n ret x\n}\n")
	if err := f.Validate(); err == nil || !strings.Contains(err.Error(), "undefined") {
		t.Errorf("undefined read not caught: %v", err)
	}
	f, _ = Parse("func f(0) {\ne:\n jmp e\n}\n")
	if err := f.Validate(); err == nil {
		t.Error("function with no reachable ret accepted")
	}
}

func TestRoundTripPrint(t *testing.T) {
	f := mustParse(t, loopSrc)
	g := mustParse(t, f.String())
	r1, _ := Run(f, []int64{6}, 10000)
	r2, _ := Run(g, []int64{6}, 10000)
	if err := Equivalent(r1, r2); err != nil {
		t.Fatal(err)
	}
}

func TestInterferenceKnownGraph(t *testing.T) {
	// a,b,c all live together; t interferes with all but only briefly.
	f := mustParse(t, `func f(0) {
e:
  a = const 1
  b = const 2
  c = const 3
  s = add a, b
  s = add s, c
  ret s
}`)
	edges := InterferenceEdges(f)
	has := func(x, y string) bool {
		for _, e := range edges {
			n1, n2 := f.RegName(e[0]), f.RegName(e[1])
			if (n1 == x && n2 == y) || (n1 == y && n2 == x) {
				return true
			}
		}
		return false
	}
	if !has("a", "b") || !has("a", "c") || !has("b", "c") {
		t.Errorf("missing a/b/c clique: %v", edges)
	}
	if has("a", "s") && has("b", "s") && has("c", "s") && len(edges) > 3 {
		// s overwrites a's value only after a dies; allowed edges: s-c only
		t.Errorf("s should not interfere with a/b: %v", edges)
	}
}

func TestGraphColouringUsesMinimumOnClique(t *testing.T) {
	f := mustParse(t, loopSrc) // a,b,c,i,n + the compare result t -> pressure 6
	a, err := Allocate(f, "color", 6, Options{Coalesce: true})
	if err != nil {
		t.Fatal(err)
	}
	if a.Static().SpillLoads != 0 || a.SpilledVars != 0 {
		t.Errorf("K=6 should fit without spills, got %+v", a.Static())
	}
	a, _ = Allocate(f, "color", 3, Options{Coalesce: true})
	if a.Static().SpillLoads == 0 {
		t.Error("K=3 must spill")
	}
	if _, err := Verify(f, a, [][]int64{{0}, {5}, {9}}); err != nil {
		t.Error(err)
	}
}

func TestCoalescingRemovesMoves(t *testing.T) {
	f := mustParse(t, `func f(1) {
e:
  n = arg 0
  a = mov n
  b = mov a
  c = mov b
  r = add c, 1
  ret r
}`)
	on, _ := Allocate(f, "color", 4, Options{Coalesce: true})
	if on.Static().Moves != 0 || on.Coalesced != 3 {
		t.Errorf("coalescing should remove all 3 moves, got %d left", on.Static().Moves)
	}
	if _, err := Verify(f, on, [][]int64{{41}}); err != nil {
		t.Error(err)
	}
	// moves with an interfering source cannot be coalesced
	g := mustParse(t, `func f(1) {
e:
  n = arg 0
  a = mov n
  n = add n, 1
  r = add a, n
  ret r
}`)
	al, _ := Allocate(g, "color", 4, Options{Coalesce: true})
	if _, err := Verify(g, al, [][]int64{{10}}); err != nil {
		t.Error(err)
	}
	if al.Static().Moves != 1 {
		t.Errorf("constrained move must stay, got %d", al.Static().Moves)
	}
}

func TestLinearScanSpillsFurthestEnd(t *testing.T) {
	f := mustParse(t, loopSrc)
	a, err := Allocate(f, "linear", 3, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Verify(f, a, [][]int64{{0}, {4}}); err != nil {
		t.Error(err)
	}
	if a.SpilledVars == 0 {
		t.Error("expected spills at K=3")
	}
}

func TestLoopDepthWeightsSpillChoice(t *testing.T) {
	// `cold` is used once outside the loop, `hot` every iteration: with K=4 the
	// allocator should spill cold, never hot.
	f := mustParse(t, `func f(1) {
e:
  n = arg 0
  cold = const 99
  hot = const 1
  x = const 2
  y = const 3
  i = const 0
  jmp h
h:
  t = lt i, n
  br t, b, d
b:
  hot = add hot, x
  x = add x, y
  y = add y, hot
  i = add i, 1
  jmp h
d:
  r = add hot, cold
  ret r
}`)
	a, err := Allocate(f, "color", 4, Options{Coalesce: true})
	if err != nil {
		t.Fatal(err)
	}
	var coldSpilled bool
	for _, b := range a.Rewritten.Blocks {
		for _, in := range b.Instrs {
			if in.Op == OpSpillSt && strings.HasPrefix(a.Rewritten.RegName(in.Args[1].Reg), "cold") {
				coldSpilled = true
			}
			if in.Op == OpSpillSt && strings.HasPrefix(a.Rewritten.RegName(in.Args[1].Reg), "hot") {
				t.Error("hot loop variable was spilled")
			}
		}
	}
	if !coldSpilled {
		t.Error("expected cold to be the spilled variable")
	}
	if _, err := Verify(f, a, [][]int64{{5}}); err != nil {
		t.Error(err)
	}
}

func TestPostPasses(t *testing.T) {
	f := mustParse(t, loopSrc)
	raw, _ := Allocate(f, "color", 3, Options{Coalesce: true, NoPost: true})
	opt, _ := Allocate(f, "color", 3, Options{Coalesce: true})
	rs, err := Verify(f, raw, [][]int64{{12}})
	if err != nil {
		t.Fatal(err)
	}
	os, err := Verify(f, opt, [][]int64{{12}})
	if err != nil {
		t.Fatal(err)
	}
	if os.Cycles > rs.Cycles || opt.Machine.Slots > raw.Machine.Slots {
		t.Errorf("post-pass made things worse: %d vs %d cycles, %d vs %d slots", os.Cycles, rs.Cycles, opt.Machine.Slots, raw.Machine.Slots)
	}
	// hand-built forwarding case
	m := &Function{NumRegs: 3, Slots: 1, Blocks: []*Block{{Name: "e", Instrs: []Instr{
		{Op: OpConst, Dst: 0, Args: []Operand{I(7)}},
		{Op: OpSpillSt, Dst: -1, Args: []Operand{I(0), R(0)}},
		{Op: OpSpillLd, Dst: 0, Args: []Operand{I(0)}},
		{Op: OpSpillLd, Dst: 1, Args: []Operand{I(0)}},
		{Op: OpRet, Dst: -1, Args: []Operand{R(1)}},
	}}}}
	m.buildEdges()
	al := &Allocation{Machine: m}
	ps := al.Optimize()
	if ps.LoadsDropped != 1 || ps.LoadsToMoves != 1 || ps.DeadStores != 1 || m.Slots != 0 {
		t.Errorf("forwarding: %+v slots=%d", ps, m.Slots)
	}
	r, _ := Run(m, nil, 100)
	if r.Ret != 7 {
		t.Errorf("forwarded code returns %d", r.Ret)
	}
}

func TestSlotSharing(t *testing.T) {
	// two spill slots with disjoint lifetimes must share one location
	m := &Function{NumRegs: 3, Slots: 2, Blocks: []*Block{{Name: "e", Instrs: []Instr{
		{Op: OpConst, Dst: 0, Args: []Operand{I(1)}},
		{Op: OpSpillSt, Dst: -1, Args: []Operand{I(0), R(0)}},
		{Op: OpConst, Dst: 0, Args: []Operand{I(5)}},
		{Op: OpSpillLd, Dst: 1, Args: []Operand{I(0)}},
		{Op: OpSpillSt, Dst: -1, Args: []Operand{I(1), R(0)}},
		{Op: OpSpillLd, Dst: 2, Args: []Operand{I(1)}},
		{Op: OpAdd, Dst: 2, Args: []Operand{R(1), R(2)}},
		{Op: OpRet, Dst: -1, Args: []Operand{R(2)}},
	}}}}
	m.buildEdges()
	compactSlots(m)
	if m.Slots != 1 {
		t.Errorf("slots=%d want 1", m.Slots)
	}
	if r, _ := Run(m, nil, 100); r.Ret != 6 {
		t.Errorf("ret=%d want 6", r.Ret)
	}
}

func TestCheckAssignmentDetectsClash(t *testing.T) {
	f := mustParse(t, `func f(0) {
e:
  a = const 1
  b = const 2
  s = add a, b
  ret s
}`)
	if err := CheckAssignment(f, []int{0, 0, 1}, 3); err == nil {
		t.Error("a and b share a register but checker passed")
	}
	if err := CheckAssignment(f, []int{0, 1, 0}, 3); err != nil {
		t.Errorf("valid assignment rejected: %v", err)
	}
}

func TestVerifyDetectsMiscompile(t *testing.T) {
	f := mustParse(t, loopSrc)
	a, _ := Allocate(f, "color", 6, Options{})
	// corrupt the machine code: change an add into a sub
	for _, b := range a.Machine.Blocks {
		for i := range b.Instrs {
			if b.Instrs[i].Op == OpAdd {
				b.Instrs[i].Op = OpSub
				goto done
			}
		}
	}
done:
	if _, err := Verify(f, a, [][]int64{{5}}); err == nil || !strings.Contains(err.Error(), "MISCOMPILE") {
		t.Errorf("tampered code not detected: %v", err)
	}
}

func TestStepLimitAndBounds(t *testing.T) {
	f := mustParse(t, "func f(0) {\ne:\n x = const 1\n br x, e, r\nr:\n ret x\n}\n")
	if _, err := Run(f, nil, 500); err != ErrStepLimit {
		t.Errorf("want step limit, got %v", err)
	}
	if err := CheckTerminates(f, [][]int64{nil}); err == nil {
		t.Error("CheckTerminates missed infinite loop")
	}
	g := mustParse(t, loopSrc)
	if _, err := Allocate(g, "color", 2, Options{}); err == nil {
		t.Error("K=2 accepted")
	}
	if _, err := Allocate(g, "color", MaxK+1, Options{}); err == nil {
		t.Error("huge K accepted")
	}
	if _, err := Allocate(g, "bogus", 4, Options{}); err == nil {
		t.Error("bogus allocator accepted")
	}
}

func TestGeneratorDeterministicAndValid(t *testing.T) {
	a, b := Generate(9, DefaultGen), Generate(9, DefaultGen)
	if a != b {
		t.Fatal("generator not deterministic")
	}
	if Generate(10, DefaultGen) == a {
		t.Fatal("different seeds gave same program")
	}
	for seed := int64(0); seed < 50; seed++ {
		cfg := DefaultGen
		cfg.Shuffle = seed%2 == 0
		f := mustParse(t, Generate(seed, cfg))
		if err := f.Validate(); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
		if _, err := Run(f, []int64{3, 4}, StepBudget); err != nil {
			t.Fatalf("seed %d: %v", seed, err)
		}
	}
}

func TestReportContainsEverything(t *testing.T) {
	f := mustParse(t, loopSrc)
	h, err := Report(ReportInput{Source: loopSrc, F: f, K: 4, Inputs: [][]int64{{7}}})
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"<svg", "Interference graph", "Live ranges", "cycles", "prefers-color-scheme", "Generated machine code"} {
		if !strings.Contains(h, want) {
			t.Errorf("report missing %q", want)
		}
	}
	if strings.Contains(h, "<script") {
		t.Error("report should be script-free")
	}
}

func TestSweepMonotoneForColour(t *testing.T) {
	f := mustParse(t, loopSrc)
	sw := Sweep(f, 3, 8, [][]int64{{9}}, true)
	prev := 1 << 60
	for _, rows := range sw {
		for _, r := range rows {
			if r.Err != nil {
				t.Fatal(r.Err)
			}
		}
		c := rows[0].Dyn.Cycles
		if c > prev+prev/10 {
			t.Errorf("K=%d colour cycles %d got much worse than %d", rows[0].K, c, prev)
		}
		prev = c
	}
}
