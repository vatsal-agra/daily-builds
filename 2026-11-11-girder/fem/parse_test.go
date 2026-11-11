package fem

import (
	"math"
	"strings"
	"testing"
)

func TestParseSolveCantilever(t *testing.T) {
	src := `
title t
material E=200000 nu=0.3 t=10
mesh rect w=100 h=10 nx=40 ny=4 type=quad4   # comment
fix where x==0 dofs=xy
traction where x==100 tx=0 ty=-5
`
	in, err := Parse(src)
	if err != nil {
		t.Fatal(err)
	}
	sol, err := in.Solid.Solve(SolverDirect)
	if err != nil {
		t.Fatal(err)
	}
	// total reaction must equal the applied line load 5*10*10
	ry := 0.0
	for i := range in.Solid.Mesh.X {
		ry += sol.R[2*i+1]
	}
	if math.Abs(ry-500) > 1e-6 {
		t.Errorf("reaction %g want 500", ry)
	}
}

func TestParseErrorsHaveLineNumbers(t *testing.T) {
	cases := map[string]string{
		"material E=abc": "line 1",
		"material E=1 nu=0.3\nmesh rect w=1 h=1 nx=1":                           "missing ny",
		"material E=1\nmesh rect w=1 h=1 nx=2 ny=2\nfix where x==9 dofs=x":      "matches no nodes",
		"material E=1\nmesh rect w=1 h=1 nx=2 ny=2\nfix where z==0":             "cannot parse selection",
		"material E=1\nmesh rect w=1 h=1 nx=2 ny=2\nfrobnicate":                 "unknown directive",
		"material E=1\nmesh rect w=1 h=1 nx=2 ny=2 foo=1":                       "unknown option",
		"material E=1 nu=0.5 plane=strain":                                      "Poisson",
		"":                                                                      "neither",
		"mesh rect w=1 h=1 nx=1 ny=1":                                           "material",
		"frame\nnode 0 0\nbeam 0 5 E=1 A=1 I=1":                                 "invalid nodes",
		"material E=1\nmesh rect w=1 h=1 nx=2 ny=2\ntraction where x==1 tx=nan": "finite",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil {
			t.Errorf("%q: expected error", src)
			continue
		}
		if !strings.Contains(err.Error(), want) {
			t.Errorf("%q: error %q lacks %q", src, err, want)
		}
	}
}

func TestParseFrame(t *testing.T) {
	in, err := Parse("frame\nnode 0 0\nnode 4 0\nbeam 0 1 E=1e5 A=1 I=10\nsupport 0 dofs=xyr\nforce 1 fy=-1")
	if err != nil {
		t.Fatal(err)
	}
	s, err := in.Frame.Solve()
	if err != nil {
		t.Fatal(err)
	}
	if rel(-s.U[4], 64/(3*1e5*10.0)) > 1e-12 {
		t.Errorf("tip %g", s.U[4])
	}
}

func TestValidationSuiteAndRates(t *testing.T) {
	cs, conv, err := RunValidation()
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range cs {
		if !c.Pass() {
			t.Errorf("%s: got %g want %g (err %.2e > tol %.0e)", c.Name, c.Got, c.Want, c.Err(), c.Tol)
		}
	}
	last := map[ElemType]float64{}
	for _, r := range conv {
		last[r.Type] = r.Rate
	}
	if last[Tri3] < 1.8 || last[Quad4] < 1.8 || last[Tri6] < 2.9 {
		t.Errorf("asymptotic convergence orders too low: %v", last)
	}
}

func TestReviewRegressionsInParser(t *testing.T) {
	bad := map[string]string{
		"material E=1 t=1\nmesh rect w=1 h=1 nx=2 ny=2\nmaterial E=9 t=1": "only be given once",
		"frame\nnode 0 0\nnode 1 0\nbar 0 1 E=1 A=1 w=-3":                 "distributed",
		"frame\nnode 0 0\nnode 1 0\nbar 0 1 E=1 A=1 i=3":                  "bending",
		"material E=1 t=1\nmesh rect w=1 h=1 nx=900 ny=900":               "too large",
	}
	for src, want := range bad {
		if _, err := Parse(src); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: want error containing %q, got %v", src, want, err)
		}
	}
	in, err := Parse("title a=1 a=2 <b>\nmaterial E=1 t=1\nmesh rect w=1 h=1 nx=1 ny=1")
	if err != nil || in.Title != "a=1 a=2 <b>" {
		t.Errorf("title with '=' mishandled: %v %q", err, in.Title)
	}
	html := Page(in.Title, "x", "")
	if strings.Contains(html, "<b>") {
		t.Error("title must be HTML-escaped")
	}
}
