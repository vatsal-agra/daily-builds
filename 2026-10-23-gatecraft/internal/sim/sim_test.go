package sim_test

import (
	"bufio"
	"math/big"
	"strings"
	"testing"

	"gatecraft/internal/sim"
	"gatecraft/internal/testutil"
)

const hier = `
module acc(input clk, input rst, input [3:0] d, output [7:0] total);
  reg [7:0] sum;
  always @(posedge clk) if (rst) sum <= 0; else sum <= sum + d;
  assign total = sum;
endmodule
module top(input clk, input rst, input [3:0] d, output [7:0] total, output big);
  acc u0(.clk(clk), .rst(rst), .d(d), .total(total));
  assign big = total > 8'd20;
endmodule`

// parseVCD returns, per signal path, the list of (time, value) changes.
func parseVCD(t *testing.T, text string) map[string][][2]int64 {
	t.Helper()
	ids := map[string]string{}
	var scope []string
	out := map[string][][2]int64{}
	sc := bufio.NewScanner(strings.NewReader(text))
	var now int64
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) == 0 {
			continue
		}
		switch {
		case f[0] == "$scope":
			scope = append(scope, f[2])
		case f[0] == "$upscope":
			scope = scope[:len(scope)-1]
		case f[0] == "$var":
			ids[f[3]] = strings.Join(append(append([]string{}, scope...), f[4]), ".")
		case strings.HasPrefix(f[0], "#"):
			v, _ := new(big.Int).SetString(f[0][1:], 10)
			now = v.Int64()
		case f[0][0] == 'b':
			v, _ := new(big.Int).SetString(f[0][1:], 2)
			out[ids[f[1]]] = append(out[ids[f[1]]], [2]int64{now, v.Int64()})
		case (f[0][0] == '0' || f[0][0] == '1') && len(f[0]) > 1:
			out[ids[f[0][1:]]] = append(out[ids[f[0][1:]]], [2]int64{now, int64(f[0][0] - '0')})
		}
	}
	return out
}

func TestVCDMatchesSimulationAndHierarchy(t *testing.T) {
	g := testutil.Build(t, hier, "top")
	s := sim.New(g)
	var buf strings.Builder
	s.AttachVCD(sim.NewVCD(&buf))
	script := `
set rst 1
tick
set rst 0
set d 7
tick 4
set d 1
tick 2
`
	if _, err := s.RunScript(strings.NewReader(script), &strings.Builder{}); err != nil {
		t.Fatal(err)
	}
	s.Finish()
	vcd := parseVCD(t, buf.String())
	// hierarchical scope present
	if _, ok := vcd["u0.sum"]; !ok {
		t.Fatalf("expected u0.sum in VCD, have %v", keys(vcd))
	}
	// value of the accumulator after each edge: 0, 7, 14, 21, 28, 29, 30
	want := []int64{0, 7, 14, 21, 28, 29, 30}
	var got []int64
	for _, c := range vcd["total"] {
		if c[0]%10 == 5 || c[0] == 0 { // post-edge samples
			got = append(got, c[1])
		}
	}
	// de-dup consecutive duplicates is not needed: only changes are recorded
	if len(got) != len(want) {
		t.Fatalf("total changes %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("total changes %v, want %v", got, want)
		}
	}
	// clock toggles: high at x5, low at the next x0 sample
	clk := vcd["clk"]
	if len(clk) < 6 || clk[1][1] != 1 || clk[2][1] != 0 {
		t.Fatalf("clock waveform wrong: %v", clk)
	}
	// 'big' becomes 1 exactly when total > 20 (after the 4th edge in this script)
	for _, c := range vcd["big"] {
		if c[1] == 1 && c[0] != 35 {
			t.Fatalf("big rose at t=%d, expected 35", c[0])
		}
	}
}

func keys(m map[string][][2]int64) []string {
	var k []string
	for n := range m {
		k = append(k, n)
	}
	return k
}

func TestScriptErrorsAreReported(t *testing.T) {
	g := testutil.Build(t, hier, "top")
	cases := map[string]string{
		"set nosuch 1":     "no input port",
		"set d 99":         "does not fit",
		"expect zzz 1":     "unknown signal",
		"frobnicate":       "unknown command",
		"repeat 3\ntick":   "without matching",
		"end":              "without 'repeat'",
		"set d":            "usage",
		"tick nosuchclk":   "not a clock",
		"expect total ~ 1": "unknown comparison",
	}
	for src, want := range cases {
		s := sim.New(g)
		_, err := s.RunScript(strings.NewReader(src), &strings.Builder{})
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: want error containing %q, got %v", src, want, err)
		}
	}
}

func TestExpectFailureIsCountedNotFatal(t *testing.T) {
	g := testutil.Build(t, hier, "top")
	s := sim.New(g)
	var out strings.Builder
	res, err := s.RunScript(strings.NewReader("set d 5\nset rst 0\ntick 2\nexpect total 11\nexpect total != 11\nexpect total >= 10\n"), &out)
	if err != nil {
		t.Fatal(err)
	}
	if res.Checks != 3 || len(res.Failures) != 1 || !strings.Contains(out.String(), "expected total == 11, got 10") {
		t.Fatalf("checks=%d failures=%v out=%q", res.Checks, res.Failures, out.String())
	}
}

func TestCombinationalDesignCannotTick(t *testing.T) {
	g := testutil.Build(t, "module m(input a, output y); assign y = ~a; endmodule", "")
	s := sim.New(g)
	if err := s.Tick("", 1); err == nil || !strings.Contains(err.Error(), "no flip-flops") {
		t.Fatalf("got %v", err)
	}
}

func TestRepeatAndRandomizeAreDeterministic(t *testing.T) {
	g := testutil.Build(t, hier, "top")
	run := func() string {
		s := sim.New(g)
		var out strings.Builder
		_, err := s.RunScript(strings.NewReader("seed 5\nrepeat 6\nrandomize d\ntick\nprint total\nend\n"), &out)
		if err != nil {
			t.Fatal(err)
		}
		return out.String()
	}
	a, b := run(), run()
	if a != b || strings.Count(a, "total") != 6 {
		t.Fatalf("not deterministic or wrong count:\n%s\n%s", a, b)
	}
}

func TestParseValue(t *testing.T) {
	for in, want := range map[string]int64{"42": 42, "0x2a": 42, "0b101010": 42, "8'h2a": 42, "'d42": 42, "4'b1_010": 10} {
		v, err := sim.ParseValue(in)
		if err != nil || v.Int64() != want {
			t.Errorf("%s: %v %v", in, v, err)
		}
	}
	if _, err := sim.ParseValue("zz"); err == nil {
		t.Error("expected error")
	}
}
