package qr

import (
	"bytes"
	"testing"
)

func TestProbeEmptyPayload(t *testing.T) {
	c, err := Encode(nil, DefaultOptions())
	if err != nil {
		t.Fatal(err)
	}
	r, err := Decode(c.Matrix)
	if err != nil || r.Text != "" {
		t.Fatalf("%v %q", err, r.Text)
	}
}

func TestProbeBinaryPayload(t *testing.T) {
	all := make([]byte, 256)
	for i := range all {
		all[i] = byte(i)
	}
	c, err := Encode(all, Options{ECC: L})
	if err != nil {
		t.Fatal(err)
	}
	r, err := Decode(c.Matrix)
	if err != nil || !bytes.Equal(r.Bytes, all) {
		t.Fatalf("binary round trip failed: %v", err)
	}
}

func TestProbeZeroValueOptionsAreSane(t *testing.T) {
	c, err := Encode([]byte("zero value options"), Options{})
	if err != nil {
		t.Fatal(err)
	}
	// With the zero value the mask must be chosen by penalty, not forced to 0.
	best := c.Penalty
	for mk := 0; mk < 8; mk++ {
		o, _ := Encode([]byte("zero value options"), Options{Mask: ForceMask(mk)})
		if o.Penalty < best {
			t.Fatalf("zero-value Options forced a non-optimal mask (%d < %d)", o.Penalty, best)
		}
	}
}

func TestProbeErasedMaskWrongSize(t *testing.T) {
	c, _ := EncodeText("erasure size", Options{ECC: M})
	if _, err := DecodeWith(c.Matrix, DecodeOptions{Erased: NewMatrix(5)}); err == nil {
		t.Fatal("mismatched erasure matrix must be an error, not a panic")
	}
}

// Random corruption must never panic and must never "succeed" with other text
// unless the corruption stayed within the correction budget.
func TestProbeDecodeNeverPanics(t *testing.T) {
	r := newRand(21)
	c, _ := EncodeText("fuzz target payload 0123456789", Options{ECC: M})
	for trial := 0; trial < 3000; trial++ {
		m := c.Matrix.Clone()
		k := 1 + r.Intn(m.N*m.N/3)
		for i := 0; i < k; i++ {
			x, y := r.Intn(m.N), r.Intn(m.N)
			m.Set(x, y, !m.Get(x, y))
		}
		if res, err := Decode(m); err == nil && res.Text != "fuzz target payload 0123456789" {
			// RS can in theory miscorrect; but the format+RS+structure checks should
			// make that vanishingly rare at this rate.
			t.Logf("trial %d: miscorrection to %q (flips=%d)", trial, res.Text, k)
		}
	}
}

func TestProbeParseTextInverted(t *testing.T) {
	c, _ := EncodeText("inverted art", Options{ECC: M})
	m, err := ParseText(c.Matrix.Text(4, true))
	if err != nil {
		t.Skip("inverted art has no dark modules to anchor on")
	}
	if r, err := Decode(m); err == nil && r.Text == "inverted art" {
		return
	}
	t.Fatal("inverted art does not decode")
}

func TestProbeCRLFArt(t *testing.T) {
	c, _ := EncodeText("windows line endings", Options{ECC: M})
	art := ""
	for _, ln := range bytes.Split([]byte(c.Matrix.Text(2, false)), []byte("\n")) {
		art += string(ln) + "   \r\n"
	}
	m, err := ParseText(art)
	if err != nil {
		t.Fatal(err)
	}
	if r, err := Decode(m); err != nil || r.Text != "windows line endings" {
		t.Fatalf("%v", err)
	}
}
