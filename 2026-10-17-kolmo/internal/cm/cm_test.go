package cm

import (
	"bytes"
	"math/rand"
	"os"
	"testing"
)

func TestRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(2))
	random := make([]byte, 20000)
	rng.Read(random)
	text, _ := os.ReadFile("../../PLAN.md")
	cases := map[string][]byte{
		"empty": {}, "one": {0}, "zeros": make([]byte, 50000), "random": random,
		"text": text, "repeat": bytes.Repeat([]byte("abcdefgh"), 5000),
		"allbytes": func() []byte {
			b := make([]byte, 1024)
			for i := range b {
				b[i] = byte(i)
			}
			return b
		}(),
	}
	for name, c := range cases {
		enc := Encode(c)
		dec, err := Decode(enc, len(c))
		if err != nil || !bytes.Equal(dec, c) {
			t.Fatalf("%s: round trip failed (%v)", name, err)
		}
	}
}

func TestBeatsOrder0OnText(t *testing.T) {
	text, _ := os.ReadFile("../../PLAN.md")
	enc := Encode(text)
	if len(enc)*10 > len(text)*5 {
		t.Fatalf("expected >2x on prose, got %d -> %d", len(text), len(enc))
	}
}

func TestCostsMatchActualSize(t *testing.T) {
	text, _ := os.ReadFile("../../PLAN.md")
	var total float64
	for _, c := range Costs(text) {
		total += float64(c)
	}
	actual := float64(len(Encode(text)) * 8)
	if total > actual || actual-total > 64 {
		t.Fatalf("model cost %.0f bits vs coded %.0f bits", total, actual)
	}
}

func TestDecodeGarbageTerminates(t *testing.T) {
	rng := rand.New(rand.NewSource(4))
	junk := make([]byte, 100)
	for i := 0; i < 50; i++ {
		rng.Read(junk)
		Decode(junk, 5000)
	}
}
