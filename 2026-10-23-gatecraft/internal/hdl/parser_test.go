package hdl

import (
	"strings"
	"testing"
)

func TestParseCounter(t *testing.T) {
	src := `
module counter #(parameter W = 8) (input clk, input rst, input en, output reg [W-1:0] q);
  always @(posedge clk) begin
    if (rst) q <= 0;
    else if (en) q <= q + 1;
  end
endmodule`
	f, err := Parse("c.v", src)
	if err != nil {
		t.Fatal(err)
	}
	m := f.Modules[0]
	if m.Name != "counter" || len(m.Decls) != 4 || len(m.Always) != 1 || m.Always[0].Clock != "clk" {
		t.Fatalf("bad parse: %+v", m)
	}
	if len(m.Params) != 1 || m.Params[0].Name != "W" {
		t.Fatal("param missing")
	}
}

func TestParseNonANSIAndInstances(t *testing.T) {
	src := `
module top(a, b, y);
  input [3:0] a, b; output [3:0] y;
  wire [3:0] t = a ^ b;
  sub #(.N(4)) u0 (.x(t), .y(y));
  p: assert property (y != 4'hF);
endmodule
module sub #(parameter N=2)(input [N-1:0] x, output [N-1:0] y); assign y = ~x; endmodule`
	f, err := Parse("t.v", src)
	if err != nil {
		t.Fatal(err)
	}
	if len(f.Modules) != 2 || len(f.Modules[0].Insts) != 1 || len(f.Modules[0].Props) != 1 || f.Modules[0].Props[0].Name != "p" {
		t.Fatalf("bad: %+v", f.Modules[0])
	}
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"module m(; endmodule":                                                         "expected",
		"module m(input a); assign a = ; endmodule":                                    "expected expression",
		"module m(input clk); always @(negedge clk) ; endmodule":                       "negedge",
		"module m(input clk, input r); always @(posedge clk or posedge r) ; endmodule": "asynchronous",
		"module m; reg [3:0] mem [0:3]; endmodule":                                     "memory arrays",
		"module m(input a); wire x = 3'bxx1; endmodule":                                "x/z",
		"module m(input a);":                                                           "endmodule",
		"module m(input a); initial #5 ; endmodule":                                    "delays",
	}
	for src, want := range cases {
		_, err := Parse("e.v", src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: want error containing %q, got %v", src, want, err)
		}
	}
}

func TestNumbers(t *testing.T) {
	for _, c := range []struct {
		s string
		w int
		v int64
	}{{"8'hFF", 8, 255}, {"4'b1_010", 4, 10}, {"'d9", 0, 9}, {"12", 0, 12}, {"3'd9", 3, 1}, {"16'o17", 16, 15}} {
		w, v, e := parseNumber(c.s)
		if e != "" || w != c.w || v.Int64() != c.v {
			t.Errorf("%s -> %d %v %q", c.s, w, v, e)
		}
	}
}

func TestPrecedence(t *testing.T) {
	f, err := Parse("p.v", "module m(input [3:0] a, b, output y); assign y = a + b * 2 == 3 ? a & b | 1 : 0; endmodule")
	if err != nil {
		t.Fatal(err)
	}
	tern, ok := f.Modules[0].Assigns[0].RHS.(*Ternary)
	if !ok {
		t.Fatal("top should be ternary")
	}
	eq := tern.C.(*Binary)
	if eq.Op != "==" || eq.L.(*Binary).Op != "+" || eq.L.(*Binary).R.(*Binary).Op != "*" {
		t.Fatal("bad arithmetic precedence")
	}
	if tern.T.(*Binary).Op != "|" {
		t.Fatal("| should bind looser than &")
	}
}
