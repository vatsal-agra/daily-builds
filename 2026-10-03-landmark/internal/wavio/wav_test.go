package wavio

import (
	"math"
	"testing"
)

func TestRoundTrip(t *testing.T) {
	x := make([]float64, 1000)
	for i := range x {
		x[i] = 0.8 * math.Sin(float64(i)*0.05)
	}
	y, r, err := Decode(Encode(x, 22050))
	if err != nil || r != 22050 || len(y) != len(x) {
		t.Fatalf("decode: %v rate=%d len=%d", err, r, len(y))
	}
	for i := range x {
		if math.Abs(x[i]-y[i]) > 1.0/16000 {
			t.Fatalf("sample %d: %v vs %v", i, x[i], y[i])
		}
	}
}

func TestClipsOnEncode(t *testing.T) {
	y, _, _ := Decode(Encode([]float64{5, -5}, 8000))
	if y[0] < 0.999 || y[1] > -0.999 {
		t.Fatalf("not clipped: %v", y)
	}
}

func TestRejectsGarbage(t *testing.T) {
	for _, b := range [][]byte{nil, []byte("hello world, not a wav"), Encode(nil, 8000)[:20]} {
		if _, _, err := Decode(b); err == nil {
			t.Fatalf("expected error for %q", b)
		}
	}
}

func TestStereoMixdown(t *testing.T) {
	// hand-built stereo 16-bit file: L=+16384, R=-16384 -> mono 0
	b := Encode([]float64{0, 0}, 8000)
	b[22] = 2 // channels
	b[32] = 4 // block align
	// data now holds 2 samples = 1 stereo frame
	b[44], b[45] = 0x00, 0x40
	b[46], b[47] = 0x00, 0xC0
	y, _, err := Decode(b)
	if err != nil || len(y) != 1 || math.Abs(y[0]) > 1e-9 {
		t.Fatalf("got %v err %v", y, err)
	}
}

func TestEightBitAnd24Bit(t *testing.T) {
	b := Encode([]float64{0, 0}, 8000)
	b[34] = 8 // 8-bit
	b[32] = 1
	b[44], b[45] = 128, 255
	y, _, err := Decode(b)
	if err != nil || len(y) != 4 || y[0] != 0 || y[1] < 0.99 {
		t.Fatalf("8-bit: %v %v", y, err)
	}
}
