package container

import (
	"bytes"
	"math/rand"
	"os"
	"testing"

	"kolmo/internal/deflate"
)

func samples() map[string][]byte {
	rng := rand.New(rand.NewSource(11))
	rnd := make([]byte, 5000)
	rng.Read(rnd)
	text, _ := os.ReadFile("../../PLAN.md")
	return map[string][]byte{"empty": {}, "one": {1}, "random": rnd, "text": text,
		"runs": bytes.Repeat([]byte{0, 0, 0, 1}, 4000)}
}

func TestEveryMethodRoundTrips(t *testing.T) {
	for name, src := range samples() {
		for _, m := range Methods() {
			enc := m.Encode(src, 6)
			dec, info, err := Decode(enc)
			if err != nil || !bytes.Equal(dec, src) || info.Method != m {
				t.Fatalf("%s/%s: %v", name, m.Name, err)
			}
		}
	}
}

func TestAutoNeverWorseThanStore(t *testing.T) {
	for name, src := range samples() {
		enc, m := Auto(src, 9)
		if len(enc) > len(src)+16 {
			t.Fatalf("%s: auto (%s) expanded %d -> %d", name, m.Name, len(src), len(enc))
		}
		dec, _, err := Decode(enc)
		if err != nil || !bytes.Equal(dec, src) {
			t.Fatalf("%s: %v", name, err)
		}
	}
}

func TestCorruptionIsDetected(t *testing.T) {
	src := samples()["text"]
	rng := rand.New(rand.NewSource(5))
	for _, m := range Methods() {
		good := m.Encode(src, 6)
		for i := 0; i < 150; i++ {
			bad := append([]byte(nil), good...)
			bad[rng.Intn(len(bad))] ^= byte(1 << uint(rng.Intn(8)))
			out, _, err := Decode(bad)
			if err == nil && !bytes.Equal(out, src) {
				t.Fatalf("%s: corrupted file decoded silently to wrong data", m.Name)
			}
		}
	}
}

func TestBadHeaders(t *testing.T) {
	for _, b := range [][]byte{nil, []byte("KOL"), []byte("XXXX\x00\x00\x00\x00\x00\x00"),
		[]byte("KOL1\x63\x00\x00\x00\x00\x00"), []byte("KOL1\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01\x00\x00\x00\x00")} {
		if _, _, err := Decode(b); err == nil {
			t.Fatalf("expected error for %q", b)
		}
	}
}

func TestGzipInputAccepted(t *testing.T) {
	src := samples()["text"]
	dec, info, err := Decode(deflate.Gzip(src, 6))
	if err != nil || !bytes.Equal(dec, src) || info.Method.Name != "deflate" {
		t.Fatalf("gzip input: %v", err)
	}
}
