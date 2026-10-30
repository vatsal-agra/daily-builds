package qr

import (
	"strings"
	"testing"
)

func TestSpecExample01234567(t *testing.T) {
	// ISO 18004 Annex I: "01234567", version 1-M, mask 2 forced by the example.
	opt := DefaultOptions()
	opt.BoostECC = false
	opt.Mask = ForceMask(2)
	c, err := EncodeText("01234567", opt)
	if err != nil {
		t.Fatal(err)
	}
	if c.Version != 1 || c.ECC != M {
		t.Fatalf("v%d-%v", c.Version, c.ECC)
	}
	want := []byte{0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11,
		0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55}
	for i := range want {
		if c.Codewords[i] != want[i] {
			t.Fatalf("codeword %d = %02X want %02X", i, c.Codewords[i], want[i])
		}
	}
	if len(c.Codewords) != len(want) {
		t.Fatalf("len %d", len(c.Codewords))
	}
}

func TestSegmentationChoosesCheapModes(t *testing.T) {
	cases := []struct {
		in    string
		modes []Mode
	}{
		{"0123456789", []Mode{ModeNumeric}},
		{"HELLO WORLD", []Mode{ModeAlnum}},
		{"hello", []Mode{ModeByte}},
		{"ABC12345678901234567", []Mode{ModeAlnum, ModeNumeric}},
		{"https://example.com/12345678901234", []Mode{ModeByte, ModeNumeric}},
	}
	for _, c := range cases {
		segs := OptimalSegments([]byte(c.in), 5)
		if len(segs) != len(c.modes) {
			t.Fatalf("%q: %d segs %+v", c.in, len(segs), segs)
		}
		for i, s := range segs {
			if s.Mode != c.modes[i] {
				t.Errorf("%q seg %d mode %v want %v", c.in, i, s.Mode, c.modes[i])
			}
		}
	}
}

// The DP result must never be bigger than any single-mode encoding or a
// brute-force split into at most 3 runs.
func TestSegmentationOptimalVsBruteForce(t *testing.T) {
	alphabet := "0123456789AB c-é"
	r := newRand(7)
	for trial := 0; trial < 400; trial++ {
		n := 1 + r.Intn(14)
		var sb strings.Builder
		for i := 0; i < n; i++ {
			sb.WriteByte(alphabet[r.Intn(len(alphabet))])
		}
		data := []byte(sb.String())
		dp := totalBits(OptimalSegments(data, 3), 3)
		best := bruteBest(data, 3)
		if dp > best {
			t.Fatalf("%q: dp %d > brute %d", data, dp, best)
		}
	}
}

func bruteBest(data []byte, v int) int {
	n := len(data)
	memo := map[int]int{}
	var rec func(i int) int
	rec = func(i int) int {
		if i == n {
			return 0
		}
		if x, ok := memo[i]; ok {
			return x
		}
		best := 1 << 30
		for j := i + 1; j <= n; j++ {
			chunk := data[i:j]
			for _, m := range []Mode{ModeNumeric, ModeAlnum, ModeByte} {
				if (m == ModeNumeric && !IsNumeric(chunk)) || (m == ModeAlnum && !IsAlnum(chunk)) {
					continue
				}
				b := segBits(Segment{Mode: m, Chars: len(chunk)}, v)
				if b < 0 {
					continue
				}
				if t := b + rec(j); t < best {
					best = t
				}
			}
		}
		memo[i] = best
		return best
	}
	return rec(0)
}

func TestCapacityBoundaries(t *testing.T) {
	// max-size payloads for version 40
	cases := []struct {
		name string
		e    ECC
		fill byte
		n    int
	}{
		{"numeric L", L, '7', 7089}, {"alnum L", L, 'A', 4296}, {"byte L", L, 'x', 2953},
		{"numeric H", H, '7', 3057}, {"byte H", H, 'x', 1273},
	}
	for _, c := range cases {
		opt := Options{ECC: c.e}
		ok, err := Encode([]byte(strings.Repeat(string(c.fill), c.n)), opt)
		if err != nil || ok.Version != 40 {
			t.Fatalf("%s: max payload failed: %v", c.name, err)
		}
		if _, err := Encode([]byte(strings.Repeat(string(c.fill), c.n+1)), opt); err != ErrTooLong {
			t.Fatalf("%s: overflow not rejected: %v", c.name, err)
		}
	}
}

func TestEncodeErrors(t *testing.T) {
	if _, err := Encode([]byte("x"), Options{Mask: 10}); err == nil {
		t.Fatal("bad mask accepted")
	}
	if _, err := Encode([]byte("x"), Options{MinVersion: 5, MaxVersion: 3}); err == nil {
		t.Fatal("bad range accepted")
	}
	if _, err := Encode([]byte(strings.Repeat("a", 100)), Options{MaxVersion: 2}); err != ErrTooLong {
		t.Fatalf("expected ErrTooLong, got %v", err)
	}
}
