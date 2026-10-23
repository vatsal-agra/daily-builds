package lutmap_test

import (
	"bytes"
	"os"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/elab"
	"gatecraft/internal/equiv"
	"gatecraft/internal/hdl"
	"gatecraft/internal/lutmap"
	"gatecraft/internal/testutil"
)

var designs = map[string]string{
	"alu": `module m(input [7:0] a, input [7:0] b, input [1:0] op, output reg [7:0] y, output z);
  always @* case (op) 0: y = a + b; 1: y = a - b; 2: y = a & b; default: y = a ^ b; endcase
  assign z = y == 0; endmodule`,
	"mul": `module m(input [5:0] a, input [5:0] b, output [5:0] y); assign y = a * b; endmodule`,
	"seq": `module m(input clk, input rst, input [3:0] d, output reg [7:0] acc);
  always @(posedge clk) if (rst) acc <= 0; else acc <= acc + d * d; endmodule`,
}

func TestMappingIsCorrectForAllK(t *testing.T) {
	for name, src := range designs {
		g := testutil.Build(t, src, "")
		g, _, err := aig.Optimize(g, aig.OptOptions{Seed: 1})
		if err != nil {
			t.Fatal(err)
		}
		prevLUTs := 1 << 30
		for k := 2; k <= 6; k++ {
			net, err := lutmap.Map(g, k)
			if err != nil {
				t.Fatal(err)
			}
			for _, l := range net.LUTs {
				if len(l.In) > k || len(l.In) == 0 {
					t.Fatalf("%s k=%d: LUT with %d inputs", name, k, len(l.In))
				}
			}
			if err := net.Verify(50, uint64(k)); err != nil {
				t.Fatalf("%s k=%d: %v", name, k, err)
			}
			// formal: rebuild an AIG from the LUTs and prove it equivalent
			r, err := equiv.CheckComb(g, net.ToAIG())
			if err != nil || r.Verdict != equiv.Equivalent {
				t.Fatalf("%s k=%d: SAT check of the mapping failed: %v %+v", name, k, err, r)
			}
			if k == 2 && net.Depth > g.Stats().Depth { // a 2-LUT can absorb a whole XOR (2 AIG levels)
				t.Fatalf("%s: 2-LUT depth %d exceeds AIG depth %d", name, net.Depth, g.Stats().Depth)
			}
			if len(net.LUTs) > prevLUTs+prevLUTs/4 {
				t.Fatalf("%s: LUT count grew from %d to %d when k increased to %d", name, prevLUTs, len(net.LUTs), k)
			}
			prevLUTs = len(net.LUTs)
			t.Logf("%s: %s", name, net.Summary())
		}
		n4, _ := lutmap.Map(g, 4)
		n6, _ := lutmap.Map(g, 6)
		if n6.Depth > n4.Depth || len(n6.LUTs) > len(n4.LUTs) {
			t.Fatalf("%s: 6-LUT mapping (%d LUTs, depth %d) should not be worse than 4-LUT (%d, %d)", name, len(n6.LUTs), n6.Depth, len(n4.LUTs), n4.Depth)
		}
	}
}

func TestMappingRejectsBadK(t *testing.T) {
	g := testutil.Build(t, designs["alu"], "")
	for _, k := range []int{0, 1, 7} {
		if _, err := lutmap.Map(g, k); err == nil {
			t.Fatalf("k=%d should be rejected", k)
		}
	}
}

func TestBLIFOutput(t *testing.T) {
	g := testutil.Build(t, designs["seq"], "")
	net, err := lutmap.Map(g, 4)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := net.WriteBLIF(&buf, "acc"); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	for _, want := range []string{".model acc", ".inputs", ".outputs", ".latch", ".end"} {
		if !strings.Contains(out, want) {
			t.Fatalf("BLIF lacks %q", want)
		}
	}
	if strings.Count(out, ".names") < len(net.LUTs) {
		t.Fatal("fewer .names than LUTs")
	}
}

func TestMapsTheTinyCPU(t *testing.T) {
	src, err := os.ReadFile("../../examples/tinycpu.v")
	if err != nil {
		t.Skip(err)
	}
	f, _ := hdl.Parse("tinycpu.v", string(src))
	g, err := elab.Elaborate([]*hdl.File{f}, elab.Options{})
	if err != nil {
		t.Fatal(err)
	}
	g, _, _ = aig.Optimize(g, aig.OptOptions{Seed: 1})
	net, err := lutmap.Map(g, 6)
	if err != nil {
		t.Fatal(err)
	}
	if err := net.Verify(100, 3); err != nil {
		t.Fatal(err)
	}
	r, err := equiv.CheckComb(g, net.ToAIG())
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("%v %+v", err, r)
	}
	t.Log(net.Summary(), "AIG:", g.Stats())
	if len(net.LUTs) > g.Stats().Ands/2 {
		t.Fatalf("6-LUT cover should need far fewer LUTs than ANDs: %d vs %d", len(net.LUTs), g.Stats().Ands)
	}
}
