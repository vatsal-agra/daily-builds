package equiv_test

import (
	"os"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/elab"
	"gatecraft/internal/equiv"
	"gatecraft/internal/hdl"
	"gatecraft/internal/testutil"
)

// Review finding R3: twin registers whose only effect cancels out.  The optimiser
// removes both (one as an alias of the other, which then becomes unobservable);
// the checker must still be able to prove the result, which needs the tie a==b.
func TestAliasOfUnobservableRegisterKeepsItsTie(t *testing.T) {
	g := testutil.Build(t, `
module m(input clk, input x, output y);
  reg a, b;
  always @(posedge clk) begin a <= a ^ x; b <= b ^ x; end
  assign y = a ^ b;          // 0 in every reachable state, but not combinationally
endmodule`, "")
	opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	if opt.Stats().Latches != 0 || opt.Stats().Ands != 0 {
		t.Fatalf("expected everything to vanish, got %s", opt.Stats())
	}
	r, err := equiv.CheckComb(g, opt)
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("checker rejected a correct optimisation: %v %+v %+v", err, r, r.Cex)
	}
	// ... and the same check refuses a wrong 'optimisation' (y stuck at 1)
	bad := testutil.Build(t, `module m(input clk, input x, output y); assign y = 1'b1; endmodule`, "")
	bad.Removed = opt.Removed
	r, err = equiv.CheckComb(g, bad)
	if err != nil || r.Verdict != equiv.Different || !r.Cex.Confirmed {
		t.Fatalf("wrong netlist accepted: %v %+v", err, r)
	}
}

// Review finding R4: identical logic must be recognised structurally, not by brute-force SAT.
func TestIdenticalMultipliersNeedNoSearch(t *testing.T) {
	src := "module m(input [11:0] a, input [11:0] b, output [11:0] y); assign y = a * b; endmodule"
	r, err := equiv.CheckComb(testutil.Build(t, src, ""), testutil.Build(t, src, ""))
	if err != nil || r.Verdict != equiv.Equivalent || r.Conflicts != 0 {
		t.Fatalf("%v %+v", err, r)
	}
	// bounded: two copies of a registered multiplier over 12 cycles
	seq := "module m(input clk, input [7:0] a, input [7:0] b, output reg [7:0] y); always @(posedge clk) y <= y + a * b; endmodule"
	br, err := equiv.CheckBounded(testutil.Build(t, seq, ""), testutil.Build(t, seq, ""), 12)
	if err != nil || br.Verdict != equiv.Equivalent || br.Conflicts != 0 {
		t.Fatalf("%v %+v", err, br)
	}
}

// Review finding R5: after SAT-sweeping, registers can stay in the netlist but become unobservable.
func TestOptimizingTheTinyCPUIsFullyVerified(t *testing.T) {
	src, err := os.ReadFile("../../examples/tinycpu.v")
	if err != nil {
		t.Skip(err)
	}
	f, err := hdl.Parse("tinycpu.v", string(src))
	if err != nil {
		t.Fatal(err)
	}
	g, err := elab.Elaborate([]*hdl.File{f}, elab.Options{})
	if err != nil {
		t.Fatal(err)
	}
	passes := 0
	opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1, Check: func(pass string, before, after *aig.AIG) error {
		passes++
		r, err := equiv.CheckComb(before, after)
		if err != nil || r.Verdict != equiv.Equivalent {
			t.Fatalf("pass %s: %v %+v", pass, err, r)
		}
		return nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	if b, a := g.Stats(), opt.Stats(); a.Ands > b.Ands/2 || a.Latches >= b.Latches {
		t.Fatalf("expected the CPU to shrink a lot: %s -> %s", b, a)
	}
	r, err := equiv.CheckComb(g, opt)
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("end-to-end: %v %+v", err, r)
	}
}

// Review finding R7: single-bit ports are not called name[0].
func TestCounterexampleNamesSingleBitOutputsPlainly(t *testing.T) {
	a := testutil.Build(t, "module m(input x, output y); assign y = x; endmodule", "")
	b := testutil.Build(t, "module m(input x, output y); assign y = ~x; endmodule", "")
	r, err := equiv.CheckComb(a, b)
	if err != nil || r.Cex == nil || strings.Contains(r.Cex.Obligation, "[0]") {
		t.Fatalf("%v %+v", err, r)
	}
}
