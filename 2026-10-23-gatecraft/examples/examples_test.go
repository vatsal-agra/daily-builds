package examples_test

import (
	"math/big"
	"os"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/elab"
	"gatecraft/internal/equiv"
	"gatecraft/internal/hdl"
	"gatecraft/internal/lutmap"
	"gatecraft/internal/sim"
)

func load(t *testing.T, name string, params map[string]*big.Int) *aig.AIG {
	t.Helper()
	src, err := os.ReadFile(name + ".v")
	if err != nil {
		t.Fatal(err)
	}
	f, err := hdl.Parse(name+".v", string(src))
	if err != nil {
		t.Fatal(err)
	}
	g, err := elab.Elaborate([]*hdl.File{f}, elab.Options{Params: params})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return g
}

func runTB(t *testing.T, g *aig.AIG, tb string) *sim.Result {
	t.Helper()
	f, err := os.Open(tb)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out strings.Builder
	res, err := sim.New(g).RunScript(f, &out)
	if err != nil {
		t.Fatalf("%s: %v", tb, err)
	}
	if !res.OK() || res.Checks == 0 {
		t.Fatalf("%s: %d checks, failures:\n%s", tb, res.Checks, out.String())
	}
	return res
}

func TestTestbenchesPass(t *testing.T) {
	for _, c := range []struct{ design, tb string }{
		{"counter", "counter.tb"}, {"fifo4", "fifo4.tb"}, {"traffic", "traffic.tb"},
		{"detect_onehot", "detect.tb"}, {"detect_binary", "detect.tb"}, {"tinycpu", "tinycpu.tb"},
	} {
		runTB(t, load(t, c.design, nil), c.tb)
	}
}

func TestBugTraceFailsOnBuggyDesignOnly(t *testing.T) {
	// the Fibonacci / overlap bug is only visible on the buggy detector
	good, bad := load(t, "detect_binary", nil), load(t, "detect_bug", nil)
	script := "set rst 1\ntick\nset rst 0\nset bit_in 1\ntick\nset bit_in 0\ntick\nset bit_in 1\ntick\nset bit_in 0\ntick\nset bit_in 1\ntick\nset bit_in 1\nexpect found 1\n"
	for name, g := range map[string]*aig.AIG{"good": good, "bad": bad} {
		res, err := sim.New(g).RunScript(strings.NewReader(script), &strings.Builder{})
		if err != nil {
			t.Fatal(err)
		}
		if (name == "good") != res.OK() {
			t.Fatalf("%s detector: ok=%v", name, res.OK())
		}
	}
}

func TestParameterOverrides(t *testing.T) {
	g := load(t, "traffic", map[string]*big.Int{"GREEN": big.NewInt(3), "YELLOW": big.NewInt(1)})
	res, err := sim.New(g).RunScript(strings.NewReader("set rst 1\ntick\nset rst 0\ntick 3\nexpect ns_yellow 1\ntick 1\nexpect ew_green 1\n"), &strings.Builder{})
	if err != nil || !res.OK() {
		t.Fatalf("%v %v", err, res)
	}
}

func TestAdderEquivalences(t *testing.T) {
	rtl, kogge, bug := load(t, "adder_rtl", nil), load(t, "adder_kogge", nil), load(t, "adder_buggy", nil)
	r, err := equiv.CheckComb(rtl, kogge)
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("ripple vs Kogge-Stone: %v %+v", err, r)
	}
	r, err = equiv.CheckComb(rtl, bug)
	if err != nil || r.Verdict != equiv.Different || !r.Cex.Confirmed {
		t.Fatalf("buggy adder: %v %+v", err, r)
	}
	if r.Cex.Inputs["a"].Int64() != 255 || r.Cex.Inputs["b"].Int64() != 0 || r.Cex.Inputs["cin"].Int64() != 1 {
		t.Fatalf("expected the unique corner case a=255 b=0 cin=1, got %v", r.Cex.Inputs)
	}
}

func TestPopcountImplementationsAgree(t *testing.T) {
	r, err := equiv.CheckComb(load(t, "popcount_loop", nil), load(t, "popcount_tree", nil))
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("%v %+v", err, r)
	}
}

func TestSequentialEquivalenceAcrossEncodings(t *testing.T) {
	// different register names/encodings: state matching is impossible ...
	for _, pair := range [][2]string{{"detect_onehot", "detect_binary"}, {"mod10_a", "mod10_b"}} {
		a, b := load(t, pair[0], nil), load(t, pair[1], nil)
		if _, err := equiv.CheckComb(a, b); err == nil {
			t.Fatalf("%v: expected state matching to be refused", pair)
		}
		// ... but the invariant-strengthened induction proves them equal for all time
		r, err := equiv.CheckInduction(a, b, 8)
		if err != nil || r.Verdict != equiv.Equivalent {
			t.Fatalf("%v: %v %+v", pair, err, r)
		}
	}
	bug, err := equiv.CheckBounded(load(t, "detect_binary", nil), load(t, "detect_bug", nil), 24)
	if err != nil || bug.Verdict != equiv.Different || bug.Trace.Cycle != 5 || !bug.Trace.Confirmed {
		t.Fatalf("%v %+v", err, bug)
	}
}

func TestPropertyResults(t *testing.T) {
	// lock: finds the code, proves the invariants
	g := load(t, "lock", nil)
	rs, err := equiv.CheckProps(g, equiv.PropOptions{MaxDepth: 12, Unique: true})
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]equiv.PropResult{}
	for _, r := range rs {
		byName[r.Name] = r
	}
	nv := byName["never_opens"]
	if nv.Status != equiv.PropFailed || !nv.Trace.Confirmed || nv.Depth != 4 {
		t.Fatalf("never_opens: %+v", nv)
	}
	var code []int64
	for _, in := range nv.Trace.Inputs[:4] {
		if in["enter"].Sign() != 1 {
			t.Fatalf("every step of the shortest opening sequence presses enter: %v", in)
		}
		code = append(code, in["digit"].Int64())
	}
	if code[0] != 3 || code[1] != 1 || code[2] != 4 || code[3] != 1 {
		t.Fatalf("recovered code %v, want 3 1 4 1", code)
	}
	for _, n := range []string{"open_means_done", "progress_bound"} {
		if byName[n].Status != equiv.PropProved {
			t.Fatalf("%s: %+v", n, byName[n])
		}
	}
	for _, name := range []string{"fifo4", "traffic", "tinycpu"} {
		rs, err := equiv.CheckProps(load(t, name, nil), equiv.PropOptions{MaxDepth: 20, Unique: true})
		if err != nil {
			t.Fatal(err)
		}
		for _, r := range rs {
			if r.Status != equiv.PropProved {
				t.Fatalf("%s/%s: %v", name, r.Name, r.Status)
			}
		}
	}
}

func TestRedundantPipelineIsCleanedUp(t *testing.T) {
	g := load(t, "pipeline_redundant", nil)
	opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	b, a := g.Stats(), opt.Stats()
	t.Logf("%s -> %s", b, a)
	// live before: a_q a_dup b_q b_dup (32) + prod (16) + acc (16) + v1 + sticky + flag = 67.
	// after: a_q b_q (16) + prod, acc (32) minus their always-zero bit 0 (the datapath computes 2*a*b) = 46
	if b.Latches != 67 || a.Latches != 46 {
		t.Fatalf("expected 67 -> 46 registers, got %d -> %d", b.Latches, a.Latches)
	}
	for k, want := range map[string]string{"sticky": "0", "flag": "0", "prod[0]": "0", "acc[0]": "0", "a_dup[3]": "a_q[3]", "b_dup[7]": "b_q[7]", "v3": "dead", "v1": "dead"} {
		if opt.Removed[k] != want {
			t.Fatalf("Removed[%s] = %q, want %q (all: %v)", k, opt.Removed[k], want, opt.Removed)
		}
	}
	if a.Ands >= b.Ands {
		t.Fatalf("logic should shrink too: %d -> %d", b.Ands, a.Ands)
	}
	r, err := equiv.CheckComb(g, opt)
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("%v %+v", err, r)
	}
}

func TestTinyCPUOptimisesAndMaps(t *testing.T) {
	g := load(t, "tinycpu", nil)
	opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	if b, a := g.Stats(), opt.Stats(); a.Ands > b.Ands/2 || a.Latches >= b.Latches {
		t.Fatalf("%s -> %s", b, a)
	}
	// the optimised CPU still runs both programs
	runTB(t, opt, "tinycpu.tb")
	net, err := lutmap.Map(opt, 4)
	if err != nil {
		t.Fatal(err)
	}
	if err := net.Verify(100, 1); err != nil {
		t.Fatal(err)
	}
}

func TestCriticalPathOfRippleAdder(t *testing.T) {
	g := load(t, "adder_rtl", nil)
	p := g.CriticalPath()
	if p.Depth != g.Stats().Depth || len(p.Steps) != p.Depth+1 || p.Steps[0].Level != 0 {
		t.Fatalf("path inconsistent: %+v vs depth %d", p, g.Stats().Depth)
	}
	for i := 1; i < len(p.Steps); i++ {
		if p.Steps[i].Level != p.Steps[i-1].Level+1 {
			t.Fatalf("levels must increase by one along the critical path: %+v", p.Steps)
		}
	}
}
