package elab_test

import (
	"math/big"
	"strings"
	"testing"

	"gatecraft/internal/sim"
	"gatecraft/internal/testutil"
)

func run(t *testing.T, src, tb string) {
	t.Helper()
	g := testutil.Build(t, src, "")
	s := sim.New(g)
	var out strings.Builder
	res, err := s.RunScript(strings.NewReader(tb), &out)
	if err != nil {
		t.Fatalf("script error: %v\n%s", err, out.String())
	}
	if !res.OK() {
		t.Fatalf("testbench failures:\n%s", out.String())
	}
	if res.Checks == 0 {
		t.Fatal("testbench ran no checks")
	}
}

func TestCounter(t *testing.T) {
	run(t, `
module counter #(parameter W = 4) (input clk, input rst, input en, output reg [W-1:0] q);
  always @(posedge clk) begin
    if (rst) q <= 0;
    else if (en) q <= q + 1;
  end
endmodule`, `
set rst 1
tick
expect q 0
set rst 0
set en 1
tick 5
expect q 5
set en 0
tick 3
expect q 5
set en 1
tick 11
expect q 0      # wraps at 16
tick
expect q 1
`)
}

func TestAdderAndOps(t *testing.T) {
	run(t, `
module ops(input [7:0] a, input [7:0] b, output [7:0] sum, output [7:0] diff, output [7:0] prod,
           output [7:0] quo, output [7:0] rem, output lt, output eq, output [8:0] wide, output [7:0] sh);
  assign sum = a + b;
  assign diff = a - b;
  assign prod = a * b;
  assign quo = a / b;
  assign rem = a % b;
  assign lt = a < b;
  assign eq = a == b;
  assign wide = a + b;       // context width 9: carry is kept
  assign sh = (a << b[2:0]) ^ (a >> 1);
endmodule`, `
set a 200
set b 100
expect sum 44
expect diff 100
expect prod 32     # 20000 mod 256
expect quo 2
expect rem 0
expect lt 0
expect eq 0
expect wide 300
set a 7
set b 9
expect diff 254
expect quo 0
expect rem 7
expect lt 1
set b 0
expect quo 255   # divide by zero convention
expect rem 7
set a 3
set b 3
expect eq 1
expect sh 0x19  # (3<<3) ^ (3>>1) = 24 ^ 1
`)
}

func TestCombAlwaysCaseAndLoops(t *testing.T) {
	run(t, `
module alu(input [3:0] a, input [3:0] b, input [1:0] op, output reg [3:0] y, output reg [2:0] pop);
  integer i;
  always @(*) begin
    case (op)
      2'd0: y = a & b;
      2'd1: y = a | b;
      2'd2: y = a ^ b;
      default: y = a + b;
    endcase
    pop = 0;
    for (i = 0; i < 4; i = i + 1)
      pop = pop + a[i];
  end
endmodule`, `
set a 0b1100
set b 0b1010
set op 0
expect y 0b1000
set op 1
expect y 0b1110
set op 2
expect y 0b0110
set op 3
expect y 6
expect pop 2
set a 15
expect pop 4
`)
}

func TestBlockingInClockedAndHierarchy(t *testing.T) {
	run(t, `
module reg1 #(parameter W=8)(input clk, input [W-1:0] d, output reg [W-1:0] q);
  always @(posedge clk) q <= d;
endmodule
module top(input clk, input [7:0] x, output [7:0] y);
  wire [7:0] m;
  reg1 #(.W(8)) s1 (.clk(clk), .d(x + 8'd1), .q(m));
  reg1 s2 (clk, m, y);
endmodule`, `
set x 10
tick
expect y 0
tick
expect y 11
set x 20
tick
expect y 11
tick
expect y 21
expect s1.q 21
`)
}

func TestShiftRegisterConcatSwap(t *testing.T) {
	run(t, `
module sr(input clk, input din, output [3:0] q, output reg [1:0] a, output reg [1:0] b);
  reg [3:0] r;
  assign q = r;
  initial begin a = 2'd1; b = 2'd2; end
  always @(posedge clk) begin
    r <= {r[2:0], din};
    a <= b;  b <= a;       // non-blocking swap
  end
endmodule`, `
expect a 1
expect b 2
set din 1
tick
expect q 1
expect a 2
expect b 1
set din 0
tick
tick
expect q 0b100
expect a 2
set din 1
tick 2
expect q 0b0011
`)
}

func TestDynamicIndexAndPartSelect(t *testing.T) {
	run(t, `
module sel(input [7:0] x, input [2:0] i, output b, output [3:0] hi, output [3:0] win, output reg [7:0] w);
  assign b = x[i];
  assign hi = x[7:4];
  assign win = x[i +: 4];
  always @* begin
    w = x;
    w[i] = ~x[i];
  end
endmodule`, `
set x 0b10110010
set i 1
expect b 1
set i 2
expect b 0
expect hi 0b1011
set i 3
expect win 0b0110
expect w 0b10111010
set i 7
expect w 0b00110010
`)
}

func TestErrors(t *testing.T) {
	cases := []struct{ name, src, want string }{
		{"latch", "module m(input a, input c, output reg y); always @* if (c) y = a; endmodule", "latch inferred"},
		{"loop", "module m(input a, output y); wire t; assign t = y & a; assign y = ~t; endmodule", "combinational loop"},
		{"multi", "module m(input a, output y); assign y = a; assign y = ~a; endmodule", "multiple drivers"},
		{"undeclared", "module m(input a, output y); assign y = b; endmodule", "undeclared"},
		{"undriven", "module m(input a, output y); wire t; assign y = t & a; endmodule", "never driven"},
		{"wireassign", "module m(input a, output y); always @* y = a; endmodule", "must be declared 'reg'"},
		{"nb-comb", "module m(input a, output reg y); always @* y <= a; endmodule", "non-blocking"},
		{"badclock", "module m(input a, input b, output reg y); always @(posedge a & b) y <= 1; endmodule", "expected"},
		{"gated", "module m(input a, input b, output reg y); wire c; assign c = a & b; always @(posedge c) y <= 1; endmodule", "clock"},
		{"oob", "module m(input [3:0] a, output y); assign y = a[7]; endmodule", "out of range"},
		{"param", "module m #(parameter W=0)(input a, output y); assign y = a; endmodule module t(input a, output y); m #(.Q(1)) u(.a(a), .y(y)); endmodule", "no overridable parameter"},
		{"unconn", "module s(input a, output y); assign y = a; endmodule module t(input a, output y); s u(.y(y)); endmodule", "not connected"},
		{"mixed", "module m(input clk, input a, output reg y); always @(posedge clk) begin y = a; y <= ~a; end endmodule", "mixes blocking"},
	}
	for _, c := range cases {
		_, err := testutil.Try(c.src, "")
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: want error containing %q, got %v", c.name, c.want, err)
		}
	}
}

func TestSimSetBounds(t *testing.T) {
	g := testutil.Build(t, "module m(input [3:0] a, output [3:0] y); assign y = a; endmodule", "")
	s := sim.New(g)
	if err := s.Set("a", big.NewInt(16)); err == nil {
		t.Fatal("expected overflow error")
	}
}
