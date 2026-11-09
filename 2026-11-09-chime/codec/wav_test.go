package codec

import (
	"bytes"
	"testing"
)

func TestWAVRoundTrip(t *testing.T) {
	a := &Audio{Rate: 44100, Ch: [][]float64{{0, 100, -100, 32767, -32768}, {1, 2, 3, 4, 5}}}
	var b bytes.Buffer
	if err := WriteWAV(&b, a); err != nil {
		t.Fatal(err)
	}
	g, err := ReadWAV(b.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	if g.Rate != 44100 || len(g.Ch) != 2 || g.Frames() != 5 {
		t.Fatalf("bad shape %+v", g)
	}
	for c := range a.Ch {
		for i := range a.Ch[c] {
			if g.Ch[c][i] != a.Ch[c][i] {
				t.Fatalf("mismatch c%d i%d", c, i)
			}
		}
	}
}

func TestWAVRejectsGarbage(t *testing.T) {
	for _, d := range [][]byte{nil, []byte("RIFF"), []byte("RIFFxxxxWAVEfmt "), bytes.Repeat([]byte{7}, 100)} {
		if _, err := ReadWAV(d); err == nil {
			t.Fatalf("accepted garbage %q", d)
		}
	}
}
