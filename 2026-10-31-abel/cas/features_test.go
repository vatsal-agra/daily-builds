package cas

import (
	"strings"
	"testing"
)

func eval1(t *testing.T, s *Session, line string) string {
	t.Helper()
	out, err := s.Eval(line)
	if err != nil {
		t.Fatalf("%s: unexpected error: %v", line, err)
	}
	return strings.Join(out, "\n")
}

func TestSimplifierTable(t *testing.T) {
	cases := map[string]string{
		"2*(x+1) - 2*x":     "2",
		"sin(x)^2+cos(x)^2": "1",
		"1-cos(x)^2":        "sin(x)^2",
		"e^(i*pi)":          "-1",
		"e^(i*pi/2)":        "i",
		"1/(1+sqrt(2))":     "sqrt(2) - 1",
		"1/(1+i)":           "-i/2 + 1/2",
		"(x^2-1)/(x-1)":     "(x^2 - 1)/(x - 1)",
		"sqrt(50)":          "5*sqrt(2)",
		"sqrt(1/2)":         "sqrt(2)/2",
		"12^(1/3)":          "12^(1/3)",
		"2^(1/3)*4^(1/3)":   "2",
		"(1/8)^(1/3)":       "1/2",
		"x^2*x^3/x^4":       "x",
		"exp(x)*exp(-x)":    "1",
		"ln(exp(5))":        "5",
		"exp(ln(x))":        "x",
		"exp(2*ln(x))":      "x^2",
		"sin(-x)":           "-sin(x)",
		"cos(-x)":           "cos(x)",
		"sin(pi/3)":         "sqrt(3)/2",
		"cos(2*pi/3)":       "-1/2",
		"sin(7*pi/4)":       "-sqrt(2)/2",
		"atan(1)":           "pi/4",
		"0.25 + 1/4":        "1/2",
		"-(x+1)":            "-(x + 1)",
		"x - (x+1)":         "-1",
		"(2*x+2)^-1":        "1/(2*(x + 1))",
		"3*x^2 - x^2*3 + 1": "1",
		"(a+b)^2 - a^2":     "-a^2 + (a + b)^2",
		"i*i":               "-1",
		"i^5":               "i",
		"2e3":               "2000",
	}
	for in, want := range cases {
		e, err := Parse(in)
		if err != nil {
			t.Errorf("%s: %v", in, err)
			continue
		}
		if got := e.String(); got != want {
			t.Errorf("%s => %s, want %s", in, got, want)
		}
	}
	if !Equal(Expand(MustParse("(a+b)^2 - a^2")), MustParse("2*a*b + b^2")) {
		t.Error("expand((a+b)^2-a^2) wrong")
	}
}

func TestParserErrors(t *testing.T) {
	bad := []string{"", "(", "2 +", "3 $ 4", "sin()", "sin(1,2)", "foo(x)", "x^", "[[1,2],[3]]", "1/0", "0^-1", "ln(0)", "tan(pi/2)", "((", ")", "2 3 )"}
	for _, in := range bad {
		if _, err := Parse(in); err == nil {
			t.Errorf("Parse(%q) should fail", in)
		}
	}
	deep := strings.Repeat("(", 5000) + "1" + strings.Repeat(")", 5000)
	if _, err := Parse(deep); err == nil || !strings.Contains(err.Error(), "nested") {
		t.Errorf("deep nesting must be rejected cleanly, got %v", err)
	}
	if _, err := Parse("x +"); err == nil || !strings.Contains(err.Error(), "^") {
		t.Errorf("errors should carry a caret position: %v", err)
	}
}

func TestDerivativesTable(t *testing.T) {
	cases := map[string]string{
		"x^3":           "3*x^2",
		"sin(x)*cos(x)": "-sin(x)^2 + cos(x)^2",
		"ln(x)/x":       "-ln(x)/x^2 + 1/x^2",
		"x^x":           "x^x*(ln(x) + 1)",
		"e^(x^2)":       "2*x*e^(x^2)",
		"atan(x)":       "1/(x^2 + 1)",
		"sqrt(x)":       "1/(2*sqrt(x))",
		"tan(x)":        "1/cos(x)^2",
		"2^x":           "ln(2)*2^x",
		"sinh(x)":       "cosh(x)",
		"asin(x)":       "1/sqrt(-x^2 + 1)",
		"x*y":           "y",
		"5":             "0",
	}
	for in, want := range cases {
		got := Diff(MustParse(in), "x").String()
		if got != want {
			t.Errorf("d/dx %s = %s, want %s", in, got, want)
		}
	}
	if got := DiffN(MustParse("x^5"), "x", 3).String(); got != "60*x^2" {
		t.Errorf("third derivative: %s", got)
	}
	if got := Diff(MustParse("f"), "x"); !isNumVal(got, 0) {
		t.Errorf("symbol constant: %s", got)
	}
}

func TestFactorTable(t *testing.T) {
	cases := map[string]string{
		"x^2-1":               "(x - 1)*(x + 1)",
		"x^4+4":               "(x^2 - 2*x + 2)*(x^2 + 2*x + 2)",
		"2*x^3-3*x^2-11*x+6":  "(2*x - 1)*(x - 3)*(x + 2)",
		"x^2+1":               "x^2 + 1",
		"(x-1)^3*(x+2)^2":     "(x - 1)^3*(x + 2)^2",
		"6*x^2+5*x+1":         "(2*x + 1)*(3*x + 1)",
		"x^2/4-1":             "(x - 2)*(x + 2)/4",
		"(x^2-1)/(x^2-2*x+1)": "(x + 1)/(x - 1)",
		"x^6+1":               "(x^2 + 1)*(x^4 - x^2 + 1)",
		"x^3-2":               "x^3 - 2",
		"-x^2+1":              "-(x - 1)*(x + 1)",
	}
	for in, want := range cases {
		got := Factor(MustParse(in), "x").String()
		if got != want {
			t.Errorf("factor %s = %s, want %s", in, got, want)
		}
		if !numericallyEqual(Factor(MustParse(in), "x"), MustParse(in)) {
			t.Errorf("factor(%s) changed the value", in)
		}
	}
	if g := PolyGCD(MustParse("x^2-1"), MustParse("x^2-2*x+1"), "x"); g.String() != "x - 1" {
		t.Errorf("gcd: %s", g)
	}
}

func TestSolveExactForms(t *testing.T) {
	cases := map[string][]string{
		"x^2-2=0":          {"-sqrt(2)", "sqrt(2)"},
		"x^2+1=0":          {"-i", "i"},
		"2*x+3=0":          {"-3/2"},
		"x^3-6*x^2+11*x=6": {"1", "2", "3"},
		"x^4-5*x^2+4=0":    {"-2", "-1", "1", "2"},
		"1/x=4":            {"1/4"},
		"(x^2-1)/(x-1)=0":  {"-1"},
	}
	for in, want := range cases {
		roots := Solve(MustParse(in), "x")
		var got []string
		for _, r := range roots {
			got = append(got, r.Exact.String())
		}
		if strings.Join(got, ",") != strings.Join(want, ",") {
			t.Errorf("solve %s = %v, want %v", in, got, want)
		}
	}
	if roots := Solve(MustParse("x^3-x-1=0"), "x"); len(roots) != 3 || roots[0].Exact != nil {
		t.Errorf("irreducible cubic should return 3 numeric roots, got %v", roots)
	}
	if err := Guard(func() { Solve(MustParse("sin(x)=0"), "x") }); err == nil {
		t.Error("non-polynomial equation must be refused")
	}
	if err := Guard(func() { Solve(MustParse("x=x"), "x") }); err == nil {
		t.Error("identity must be reported")
	}
}

var integrands = []string{
	"x^2+3x+1", "1/x", "1/(2x+3)", "sqrt(x)", "1/sqrt(x)", "x/sqrt(x^2+1)", "2^x", "a*x", "sin(a*x)", "x*e^(-x)",
	"sin(x)^2", "cos(x)^3", "sin(x)^3*cos(x)^2", "sin(x)^4", "sin(x)*cos(x)", "sin(2x)*cos(3x)", "sin(x)*sin(3x)", "cos(x)*cos(2x)",
	"tan(x)", "tan(x)^2", "tan(x)^3", "sec(x)^2", "sec(x)", "csc(x)^2", "1/sin(x)",
	"atan(x)", "x*atan(x)", "asin(x)", "ln(x)", "x*ln(x)", "ln(x)^2", "x^2*ln(x)", "ln(x)/x", "1/(x*ln(x))",
	"e^x*sin(x)", "e^x*cos(2x)", "e^(2x)*sin(3x)", "x*e^x", "x^2*e^x", "x^8*e^x", "x^3*sin(2x)", "x^2*cos(x)",
	"x*e^(x^2)", "x^3*e^(x^2)", "cos(x)*e^(sin(x))", "e^x/(1+e^x)", "1/(1+e^x)",
	"1/(x^2+1)", "1/(x^2-1)", "1/(x^2-2)", "1/(x^2+2x+5)", "(3x+2)/(x^2+2x+5)", "1/(x^2+1)^2", "1/(x^2+x+1)^2",
	"x^2/(x^2+1)", "1/(x^3-x)", "1/(x*(x+1)^2)", "1/(x^4-1)", "(x^3+2x)/(x^2+1)^2", "1/((x-1)*(x-2)*(x-3))", "x^5/(x^2+1)",
	"sqrt(1-x^2)", "1/sqrt(1-x^2)", "sqrt(x^2+1)", "1/sqrt(x^2+4)", "1/sqrt(3-2x-x^2)", "x*sqrt(x+1)", "abs(x)",
	"(2x+1)^5", "1/(3x-2)^3", "sinh(x)", "cosh(2x)", "tanh(x)", "x*sin(x)^2",
}

func TestIntegrationCertified(t *testing.T) {
	for _, in := range integrands {
		f := MustParse(in)
		F, err := Integrate(f, "x")
		if err != nil {
			t.Errorf("integrate %s: %v", in, err)
			continue
		}
		if ok, detail := Verify(f, F, "x"); !ok {
			t.Errorf("integrate %s = %s failed certification: %s", in, F, detail)
		}
	}
}

func TestIntegrationRefusesNonElementary(t *testing.T) {
	for _, in := range []string{"e^(x^2)", "e^(-x^2)", "sin(x)/x", "x^x", "ln(x)/(x+1)", "1/(x^4+1)", "sin(x^2)"} {
		if F, err := Integrate(MustParse(in), "x"); err == nil {
			t.Errorf("integrate %s should fail honestly but returned %s", in, F)
		}
	}
}

func TestVerifyRejectsWrongAntiderivatives(t *testing.T) {
	wrong := [][2]string{{"x^2", "x^3/2"}, {"sin(x)", "cos(x)"}, {"1/x", "ln(x)+x"}, {"e^x", "e^x+x"}, {"x*e^x", "x*e^x"}, {"1/(1+x^2)", "ln(1+x^2)"}}
	for _, w := range wrong {
		if ok, _ := Verify(MustParse(w[0]), MustParse(w[1]), "x"); ok {
			t.Errorf("Verify accepted %s as an antiderivative of %s", w[1], w[0])
		}
	}
	if ok, _ := Verify(MustParse("x*e^x"), MustParse("x*e^x-e^x"), "x"); !ok {
		t.Error("Verify rejected a correct antiderivative")
	}
}

func TestDefiniteAndImproperIntegrals(t *testing.T) {
	cases := []struct{ f, a, b, want string }{
		{"x", "0", "2", "2"},
		{"sin(x)", "0", "pi", "2"},
		{"1/x", "1", "e", "1"},
		{"ln(x)", "0", "1", "-1"},
		{"1/sqrt(x)", "0", "1", "2"},
		{"e^(-x)", "0", "oo", "1"},
		{"1/(1+x^2)", "-oo", "oo", "pi"},
		{"1/x^2", "1", "oo", "1"},
		{"x*e^(-x^2)", "0", "oo", "1/2"},
		{"ln(x)/x^2", "1", "oo", "1"},
		{"x^2", "a", "b", "-a^3/3 + b^3/3"},
	}
	for _, c := range cases {
		got, _, err := DefiniteIntegral(MustParse(c.f), "x", MustParse(c.a), MustParse(c.b))
		if err != nil {
			t.Errorf("∫%s [%s,%s]: %v", c.f, c.a, c.b, err)
			continue
		}
		if got.String() != c.want {
			t.Errorf("∫%s [%s,%s] = %s, want %s", c.f, c.a, c.b, got, c.want)
		}
	}
	for _, c := range [][3]string{{"1/x", "0", "1"}, {"1/x^2", "-1", "1"}, {"1/(x-1)", "0", "2"}, {"1/x", "1", "oo"}, {"x", "0", "oo"}} {
		if got, _, err := DefiniteIntegral(MustParse(c[0]), "x", MustParse(c[1]), MustParse(c[2])); err == nil {
			t.Errorf("∫%s [%s,%s] should be refused, got %s", c[0], c[1], c[2], got)
		}
	}
}

func TestLimits(t *testing.T) {
	cases := []struct {
		e, x, a string
		dir     int
		want    string
	}{
		{"sin(x)/x", "x", "0", 0, "1"},
		{"(1-cos(x))/x^2", "x", "0", 0, "1/2"},
		{"(x^2-1)/(x-1)", "x", "1", 0, "2"},
		{"(1+x)^(1/x)", "x", "0", 0, "e"},
		{"x*ln(x)", "x", "0", 1, "0"},
		{"ln(x)/x", "x", "oo", 0, "0"},
		{"(1+1/x)^x", "x", "oo", 0, "e"},
		{"e^(-x)", "x", "oo", 0, "0"},
		{"x*e^(-x)", "x", "oo", 0, "0"},
		{"x^3/e^x", "x", "oo", 0, "0"},
		{"1/x", "x", "0", 1, "oo"},
		{"1/x", "x", "0", -1, "-oo"},
		{"1/x^2", "x", "0", 0, "oo"},
		{"x^2", "x", "oo", 0, "oo"},
		{"(3x^2+1)/(x^2-5)", "x", "oo", 0, "3"},
		{"atan(x)", "x", "-oo", 0, "-pi/2"},
		{"(e^x-1)/x", "x", "0", 0, "1"},
		{"x^x", "x", "0", 1, "1"},
		{"x^2+3", "x", "2", 0, "7"},
	}
	for _, c := range cases {
		got, err := func() (r E, err error) {
			err = Guard(func() { r = Limit(MustParse(c.e), c.x, MustParse(c.a), c.dir) })
			return
		}()
		if err != nil || got.String() != c.want {
			t.Errorf("limit %s as %s->%s (dir %d) = %v (%v), want %s", c.e, c.x, c.a, c.dir, got, err, c.want)
		}
	}
	for _, c := range [][2]string{{"1/x", "0"}, {"sin(x)", "oo"}} {
		if err := Guard(func() { Limit(MustParse(c[0]), "x", MustParse(c[1]), 0) }); err == nil {
			t.Errorf("limit of %s at %s should be reported as nonexistent", c[0], c[1])
		}
	}
}

func TestTaylor(t *testing.T) {
	cases := map[string]string{
		"sin(x)":  "-x^7/5040 + x^5/120 - x^3/6 + x",
		"e^x":     "x^7/5040 + x^6/720 + x^5/120 + x^4/24 + x^3/6 + x^2/2 + x + 1",
		"1/(1-x)": "x^7 + x^6 + x^5 + x^4 + x^3 + x^2 + x + 1",
		"cos(x)":  "-x^6/720 + x^4/24 - x^2/2 + 1",
		"atan(x)": "-x^7/7 + x^5/5 - x^3/3 + x",
	}
	for in, want := range cases {
		if got := Taylor(MustParse(in), "x", Zero, 7).String(); got != want {
			t.Errorf("taylor %s = %s, want %s", in, got, want)
		}
	}
	// numeric sanity at a nonzero centre
	tp := Taylor(MustParse("ln(x)"), "x", One, 12)
	v, _ := EvalReal(tp, map[string]float64{"x": 1.1})
	if d := v - 0.09531017980432487; d > 1e-9 || d < -1e-9 {
		t.Errorf("taylor ln about 1 off by %g", d)
	}
	if err := Guard(func() { Taylor(MustParse("1/x"), "x", Zero, 3) }); err == nil {
		t.Error("series at a pole must fail")
	}
}

func TestMatrixCommands(t *testing.T) {
	s := NewSession()
	checks := map[string]string{
		"det([[1,2],[3,4]])":                 "-2",
		"det([[a,b],[c,d]])":                 "-b*c + a*d",
		"rank([[1,2],[2,4]])":                "1",
		"[[1,2],[3,4]]^2":                    "[[7, 10], [15, 22]]",
		"[[1,2],[3,4]]*[[1],[1]]":            "[[3], [7]]",
		"transpose([[1,2],[3,4]])":           "| 1  3 |\n| 2  4 |",
		"inv([[2,0],[0,4]])":                 "| 1/2    0 |\n|   0  1/4 |",
		"charpoly([[1,2],[3,4]], t)":         "t^2 - 5*t - 2",
		"linsolve([[2,1],[1,3]],[[5],[10]])": "| 1 |\n| 3 |",
	}
	for in, want := range checks {
		if got := eval1(t, s, in); got != want {
			t.Errorf("%s =>\n%s\nwant\n%s", in, got, want)
		}
	}
	got := eval1(t, s, "eigen([[2,1],[1,2]])")
	for _, frag := range []string{"lambda = 1", "lambda = 3", "eigenvector: (-1, 1)^T", "eigenvector: (1, 1)^T"} {
		if !strings.Contains(got, frag) {
			t.Errorf("eigen output lacks %q:\n%s", frag, got)
		}
	}
	for _, bad := range []string{"inv([[1,2],[2,4]])", "det([[1,2,3],[4,5,6]])", "[[1,2],[3,4]]+[[1],[2]]", "inv([[a,b],[c,d]])", "linsolve([[1,1],[1,1]],[[1],[2]])"} {
		if _, err := s.Eval(bad); err == nil {
			t.Errorf("%s should fail", bad)
		}
	}
}

func TestSessionAndCommands(t *testing.T) {
	s := NewSession()
	if got := eval1(t, s, "a = 3"); got != "a = 3" {
		t.Error(got)
	}
	if got := eval1(t, s, "b = a^2 + 1"); got != "b = 10" {
		t.Error(got)
	}
	if got := eval1(t, s, "diff(x^2*a, x)"); got != "6*x" {
		t.Error(got)
	}
	if got := eval1(t, s, "ans"); got != "6*x" {
		t.Error(got)
	}
	if got := eval1(t, s, "solve([x+y=3, x-y=1],[x,y])"); got != "x = 2\ny = 1" {
		t.Error(got)
	}
	if got := eval1(t, s, "equal((x+1)^2, x^2+2x+1)"); !strings.HasPrefix(got, "true") {
		t.Error(got)
	}
	if got := eval1(t, s, "equal(x+1, x+2)"); got != "false" {
		t.Error(got)
	}
	if got := eval1(t, s, "N(sqrt(2))"); got != "1.414213562" {
		t.Error(got)
	}
	if got := eval1(t, s, "integrate(x*sin(x), x)"); !strings.Contains(got, "certified") {
		t.Error(got)
	}
	if got := eval1(t, s, "apart(1/(x^2-1), x)"); got != "-1/(2*(x + 1)) + 1/(2*(x - 1))" {
		t.Error(got)
	}
	if got := eval1(t, s, "together(1/x+1/(x+1), x)"); got != "(2*x + 1)/(x^2 + x)" {
		t.Error(got)
	}
	if got := eval1(t, s, "subst(x^2+y, x, 3)"); got != "y + 9" {
		t.Error(got)
	}
	if got := eval1(t, s, "help"); !strings.Contains(got, "integrate(expr, x") {
		t.Error("help text missing")
	}
	for _, bad := range []string{"integrate(e^(x^2), x)", "factor(sin(x))", "solve(y=2, x)", "diff(x^2)", "taylor(1/x, x, 0, 3)", "gcd(x, y)", "foo(x)", "diff(x, 3)"} {
		if _, err := s.Eval(bad); err == nil {
			t.Errorf("%s should produce an error", bad)
		}
	}
	// the session survives errors
	if got := eval1(t, s, "1+1"); got != "2" {
		t.Error(got)
	}
}

func TestNeverPanics(t *testing.T) {
	s := NewSession()
	junk := []string{"((((", "))))", "x^^2", "[[", "]]", "[]", "[[1,2],[3,4]]^x", "integrate()", "solve()", "limit(x)", "taylor(x,x,0,-5)",
		"taylor(sin(x),x,0,1000)", "diff(sin(x), x, 100)", "2^2^2^2^2", "x^(1/0)", "factor(0)", "factor(1000000007)", "integrate(0, x)", "solve(0=0,x)",
		"[1,2][3]", "det([])", "inv(5)", "nroots(5)", "nroots(sin(x))", "gcd(0,0)", "apart(0,x)", "together(0,x)", "N(x)", "N(1/0)", "eigen(5)", "vars", "ans", "oo-oo", "limit(1/0,x,0)"}
	for _, in := range junk {
		_, err := s.Eval(in)
		if err != nil && strings.Contains(err.Error(), "internal error") {
			t.Errorf("%q hit an internal error: %v", in, err)
		}
	}
}
