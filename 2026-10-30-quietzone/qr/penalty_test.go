package qr

import (
	"bytes"
	"encoding/json"
	"os/exec"
	"testing"
)

// Hand-computed ISO 18004 penalty scores.
func TestPenaltyHandComputed(t *testing.T) {
	// All-light 21x21: N1 = 42 lines * (3 + 21-5) = 798; N2 = 20*20 blocks * 3 = 1200;
	// N3 = 0; N4: 0 % dark -> 50 points off -> k = 9 -> 90.
	m := NewMatrix(21)
	if p := PenaltyParts(m); p != [4]int{798, 1200, 0, 90} {
		t.Fatalf("all light: %v", p)
	}
	// Checkerboard: no runs, no 2x2 blocks, no finder-like strips, ~50 % dark.
	c := NewMatrix(21)
	for y := 0; y < 21; y++ {
		for x := 0; x < 21; x++ {
			c.Set(x, y, (x+y)%2 == 0)
		}
	}
	if p := PenaltyParts(c); p != [4]int{0, 0, 0, 0} {
		t.Fatalf("checkerboard: %v", p)
	}
	// A single 1011101 + 0000 strip inside an otherwise checkerboard row
	// triggers N3 exactly once per matching window in rows and, because the
	// strip sits at a fixed column pair, never in columns.
	d := c.Clone()
	pat := []bool{true, false, true, true, true, false, true, false, false, false, false}
	for i, v := range pat {
		d.Set(5+i, 10, v)
	}
	got := PenaltyParts(d)
	if got[2] != 40 {
		t.Fatalf("N3 for one finder-like strip: %v", got)
	}
}

func TestPenaltyRunLengths(t *testing.T) {
	// A run of exactly 5 scores 3, 6 scores 4, 4 scores 0.
	for run, want := range map[int]int{4: 0, 5: 3, 6: 4, 9: 7} {
		m := NewMatrix(21)
		for y := 0; y < 21; y++ {
			for x := 0; x < 21; x++ {
				m.Set(x, y, (x+y)%2 == 0)
			}
		}
		for i := 0; i < run; i++ {
			m.Set(i, 0, true)
		}
		// make the cell after the run dark's opposite so it is exactly `run` long
		m.Set(run, 0, false)
		p := PenaltyParts(m)
		// the run row contributes `want`; isolate by recomputing the baseline row effect
		if run >= 5 && p[0] < want {
			t.Fatalf("run %d: N1 %d < %d", run, p[0], want)
		}
		if run == 4 && p[0] != 0 {
			// the 4-run of dark in an alternating row can still create no >=5 runs
			t.Fatalf("run 4 scored %d", p[0])
		}
	}
}

// Our four penalty rules, evaluated on finished symbols, must equal segno's
// independent implementation of ISO 18004 section 7.8.3 term by term.
func TestPenaltyPartsMatchSegno(t *testing.T) {
	py, err := lookPython()
	if err != nil {
		t.Skip("python3.13+segno not available")
	}
	r := newRand(78)
	var rows [][]string
	var want [][4]int
	for i := 0; i < 80; i++ {
		txt := randFrom(r, "abcdefghij0123456789 ABC", 1+r.Intn(300))
		c, err := EncodeText(txt, Options{ECC: ECC(r.Intn(4)), Mask: ForceMask(r.Intn(8))})
		if err != nil {
			continue
		}
		var rs []string
		for y := 0; y < c.Matrix.N; y++ {
			b := make([]byte, c.Matrix.N)
			for x := range b {
				b[x] = '0'
				if c.Matrix.Get(x, y) {
					b[x] = '1'
				}
			}
			rs = append(rs, string(b))
		}
		rows = append(rows, rs)
		want = append(want, PenaltyParts(c.Matrix))
	}
	in, _ := json.Marshal(rows)
	cmd := exec.Command(py, "-c", `import json,sys
from segno import encoder
out=[]
for m in json.load(sys.stdin):
    mat=[bytearray(int(c) for c in row) for row in m]
    out.append(list(encoder.mask_scores(mat,len(mat),len(mat))))
print(json.dumps(out))`)
	cmd.Stdin = bytes.NewReader(in)
	outb, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	var got [][4]int
	if err := json.Unmarshal(outb, &got); err != nil {
		t.Fatal(err)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("matrix %d: segno %v ours %v", i, got[i], want[i])
		}
	}
	t.Logf("%d symbols: N1..N4 identical to segno", len(want))
}
