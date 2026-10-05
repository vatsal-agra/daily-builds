package expr

import (
	"math"
	"math/rand"
	"testing"
)

var names = []string{"x", "y"}

func mustParse(t *testing.T, s string) *Node {
	t.Helper()
	n, err := Parse(s, names)
	if err != nil {
		t.Fatalf("parse %q: %v", s, err)
	}
	return n
}

func TestParseEval(t *testing.T) {
	cases := []struct {
		src  string
		want float64
	}{
		{"1+2*3", 7}, {"(1+2)*3", 9}, {"2^3^2", 512}, {"-2^2", -4}, {"2^-1", 0.5},
		{"x*y", 12}, {"x**2", 9}, {"sqrt(16)+log(e)", 5}, {"sin(0)+cos(0)", 1},
		{"10/4", 2.5}, {"1e2+1.5e-1", 100.15}, {"abs(-3)", 3}, {"2*pi", 2 * math.Pi}, {"ln(e)", 1},
		{"8-3-2", 3}, {"8/4/2", 1}, {"--x", 3},
	}
	for _, c := range cases {
		got := mustParse(t, c.src).Eval([]float64{3, 4})
		if math.Abs(got-c.want) > 1e-12 {
			t.Errorf("%s = %v, want %v", c.src, got, c.want)
		}
	}
}

func TestParseErrors(t *testing.T) {
	for _, s := range []string{"", "1+", "(1", "1)", "foo(1)", "z+1", "1 2", "2x", "sin(", "^2", "1..2"} {
		if _, err := Parse(s, names); err == nil {
			t.Errorf("expected error for %q", s)
		}
	}
}

func TestDomainErrorsAreNaN(t *testing.T) {
	for _, s := range []string{"1/0", "log(0)", "log(-1)", "sqrt(-1)", "(-8)^0.5", "0^-1", "exp(1000)"} {
		if v := mustParse(t, s).Eval([]float64{0, 0}); !math.IsNaN(v) {
			t.Errorf("%s = %v, want NaN", s, v)
		}
	}
}

func TestPrintRoundTrip(t *testing.T) {
	for _, s := range []string{"x + y * 2", "(x + y) * 2", "x - (y - 1)", "x / (y * 2)", "-(x + y)", "x^(y + 1)", "(x^2)^3", "sin(x) ^ 2", "-x ^ 2", "2 ^ -x", "x - y - 1"} {
		n := mustParse(t, s)
		again := mustParse(t, n.Format(names))
		for _, in := range [][]float64{{1.3, 2.1}, {0.4, 0.9}} {
			a, b := n.Eval(in), again.Eval(in)
			if math.Abs(a-b) > 1e-12*(1+math.Abs(a)) {
				t.Errorf("%q printed as %q evaluates differently: %v vs %v", s, n.Format(names), a, b)
			}
		}
	}
}

func TestSimplifyKnown(t *testing.T) {
	cases := map[string]string{
		"x + 0": "x", "0 + x": "x", "x * 1": "x", "x*0": "0", "x - x": "0", "x / x": "1",
		"x^1": "x", "x^0": "1", "2 + 3": "5", "x + x": "2 * x", "x * x": "x^2",
		"x^3 - x - x": "x^3 - 2 * x", "-(-x)": "x", "x - -y": "x + y", "exp(log(x))": "x",
		"sqrt(x^2)": "abs(x)", "x*y*x/x": "x * y", "2*x/4": "0.5 * x", "x + 1 + 2": "x + 3",
	}
	for src, want := range cases {
		got := Simplify(mustParse(t, src)).Format(names)
		if got != want {
			t.Errorf("simplify %q = %q, want %q", src, got, want)
		}
	}
}

func randTree(r *rand.Rand, d int) *Node {
	if d == 0 || r.Intn(4) == 0 {
		if r.Intn(2) == 0 {
			return V(r.Intn(2))
		}
		return C(float64(r.Intn(7) - 3))
	}
	if r.Intn(5) == 0 {
		return U([]string{"neg", "sin", "cos", "abs"}[r.Intn(4)], randTree(r, d-1))
	}
	op := []string{"+", "-", "*", "/", "+", "*"}[r.Intn(6)]
	return B(op, randTree(r, d-1), randTree(r, d-1))
}

// Property: simplification never changes the function where the original is defined.
func TestSimplifyPreservesValue(t *testing.T) {
	r := rand.New(rand.NewSource(42))
	checked := 0
	for i := 0; i < 4000; i++ {
		n := randTree(r, 5)
		s := Simplify(n)
		if s.Size() > n.Size()+2 {
			t.Fatalf("simplify grew %v -> %v", n, s)
		}
		for k := 0; k < 4; k++ {
			in := []float64{r.Float64()*6 - 3, r.Float64()*6 - 3}
			a, b := n.Eval(in), s.Eval(in)
			if math.IsNaN(a) || math.IsInf(a, 0) || math.Abs(a) > 1e8 {
				continue
			}
			checked++
			if math.IsNaN(b) || math.Abs(a-b) > 1e-7*(1+math.Abs(a)) {
				t.Fatalf("simplify changed value: %v -> %v at %v: %v vs %v", n, s, in, a, b)
			}
		}
	}
	if checked < 5000 {
		t.Fatalf("only %d checks ran", checked)
	}
}

func TestDiffMatchesFiniteDifference(t *testing.T) {
	forms := []string{"x^2*sin(x)", "exp(2*x)/(1+x^2)", "sqrt(x)*log(x)", "x^x", "cos(x*y)+y", "x^y", "(x+y)^3", "abs(x)*x", "1/x", "sin(cos(x))"}
	for _, f := range forms {
		n := mustParse(t, f)
		d, err := Diff(n, 0)
		if err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		for _, x := range []float64{0.7, 1.9, 2.6} {
			in := []float64{x, 1.3}
			h := 1e-6
			num := (n.Eval([]float64{x + h, 1.3}) - n.Eval([]float64{x - h, 1.3})) / (2 * h)
			got := d.Eval(in)
			if math.Abs(got-num) > 1e-4*(1+math.Abs(num)) {
				t.Errorf("d/dx %s at %v: symbolic %v (%s) vs numeric %v", f, x, got, d.Format(names), num)
			}
		}
	}
	// derivative w.r.t. other variable
	d, _ := Diff(mustParse(t, "x*y^2"), 1)
	if got := Simplify(d).Format(names); got != "2 * x * y" && got != "x * 2 * y" {
		t.Errorf("d/dy x*y^2 = %s", got)
	}
}

func TestComplexityAndSize(t *testing.T) {
	n := mustParse(t, "x*y+1")
	if n.Size() != 5 {
		t.Errorf("size %d", n.Size())
	}
	if n.Complexity() != 1+2+1+1+1 {
		t.Errorf("complexity %d", n.Complexity())
	}
	c := n.Clone()
	c.L.L.Idx = 1
	if n.L.L.Idx != 0 {
		t.Error("clone is shallow")
	}
}
