package data

import (
	"bytes"
	"strings"
	"testing"
)

const good = "x,z,y\n1,2,3\n2,3,5\n3,4,7\n4,5,9\n5,6,11\n"

func TestReadCSV(t *testing.T) {
	d, err := ReadCSV(strings.NewReader(good), "")
	if err != nil {
		t.Fatal(err)
	}
	if d.Target != "y" || len(d.Names) != 2 || d.N() != 5 || d.X[2][1] != 4 || d.Y[4] != 11 {
		t.Fatalf("bad parse %+v", d)
	}
	d2, err := ReadCSV(strings.NewReader(good), "z")
	if err != nil || d2.Target != "z" || d2.Names[1] != "y" {
		t.Fatalf("target select: %v %+v", err, d2)
	}
}

func TestReadCSVEdgeCases(t *testing.T) {
	ok := map[string]string{
		"BOM":      "\xef\xbb\xbfx,y\r\n1,2\r\n2,3\r\n3,4\r\n4,5\r\n5,6\r\n",
		"comments": "x,y\n# note\n1,2\n2,3\n3,4\n\n4,5\n5,6\n",
		"spaces":   "x, y\n1, 2\n2, 3\n3, 4\n4, 5\n5, 6\n",
	}
	for name, src := range ok {
		if d, err := ReadCSV(strings.NewReader(src), ""); err != nil || d.N() != 5 {
			t.Errorf("%s: %v", name, err)
		}
	}
	bad := map[string]string{
		"empty":       "",
		"header only": "x,y\n",
		"few rows":    "x,y\n1,2\n2,3\n",
		"ragged":      "x,y\n1,2\n2,3,4\n3,4\n4,5\n5,6\n",
		"text":        "x,y\n1,2\n2,hello\n3,4\n4,5\n5,6\n",
		"nan":         "x,y\n1,2\n2,NaN\n3,4\n4,5\n5,6\n",
		"inf":         "x,y\n1,2\n2,Inf\n3,4\n4,5\n5,6\n",
		"one column":  "x\n1\n2\n3\n4\n5\n",
		"bad name":    "x y,z\n1,2\n2,3\n3,4\n4,5\n5,6\n",
		"reserved":    "pi,y\n1,2\n2,3\n3,4\n4,5\n5,6\n",
		"blank col":   "x,,y\n1,2,3\n2,3,4\n3,4,5\n4,5,6\n5,6,7\n",
	}
	for name, src := range bad {
		if _, err := ReadCSV(strings.NewReader(src), ""); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	if _, err := ReadCSV(strings.NewReader(good), "nope"); err == nil || !strings.Contains(err.Error(), "not found") {
		t.Errorf("missing target: %v", err)
	}
	// error message names the row
	_, err := ReadCSV(strings.NewReader("x,y\n1,2\n2,hello\n3,4\n4,5\n5,6\n"), "")
	if err == nil || !strings.Contains(err.Error(), "row 3") {
		t.Errorf("error should cite row 3: %v", err)
	}
}

func TestRoundTripAndSplit(t *testing.T) {
	b, _ := Find("pendulum")
	d := b.Generate(50, 3)
	var buf bytes.Buffer
	if err := d.WriteCSV(&buf); err != nil {
		t.Fatal(err)
	}
	back, err := ReadCSV(&buf, "")
	if err != nil || back.N() != 50 {
		t.Fatal(err)
	}
	tr, ho := back.Split(0.2, 1)
	if tr.N()+ho.N() != 50 || ho.N() != 10 {
		t.Fatalf("split %d/%d", tr.N(), ho.N())
	}
	tr2, _ := back.Split(0.2, 1)
	if tr2.Y[0] != tr.Y[0] {
		t.Error("split not deterministic")
	}
}

func TestBenchmarksGenerate(t *testing.T) {
	for _, b := range Benchmarks {
		d := b.Generate(40, 1)
		if d.N() != 40 || len(d.Names) != len(b.Ranges) {
			t.Errorf("%s shape", b.Name)
		}
		for i, row := range d.X {
			for j, v := range row {
				if v < b.Ranges[j][0] || v > b.Ranges[j][1] {
					t.Errorf("%s out of range", b.Name)
				}
			}
			if b.Noise == 0 && d.Y[i] != b.Fn(row) {
				t.Errorf("%s noiseless y mismatch", b.Name)
			}
		}
	}
}
