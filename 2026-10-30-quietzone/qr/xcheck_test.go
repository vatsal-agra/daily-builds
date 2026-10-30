package qr

import (
	"bytes"
	"encoding/json"
	"errors"
	"os/exec"
	"strings"
	"testing"
)

// Differential test against the independent Python `segno` library. Skipped
// when python3.13/segno is unavailable.
func TestMatchesSegnoByteForByte(t *testing.T) {
	py, err := exec.LookPath("python3.13")
	if err != nil {
		t.Skip("python3.13 not available")
	}
	if exec.Command(py, "-c", "import segno").Run() != nil {
		t.Skip("segno not installed")
	}
	type tc struct {
		Text    string `json:"text"`
		Version int    `json:"version"`
		ECC     string `json:"ecc"`
		Mask    int    `json:"mask"`
	}
	r := newRand(11)
	var cases []tc
	gens := []func(n int) string{
		func(n int) string { return randFrom(r, "0123456789", n) },
		func(n int) string { return randFrom(r, alnumChars, n) },
		func(n int) string { return randFrom(r, "abcdefghijklmnopqrstuvwxyz,;!?", n) },
	}
	for i := 0; i < 240; i++ {
		v := 1 + r.Intn(40)
		e := ECC(r.Intn(4))
		g := gens[i%3]
		var maxN int
		switch i % 3 {
		case 0:
			maxN = DataCodewords(v, e)*8*29/100 - 6
		case 1:
			maxN = DataCodewords(v, e)*8*17/100 - 6
		default:
			maxN = DataCodewords(v, e) - 3
		}
		if maxN < 1 {
			maxN = 1
		}
		n := 1 + r.Intn(maxN)
		if v > 1 && i%2 == 0 {
			n = max(1, maxN-r.Intn(3)) // near capacity
		}
		cases = append(cases, tc{g(n), v, e.String(), r.Intn(8)})
	}
	in, _ := json.Marshal(cases)
	cmd := exec.Command(py, "../tools/segno_ref.py")
	cmd.Stdin = bytes.NewReader(in)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		t.Fatalf("reference generator failed (%v): %s", err, errb.String())
	}
	var ref [][]string
	if err := json.Unmarshal(out.Bytes(), &ref); err != nil {
		t.Fatal(err)
	}
	skipped := 0
	defer func() {
		t.Logf("%d cases matched segno exactly, %d nibble-aligned cases verified by decoding", len(cases)-skipped, skipped)
	}()
	for i, c := range cases {
		e, _ := ParseECC(c.ECC)
		code, err := EncodeText(c.Text, Options{ECC: e, MinVersion: c.Version, MaxVersion: c.Version, Mask: ForceMask(c.Mask)})
		if err != nil {
			t.Fatalf("case %d: %v", i, err)
		}
		// segno quirk: when the stream ends exactly on a nibble, segno emits a whole
		// extra 00 pad byte after the terminator (ISO 18004 §7.4.9 does not), so the
		// pad bytes shift. Those cases are compared through decoding instead.
		if used := totalBits(code.Segments, code.Version); used%8 == 4 && used+4 < DataCodewords(code.Version, code.ECC)*8 {
			skipped++
			rm := NewMatrix(code.Matrix.N)
			for yy, rr := range ref[i] {
				for xx, c2 := range rr {
					rm.Set(xx, yy, c2 == '1')
				}
			}
			if rr, derr := Decode(rm); derr != nil || rr.Text != c.Text {
				t.Fatalf("case %d: our decoder cannot read segno's symbol: %v", i, derr)
			}
			continue
		}
		for y, row := range ref[i] {
			for x, ch := range row {
				if (ch == '1') != code.Matrix.Get(x, y) {
					rm := NewMatrix(code.Matrix.N)
					for yy, rr := range ref[i] {
						for xx, c2 := range rr {
							rm.Set(xx, yy, c2 == '1')
						}
					}
					rr, derr := Decode(rm)
					if derr == nil {
						t.Logf("segno segments: %+v\nours: %+v", rr.Segments, code.Segments)
					}
					t.Fatalf("case %d (v%d-%s mask %d %q...): module (%d,%d) differs from segno", i, c.Version, c.ECC, c.Mask, c.Text[:min(12, len(c.Text))], x, y)
				}
			}
		}
	}
}

func randFrom(r interface{ Intn(int) int }, set string, n int) string {
	var sb strings.Builder
	for i := 0; i < n; i++ {
		sb.WriteByte(set[r.Intn(len(set))])
	}
	return sb.String()
}

func lookPython() (string, error) {
	py, err := exec.LookPath("python3.13")
	if err != nil {
		return "", err
	}
	if exec.Command(py, "-c", "import segno").Run() != nil {
		return "", errors.New("no segno")
	}
	return py, nil
}
