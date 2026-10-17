package deflate

import (
	"bytes"
	"compress/flate"
	"io"
	"math/rand"
	"os/exec"
	"testing"
)

func corpora() map[string][]byte {
	rng := rand.New(rand.NewSource(1))
	random := make([]byte, 100000)
	rng.Read(random)
	text := bytes.Repeat([]byte("the quick brown fox jumps over the lazy dog. "), 3000)
	var mixed []byte
	for i := 0; i < 200; i++ {
		mixed = append(mixed, text[:rng.Intn(500)]...)
		mixed = append(mixed, random[:rng.Intn(300)]...)
	}
	skew := make([]byte, 70000)
	for i := range skew {
		skew[i] = byte(rng.ExpFloat64() * 3)
	}
	return map[string][]byte{
		"empty": {}, "one": {42}, "two": {1, 2}, "zeros": make([]byte, 300000),
		"random": random, "text": text, "mixed": mixed, "skew": skew,
		"ab": bytes.Repeat([]byte("ab"), 40000), "stored-edge": random[:65535], "stored-edge2": random[:65536],
	}
}

func TestRoundTripAllLevels(t *testing.T) {
	for name, src := range corpora() {
		for lv := 0; lv <= 9; lv++ {
			c := Compress(src, lv)
			got, used, err := Inflate(c, 0)
			if err != nil || !bytes.Equal(got, src) || used != len(c) {
				t.Fatalf("%s level %d: err=%v used=%d/%d equal=%v", name, lv, err, used, len(c), bytes.Equal(got, src))
			}
		}
	}
}

// Our output must be decodable by the standard library (independent oracle).
func TestStdlibCanDecodeOurs(t *testing.T) {
	for name, src := range corpora() {
		for _, lv := range []int{1, 4, 6, 9} {
			got, err := io.ReadAll(flate.NewReader(bytes.NewReader(Compress(src, lv))))
			if err != nil || !bytes.Equal(got, src) {
				t.Fatalf("%s level %d: stdlib decode failed: %v", name, lv, err)
			}
		}
	}
}

// We must decode what the standard library produces, at every level.
func TestWeCanDecodeStdlib(t *testing.T) {
	for name, src := range corpora() {
		for lv := -2; lv <= 9; lv++ {
			var buf bytes.Buffer
			w, _ := flate.NewWriter(&buf, lv)
			w.Write(src)
			w.Close()
			got, _, err := Inflate(buf.Bytes(), 0)
			if err != nil || !bytes.Equal(got, src) {
				t.Fatalf("%s stdlib level %d: %v", name, lv, err)
			}
		}
	}
}

func TestGzipInteropWithSystemGzip(t *testing.T) {
	if _, err := exec.LookPath("gzip"); err != nil {
		t.Skip("no gzip binary")
	}
	src := corpora()["mixed"]
	cmd := exec.Command("gzip", "-dc")
	cmd.Stdin = bytes.NewReader(Gzip(src, 6))
	out, err := cmd.Output()
	if err != nil || !bytes.Equal(out, src) {
		t.Fatalf("system gzip rejected our stream: %v", err)
	}
	cmd = exec.Command("gzip", "-9c")
	cmd.Stdin = bytes.NewReader(src)
	gz, _ := cmd.Output()
	got, err := Gunzip(gz, 0)
	if err != nil || !bytes.Equal(got, src) {
		t.Fatalf("could not read system gzip output: %v", err)
	}
}

func TestGunzipConcatenatedAndCorrupt(t *testing.T) {
	a, b := []byte("hello "), []byte("world")
	got, err := Gunzip(append(Gzip(a, 6), Gzip(b, 6)...), 0)
	if err != nil || string(got) != "hello world" {
		t.Fatalf("concat: %q %v", got, err)
	}
	gz := Gzip(bytes.Repeat([]byte("xyz"), 1000), 6)
	gz[len(gz)-6] ^= 1 // flip a CRC byte
	if _, err := Gunzip(gz, 0); err == nil {
		t.Fatal("expected CRC error")
	}
}

func TestInflateRejectsGarbage(t *testing.T) {
	rng := rand.New(rand.NewSource(7))
	good := Compress(corpora()["text"][:5000], 6)
	for i := 0; i < 3000; i++ {
		bad := append([]byte(nil), good...)
		for k := 0; k < 1+rng.Intn(4); k++ {
			bad[rng.Intn(len(bad))] ^= byte(1 << uint(rng.Intn(8)))
		}
		if rng.Intn(3) == 0 {
			bad = bad[:rng.Intn(len(bad))]
		}
		Inflate(bad, 1<<20) // must not panic or hang
	}
	junk := make([]byte, 200)
	for i := 0; i < 2000; i++ {
		rng.Read(junk)
		Inflate(junk, 1<<20)
	}
}

func TestMaxOutBound(t *testing.T) {
	bomb := Compress(make([]byte, 5_000_000), 9)
	if _, _, err := Inflate(bomb, 1000); err == nil {
		t.Fatal("expected output limit error")
	}
}

func TestLevelsMonotone(t *testing.T) {
	src := corpora()["mixed"]
	if len(Compress(src, 9)) > len(Compress(src, 1)) {
		t.Fatal("level 9 should not be worse than level 1 on this input")
	}
}
