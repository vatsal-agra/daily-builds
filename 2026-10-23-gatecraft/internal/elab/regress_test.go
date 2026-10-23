package elab_test

import (
	"math/big"
	"strings"
	"testing"

	"gatecraft/internal/elab"
	"gatecraft/internal/hdl"
	"gatecraft/internal/testutil"
)

// Review finding R1: an unconditional second assignment after a default must not look like a latch.
func TestUnconditionalOverwriteIsNotALatch(t *testing.T) {
	run(t, `
module m(input [3:0] a, input c, output reg [3:0] y, output reg [3:0] z);
  always @* begin
    y = 0;
    y = a;                // overwrites the unassigned marker with a defined value
    if (c) z = a; else z = ~a;
    z = z + 1;
  end
endmodule`, `
set a 5
set c 1
expect y 5
expect z 6
set c 0
expect z 11
`)
}

// Review finding R2: reading c[4] while defining c[5] is not a combinational loop.
func TestBitLevelDependenciesDoNotCreateFalseLoops(t *testing.T) {
	run(t, `
module m(input [3:0] a, output [3:0] y);
  wire [3:0] c;
  assign c[0] = a[0];
  assign c[1] = c[0] ^ a[1];
  assign c[2] = c[1] ^ a[2];
  assign c[3] = c[2] ^ a[3];
  assign y = c;
endmodule`, `
set a 0b1111
expect y 0b0101
`)
	// a genuine loop is still reported, with its path
	_, err := testutil.Try(`module m(input a, output y); wire p, q; assign p = q & a; assign q = ~p; assign y = q; endmodule`, "")
	if err == nil || !strings.Contains(err.Error(), "combinational loop") {
		t.Fatalf("want combinational loop error, got %v", err)
	}
}

func TestPortWidthWarnings(t *testing.T) {
	g := testutil.Build(t, `
module s(input [3:0] x, output [7:0] y); assign y = x; endmodule
module m(input [7:0] a, output [3:0] y);
  wire [7:0] w; s u(.x(a), .y(w)); assign y = w[3:0];
endmodule`, "m")
	if len(g.Warnings) != 1 || !strings.Contains(g.Warnings[0], "port 'x'") || !strings.Contains(g.Warnings[0], "truncated") {
		t.Fatalf("warnings = %v", g.Warnings)
	}
}

func TestNoModulesMessageNamesTheFile(t *testing.T) {
	f, _ := hdl.Parse("empty.v", "")
	_, err := elab.Elaborate([]*hdl.File{f}, elab.Options{})
	if err == nil || !strings.Contains(err.Error(), "empty.v") {
		t.Fatalf("got %v", err)
	}
}

func TestParameterOverrideAndClog2(t *testing.T) {
	f, err := hdl.Parse("p.v", `
module m #(parameter D = 10)(input [$clog2(D)-1:0] a, output [$clog2(D)-1:0] y);
  localparam W = $clog2(D);
  assign y = a + W;
endmodule`)
	if err != nil {
		t.Fatal(err)
	}
	g, err := elab.Elaborate([]*hdl.File{f}, elab.Options{Params: map[string]*big.Int{"D": big.NewInt(100)}})
	if err != nil {
		t.Fatal(err)
	}
	if w := len(g.Inputs[0].Bits); w != 7 {
		t.Fatalf("D=100 should give 7-bit port, got %d", w)
	}
}

// Review finding R8: a legal dependency that passes through a block's own output is not a loop.
func TestPeekThroughOwnOutputIsNotALoop(t *testing.T) {
	run(t, `
module m(input x, output reg a, output reg b, output c);
  assign c = ~a;
  always @* begin a = x; b = a ^ c; end
endmodule`, `
set x 1
expect a 1
expect c 0
expect b 1
set x 0
expect c 1
expect b 1
`)
	// ... unless the block overwrites the value afterwards: then the result would be ambiguous
	_, err := testutil.Try(`
module m(input x, output reg a, output reg b, output c);
  assign c = ~a;
  always @* begin a = x; b = a ^ c; a = ~x; end
endmodule`, "")
	if err == nil || !strings.Contains(err.Error(), "still computing") {
		t.Fatalf("want ambiguity error, got %v", err)
	}
}
