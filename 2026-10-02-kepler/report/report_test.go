package report

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"kepler/data"
	"kepler/expr"
	"kepler/gp"
)

func fakeResult(t *testing.T, names []string, formulas ...string) *gp.Result {
	t.Helper()
	r := &gp.Result{Names: names}
	for i, f := range formulas {
		n, err := expr.Parse(f, names)
		if err != nil {
			t.Fatal(err)
		}
		r.Front = append(r.Front, gp.Model{Tree: n, Complexity: n.Complexity(), TrainNMSE: math.Pow(10, -float64(i)*3), HoldoutNMSE: math.NaN()})
	}
	r.Selected = len(formulas) - 1
	return r
}

func TestWriteSingleAndMultiVar(t *testing.T) {
	dir := t.TempDir()
	one := (&data.Benchmarks[0]).Generate(30, 1)
	p := filepath.Join(dir, "a.html")
	if err := Write(p, one.Target, one, fakeResult(t, one.Names, "a", "a^1.5"), nil); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(p)
	s := string(b)
	for _, want := range []string{"<!doctype html>", "a^1.5", "Pareto front", "<polyline", "<circle", "viewport"} {
		if !strings.Contains(s, want) {
			t.Errorf("report missing %q", want)
		}
	}
	two := (&data.Benchmarks[1]).Generate(30, 1)
	p2 := filepath.Join(dir, "b.html")
	if err := Write(p2, two.Target, two, fakeResult(t, two.Names, "L", "6.28*sqrt(L/g)"), nil); err != nil {
		t.Fatal(err)
	}
	b, _ = os.ReadFile(p2)
	if !strings.Contains(string(b), "actual T") {
		t.Error("multi-variable fit plot should be predicted-vs-actual")
	}
}

func TestEscapesUserText(t *testing.T) {
	d := &data.Dataset{Names: []string{"x"}, Target: "<script>alert(1)</script>"}
	for i := 0; i < 6; i++ {
		d.X = append(d.X, []float64{float64(i)})
		d.Y = append(d.Y, float64(i))
	}
	p := filepath.Join(t.TempDir(), "x.html")
	if err := Write(p, d.Target, d, fakeResult(t, d.Names, "x"), nil); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(p)
	if strings.Contains(string(b), "<script>alert") {
		t.Fatal("unescaped target name in report")
	}
}

func TestSingleModelFrontAndBenchReport(t *testing.T) {
	d := (&data.Benchmarks[0]).Generate(20, 1)
	res := fakeResult(t, d.Names, "a^1.5")
	p := filepath.Join(t.TempDir(), "bench.html")
	rows := []BenchRow{{Name: "kepler", Desc: "d", Truth: "T = a^1.5", Found: "T = a^1.5", OK: true, Result: res, Data: d},
		{Name: "miss", Desc: "d", Truth: "t", Found: "f", OK: false, Result: res, Data: d}}
	if err := WriteBench(p, rows); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(p)
	s := string(b)
	if !strings.Contains(s, "1 of 2 physical laws") || !strings.Contains(s, "missed") || !strings.Contains(s, "rediscovered") {
		t.Error("bench summary wrong")
	}
	if strings.Contains(s, "NaN") || strings.Contains(s, "Inf") {
		t.Error("NaN/Inf leaked into SVG")
	}
}
