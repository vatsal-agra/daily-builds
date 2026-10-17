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
			enc, err := m.Encode(src, 6)
			if err != nil {
				t.Fatalf("%s/%s: %v", name, m.Name, err)
			}
			dec, info, err := Decode(enc)
			if err != nil || !bytes.Equal(dec, src) || info.Method != m {
				t.Fatalf("%s/%s: %v", name, m.Name, err)
			}
		}
	}
}

func TestAutoNeverWorseThanStore(t *testing.T) {
	for name, src := range samples() {
		enc, m, _, _ := Auto(src, 9)
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
		good, _ := m.Encode(src, 6)
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

func TestSizeBombRejectedBeforeAllocation(t *testing.T) {
	for _, m := range Methods() {
		// header declaring 1 GiB over a 4-byte payload
		f := append([]byte(Magic), m.ID, 0x80, 0x80, 0x80, 0x80, 0x04, 0, 0, 0, 0, 'a', 'b', 'c', 'd')
		_, _, err := Decode(f)
		if m.ID != 0 && err == nil {
			t.Fatalf("%s: bomb accepted", m.Name)
		}
	}
}

func TestEncoderHonoursDecoderBound(t *testing.T) {
	zeros := make([]byte, 3_000_000)
	for _, m := range Methods() {
		if m.Name == "cm" {
			zeros = zeros[:400_000] // keep the slow model quick; its bound is a hard floor on cost
		}
		enc, err := m.Encode(zeros, 9)
		if err != nil {
			continue // refusing is allowed; writing an unreadable file is not
		}
		dec, _, err := Decode(enc)
		if err != nil || !bytes.Equal(dec, zeros) {
			t.Fatalf("%s: wrote a file it cannot read back: %v", m.Name, err)
		}
	}
}
