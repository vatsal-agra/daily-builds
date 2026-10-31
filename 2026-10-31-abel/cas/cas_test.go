package cas

import "testing"

func TestBasicSimplify(t *testing.T) {
	cases := map[string]string{
		"x + x":           "2*x",
		"x - x":           "0",
		"2*(x+1) - 2*x":   "2",
		"x*x*x":           "x^3",
		"sqrt(8)":         "2*sqrt(2)",
		"sqrt(2)*sqrt(3)": "sqrt(6)",
		"sqrt(2)*sqrt(2)": "2",
		"1/2 + 1/3":       "5/6",
		"sin(pi/6)":       "1/2",
		"cos(pi)":         "-1",
		"e^x*e^x":         "e^(2*x)",
		"ln(e^3)":         "3",
		"x^2/x":           "x",
		"sqrt(-4)":        "2*i",
		"i^2":             "-1",
		"(x+1)^2":         "(x + 1)^2",
		"2x^2 + 3x + 1":   "2*x^2 + 3*x + 1",
		"1/sqrt(2)":       "sqrt(2)/2",
		"-x^2":            "-x^2",
		"x/y":             "x/y",
		"2^(1/2)*2^(1/3)": "32^(1/6)",
	}
	for in, want := range cases {
		got := MustParse(in).String()
		if got != want {
			t.Errorf("%s => %s, want %s", in, got, want)
		}
	}
}
