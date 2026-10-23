package emit_test

import (
	"bytes"
	"fmt"
	"math/rand"
	"os"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/elab"
	"gatecraft/internal/emit"
	"gatecraft/internal/equiv"
	"gatecraft/internal/hdl"
	"gatecraft/internal/testutil"
)

var designs = map[string]string{
	"comb": `module m(input [7:0] a, input [7:0] b, input s, output [7:0] y, output z);
  assign y = s ? a * b : a - b; assign z = ^a & (a < b); endmodule`,
	"seq": `module m(input clk, input rst, input [3:0] d, output reg [7:0] acc, output pos);
  always @(posedge clk) if (rst) acc <= 0; else acc <= acc + {4'b0, d};
  assign pos = acc[7]; endmodule`,
	"props": `module m(input clk, input go, output reg [1:0] st);
  always @(posedge clk) if (go) st <= st + 1;
  assert property (st != 2'd3);
  assume property (!go || st != 2'd2);
endmodule`,
}

func equivalent(t *testing.T, name string, a, b *aig.AIG) {
	t.Helper()
	if len(a.Latches) == 0 && len(b.Latches) == 0 {
		r, err := equiv.CheckComb(a, b)
		if err != nil || r.Verdict != equiv.Equivalent {
			t.Fatalf("%s: round trip not equivalent: %v %+v", name, err, r)
		}
		return
	}
	r, err := equiv.CheckBounded(a, b, 20)
	if err != nil || r.Verdict != equiv.Equivalent {
		t.Fatalf("%s: round trip diverges: %v %+v", name, err, r)
	}
}

func TestVerilogRoundTrip(t *testing.T) {
	for name, src := range designs {
		g := testutil.Build(t, src, "")
		var buf bytes.Buffer
		if err := emit.Verilog(&buf, g, "rt"); err != nil {
			t.Fatal(err)
		}
		f, err := hdl.Parse(name+".v", buf.String())
		if err != nil {
			t.Fatalf("%s: emitted Verilog does not parse: %v\n%s", name, err, buf.String())
		}
		g2, err := elab.Elaborate([]*hdl.File{f}, elab.Options{})
		if err != nil {
			t.Fatalf("%s: emitted Verilog does not elaborate: %v\n%s", name, err, buf.String())
		}
		equivalent(t, name, g, g2)
		if len(g.Asserts) != len(g2.Asserts) || len(g.Assumes) != len(g2.Assumes) {
			t.Fatalf("%s: properties lost in round trip", name)
		}
	}
}

func TestAIGERRoundTrip(t *testing.T) {
	for name, src := range designs {
		g := testutil.Build(t, src, "")
		var buf bytes.Buffer
		if err := emit.AIGER(&buf, g); err != nil {
			t.Fatal(err)
		}
		g2, err := emit.ReadAIGER(strings.NewReader(buf.String()))
		if err != nil {
			t.Fatalf("%s: %v\n%s", name, err, buf.String())
		}
		equivalent(t, name, g, g2)
	}
}

func TestReadAIGERErrors(t *testing.T) {
	for in, want := range map[string]string{
		"":                             "empty",
		"aig 1 1 0 1 0\n":              "ASCII AIGER",
		"aag 1 1 0 1 0\n2\n":           "truncated",
		"aag 3 1 0 1 1\n2\n6\n6 8 2\n": "exceeds",
		"aag 2 1 0 1 1\n2\n4\n4 4 2\n": "cycle",
		"aag x 1 0 1 0\n":              "bad AIGER header",
	} {
		_, err := emit.ReadAIGER(strings.NewReader(in))
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: want %q, got %v", in, want, err)
		}
	}
}

// ---- minimal BLIF interpreter to check the BLIF writer independently ----

type blifNet struct {
	inputs, outputs []string
	names           []struct {
		ins  []string
		out  string
		rows []string
	}
	latches []struct {
		d, q string
		init int
	}
}

func parseBLIF(t *testing.T, text string) *blifNet {
	n := &blifNet{}
	lines := strings.Split(text, "\n")
	for i := 0; i < len(lines); i++ {
		f := strings.Fields(lines[i])
		if len(f) == 0 {
			continue
		}
		switch f[0] {
		case ".inputs":
			n.inputs = f[1:]
		case ".outputs":
			n.outputs = f[1:]
		case ".latch":
			n.latches = append(n.latches, struct {
				d, q string
				init int
			}{f[1], f[2], int(f[len(f)-1][0] - '0')})
		case ".names":
			e := struct {
				ins  []string
				out  string
				rows []string
			}{ins: f[1 : len(f)-1], out: f[len(f)-1]}
			for i+1 < len(lines) && len(lines[i+1]) > 0 && lines[i+1][0] != '.' {
				i++
				e.rows = append(e.rows, lines[i])
			}
			n.names = append(n.names, e)
		}
	}
	return n
}

func (n *blifNet) eval(in map[string]bool, state map[string]bool) map[string]bool {
	val := map[string]bool{}
	for k, v := range in {
		val[k] = v
	}
	for k, v := range state {
		val[k] = v
	}
	for changed := true; changed; {
		changed = false
		for _, e := range n.names {
			if _, done := val[e.out]; done {
				continue
			}
			ready := true
			for _, s := range e.ins {
				if _, ok := val[s]; !ok {
					ready = false
				}
			}
			if !ready {
				continue
			}
			res := false
			for _, row := range e.rows {
				f := strings.Fields(row)
				if len(e.ins) == 0 {
					res = f[0] == "1"
					continue
				}
				match := true
				for i, s := range e.ins {
					if (f[0][i] == '1') != val[s] {
						match = false
					}
				}
				if match {
					res = f[1] == "1"
				}
			}
			val[e.out] = res
			changed = true
		}
	}
	return val
}

func TestBLIFMatchesSimulation(t *testing.T) {
	for name, src := range designs {
		g := testutil.Build(t, src, "")
		var buf bytes.Buffer
		if err := emit.BLIF(&buf, g, "m"); err != nil {
			t.Fatal(err)
		}
		net := parseBLIF(t, buf.String())
		sim := aig.NewSimulator(g)
		state := map[string]bool{}
		for _, l := range net.latches {
			state[l.q] = l.init == 1
		}
		rng := rand.New(rand.NewSource(9))
		for cyc := 0; cyc < 60; cyc++ {
			in := map[string]bool{}
			for i, pi := range g.PIs {
				b := rng.Intn(2) == 1
				w := uint64(0)
				if b {
					w = ^uint64(0)
				}
				sim.SetPI(i, w)
				nm := pi.Port
				if p := g.FindInput(pi.Port); len(p.Bits) > 1 {
					nm = fmt.Sprintf("%s[%d]", pi.Port, pi.Bit)
				}
				in[nm] = b
			}
			sim.Eval()
			val := net.eval(in, state)
			for _, p := range g.Outputs {
				for i, bit := range p.Bits {
					nm := p.Name
					if len(p.Bits) > 1 {
						nm = fmt.Sprintf("%s[%d]", p.Name, i)
					}
					if (sim.Lit(bit)&1 == 1) != val[nm] {
						t.Fatalf("%s: cycle %d output %s differs between BLIF and simulator", name, cyc, nm)
					}
				}
			}
			next := map[string]bool{}
			for _, l := range net.latches {
				next[l.q] = val[l.d]
			}
			state = next
			sim.Clock(nil)
		}
	}
}

func TestExamplesEmitAndReparse(t *testing.T) {
	entries, err := os.ReadDir("../../examples")
	if err != nil {
		t.Skip("examples not found")
	}
	for _, e := range entries {
		if !strings.HasSuffix(e.Name(), ".v") {
			continue
		}
		src, _ := os.ReadFile("../../examples/" + e.Name())
		f, err := hdl.Parse(e.Name(), string(src))
		if err != nil {
			t.Fatal(err)
		}
		g, err := elab.Elaborate([]*hdl.File{f}, elab.Options{})
		if err != nil {
			t.Fatalf("%s: %v", e.Name(), err)
		}
		var buf bytes.Buffer
		if err := emit.Verilog(&buf, g, "rt"); err != nil {
			t.Fatal(err)
		}
		f2, err := hdl.Parse("rt.v", buf.String())
		if err != nil {
			t.Fatalf("%s: re-parse: %v", e.Name(), err)
		}
		g2, err := elab.Elaborate([]*hdl.File{f2}, elab.Options{})
		if err != nil {
			t.Fatalf("%s: re-elaborate: %v", e.Name(), err)
		}
		equivalent(t, e.Name(), g, g2)
	}
}
