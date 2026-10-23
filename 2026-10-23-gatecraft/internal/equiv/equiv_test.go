package equiv_test

import (
	"math/rand"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/equiv"
	"gatecraft/internal/testutil"
)

const redundant = `
module red(input [7:0] a, input [7:0] b, input s, output [7:0] y, output z, output [7:0] m);
  // (a&b)|(a&~b) == a ; mux with equal arms ; double negation
  assign y = (a & b) | (a & ~b);
  assign z = ~(~(s & a[0])) & (s | a[0]) & s;
  assign m = s ? (a + b) : (b + a);
endmodule`

const dupRegs = `
module dup(input clk, input rst, input en, output [3:0] c1, output [3:0] c2, output k);
  reg [3:0] a, b;
  reg zero, dead;
  initial begin a = 0; b = 0; end
  always @(posedge clk) begin
    if (rst) a <= 0; else if (en) a <= a + 1;
    if (rst) b <= 0; else if (en) b <= b + 1;
    zero <= zero & en;           // stuck at its reset value 0
    dead <= ~dead;                // observable by nothing
  end
  assign c1 = a;
  assign c2 = b;
  assign k = zero;
endmodule`

func simEq(t *testing.T, a, b *aig.AIG, cycles int) {
	t.Helper()
	rng := rand.New(rand.NewSource(3))
	sa, sb := aig.NewSimulator(a), aig.NewSimulator(b)
	for c := 0; c < cycles; c++ {
		for i, pi := range a.PIs {
			w := rng.Uint64()
			sa.SetPI(i, w)
			// same port/bit in b
			for j, pj := range b.PIs {
				if pj.Port == pi.Port && pj.Bit == pi.Bit {
					sb.SetPI(j, w)
				}
			}
		}
		sa.Eval()
		sb.Eval()
		for _, p := range a.Outputs {
			q := b.FindOutput(p.Name)
			for i := range p.Bits {
				if sa.Lit(p.Bits[i]) != sb.Lit(q.Bits[i]) {
					t.Fatalf("cycle %d: output %s[%d] differs after optimisation", c, p.Name, i)
				}
			}
		}
		sa.Clock(nil)
		sb.Clock(nil)
	}
}

func TestOptimizeShrinksAndStaysEquivalent(t *testing.T) {
	for name, src := range map[string]string{"redundant": redundant, "dupRegs": dupRegs} {
		g := testutil.Build(t, src, "")
		before := g.Stats()
		opt, reports, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
		if err != nil {
			t.Fatal(err)
		}
		after := opt.Stats()
		t.Logf("%s: %s -> %s (%d passes)", name, before, after, len(reports))
		if after.Ands >= before.Ands && after.Latches >= before.Latches {
			t.Errorf("%s: optimiser achieved nothing", name)
		}
		res, err := equiv.CheckComb(g, opt)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if res.Verdict != equiv.Equivalent {
			t.Fatalf("%s: optimised design not equivalent: %+v", name, res)
		}
		simEq(t, g, opt, 200)
	}
}

func TestDupRegsRemoved(t *testing.T) {
	g := testutil.Build(t, dupRegs, "")
	opt, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	if got := opt.Stats().Latches; got != 4 {
		t.Fatalf("want 4 latches (one counter), got %d (removed=%v)", got, opt.Removed)
	}
	if opt.Removed["zero"] != "0" || opt.Removed["dead"] != "dead" {
		t.Fatalf("bad removal record: %v", opt.Removed)
	}
	// b[i] aliased to a[i]
	if opt.Removed["b[2]"] != "a[2]" {
		t.Fatalf("expected b[2] -> a[2], got %q", opt.Removed["b[2]"])
	}
}

func TestEquivDetectsBugWithConfirmedCex(t *testing.T) {
	good := testutil.Build(t, `module m(input [7:0] a, input [7:0] b, output [7:0] y, output c);
  assign y = a + b; assign c = (a + b) < a; endmodule`, "")
	bad := testutil.Build(t, `module m(input [7:0] a, input [7:0] b, output [7:0] y, output c);
  assign y = (a == 8'd77 && b == 8'd1) ? 8'd0 : a + b; assign c = (a + b) < a; endmodule`, "")
	res, err := equiv.CheckComb(good, bad)
	if err != nil {
		t.Fatal(err)
	}
	if res.Verdict != equiv.Different || res.Cex == nil || !res.Cex.Confirmed {
		t.Fatalf("expected confirmed counterexample, got %+v", res)
	}
	if res.Cex.Inputs["a"].Int64() != 77 || res.Cex.Inputs["b"].Int64() != 1 {
		t.Fatalf("counterexample should be the unique bad input, got %v", res.Cex.Inputs)
	}
}

func TestAdderArchitecturesEquivalent(t *testing.T) {
	ripple := testutil.Build(t, `module add(input [7:0] a, input [7:0] b, output [7:0] y);
  assign y = a + b; endmodule`, "")
	cla := testutil.Build(t, `module add(input [7:0] a, input [7:0] b, output [7:0] y);
  wire [7:0] g = a & b;
  wire [7:0] p = a ^ b;
  wire [8:0] c;
  assign c[0] = 1'b0;
  assign c[1] = g[0];
  assign c[2] = g[1] | (p[1] & g[0]);
  assign c[3] = g[2] | (p[2] & g[1]) | (p[2] & p[1] & g[0]);
  assign c[4] = g[3] | (p[3] & g[2]) | (p[3] & p[2] & g[1]) | (p[3] & p[2] & p[1] & g[0]);
  assign c[5] = g[4] | (p[4] & c[4]);
  assign c[6] = g[5] | (p[5] & c[5]);
  assign c[7] = g[6] | (p[6] & c[6]);
  assign c[8] = g[7] | (p[7] & c[7]);
  assign y = p ^ c[7:0];
endmodule`, "")
	res, err := equiv.CheckComb(ripple, cla)
	if err != nil {
		t.Fatal(err)
	}
	if res.Verdict != equiv.Equivalent {
		t.Fatalf("ripple vs carry-lookahead: %+v", res)
	}
}

func TestMultiplierCommutes(t *testing.T) {
	a := testutil.Build(t, "module m(input [5:0] a, input [5:0] b, output [5:0] y); assign y = a * b; endmodule", "")
	b := testutil.Build(t, "module m(input [5:0] a, input [5:0] b, output [5:0] y); assign y = b * a; endmodule", "")
	res, err := equiv.CheckComb(a, b)
	if err != nil || res.Verdict != equiv.Equivalent {
		t.Fatalf("a*b vs b*a: %v %+v", err, res)
	}
}

func TestInterfaceMismatch(t *testing.T) {
	a := testutil.Build(t, "module m(input [3:0] a, output y); assign y = a[0]; endmodule", "")
	b := testutil.Build(t, "module m(input [4:0] a, output y); assign y = a[0]; endmodule", "")
	if _, err := equiv.CheckComb(a, b); err == nil || !strings.Contains(err.Error(), "4 bits vs 5 bits") {
		t.Fatalf("want width mismatch error, got %v", err)
	}
}

func TestBoundedFindsSequentialBug(t *testing.T) {
	good := testutil.Build(t, `module c(input clk, input en, output reg [3:0] q);
  always @(posedge clk) if (en) q <= q + 1; endmodule`, "")
	// differs only after the counter reaches 9 while enabled
	bad := testutil.Build(t, `module c(input clk, input en, output reg [3:0] q);
  always @(posedge clk) if (en) q <= (q == 4'd9) ? 4'd0 : q + 1; endmodule`, "")
	res, err := equiv.CheckBounded(good, bad, 20)
	if err != nil {
		t.Fatal(err)
	}
	if res.Verdict != equiv.Different || !res.Trace.Confirmed {
		t.Fatalf("expected confirmed trace, got %+v", res)
	}
	if res.Trace.Cycle != 10 {
		t.Fatalf("shortest divergence is 10 enabled ticks after reset, got cycle %d", res.Trace.Cycle)
	}
	res, err = equiv.CheckBounded(good, good, 12)
	if err != nil || res.Verdict != equiv.Equivalent {
		t.Fatalf("self-equivalence failed: %v %+v", err, res)
	}
}

func TestProps(t *testing.T) {
	g := testutil.Build(t, `
module fsm(input clk, input go, input stop, output reg [1:0] st);
  // one-hot-ish: st is always in {0,1,2}; 3 is unreachable
  always @(posedge clk) begin
    case (st)
      2'd0: if (go) st <= 2'd1;
      2'd1: st <= 2'd2;
      2'd2: if (stop) st <= 2'd0;
      default: st <= 2'd0;
    endcase
  end
  assert property (st != 2'd3);          // true but needs induction + reachability
  assert property (st != 2'd2 || !go);   // false: go can be 1 while in state 2
  assume property (!(go && stop));
endmodule`, "")
	rs, err := equiv.CheckProps(g, equiv.PropOptions{MaxDepth: 10, Unique: true})
	if err != nil {
		t.Fatal(err)
	}
	if len(rs) != 2 {
		t.Fatal(len(rs))
	}
	if rs[1].Status != equiv.PropFailed || !rs[1].Trace.Confirmed || rs[1].Depth != 2 {
		t.Fatalf("second property should fail at cycle 2 with a confirmed trace: %+v", rs[1])
	}
	if rs[0].Status != equiv.PropProved {
		t.Fatalf("first property should be proved: %+v", rs[0])
	}
}
