package qr

import (
	"bytes"
	"math/rand"
	"testing"
)

func TestGFAxioms(t *testing.T) {
	for a := 1; a < 256; a++ {
		if GFMul(byte(a), GFInv(byte(a))) != 1 {
			t.Fatalf("inverse of %d", a)
		}
		for b := 1; b < 256; b += 7 {
			if GFDiv(GFMul(byte(a), byte(b)), byte(b)) != byte(a) {
				t.Fatalf("div %d %d", a, b)
			}
			// distributivity
			c := byte(a * b)
			if GFMul(byte(a), byte(b)^c) != GFMul(byte(a), byte(b))^GFMul(byte(a), c) {
				t.Fatal("distributive")
			}
		}
	}
	if gfExp[8] != 0x1D || GFPow(255) != 1 || GFPow(-1) != GFInv(2) {
		t.Fatal("exp table")
	}
}

// ISO 18004 Annex I worked example: "01234567" in version 1-M.
func TestRSKnownVector(t *testing.T) {
	data := []byte{0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11}
	want := []byte{0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55}
	if got := RSEncode(data, 10); !bytes.Equal(got, want) {
		t.Fatalf("got % X want % X", got, want)
	}
}

func TestRSCorrectsUpToCapacity(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	for trial := 0; trial < 3000; trial++ {
		ecc := []int{7, 10, 13, 17, 22, 28, 30}[r.Intn(7)]
		k := 1 + r.Intn(255-ecc)
		data := make([]byte, k)
		r.Read(data)
		block := append(append([]byte(nil), data...), RSEncode(data, ecc)...)
		n := len(block)
		// choose e errors and f erasures with 2e+f <= ecc
		f := r.Intn(ecc + 1)
		if f > n {
			f = n
		}
		e := r.Intn((ecc-f)/2 + 1)
		if e+f > n {
			e = n - f
		}
		idx := r.Perm(n)
		bad := append([]byte(nil), block...)
		var er []int
		for _, p := range idx[:f] {
			bad[p] ^= byte(1 + r.Intn(255))
			er = append(er, p)
		}
		for _, p := range idx[f : f+e] {
			bad[p] ^= byte(1 + r.Intn(255))
		}
		if _, err := RSDecode(bad, ecc, er); err != nil {
			t.Fatalf("trial %d ecc=%d n=%d e=%d f=%d: %v", trial, ecc, n, e, f, err)
		}
		if !bytes.Equal(bad, block) {
			t.Fatalf("trial %d: wrong correction", trial)
		}
	}
}

// Beyond capacity the decoder must either fail or (rarely) miscorrect to a
// *valid* codeword — never return success with a non-codeword.
func TestRSBeyondCapacityNeverReturnsGarbage(t *testing.T) {
	r := rand.New(rand.NewSource(2))
	fails := 0
	for trial := 0; trial < 2000; trial++ {
		ecc := 10
		data := make([]byte, 16)
		r.Read(data)
		block := append(append([]byte(nil), data...), RSEncode(data, ecc)...)
		bad := append([]byte(nil), block...)
		for _, p := range r.Perm(len(bad))[:6+r.Intn(8)] {
			bad[p] ^= byte(1 + r.Intn(255))
		}
		in := append([]byte(nil), bad...)
		if _, err := RSDecode(bad, ecc, nil); err != nil {
			fails++
			if !bytes.Equal(bad, in) {
				t.Fatal("failed decode mutated the block")
			}
			continue
		}
		if _, clean := syndromes(bad, ecc); !clean {
			t.Fatal("success returned non-codeword")
		}
	}
	if fails < 1900 {
		t.Fatalf("only %d/2000 rejected", fails)
	}
}

func TestRSBadArgs(t *testing.T) {
	if _, err := RSDecode(make([]byte, 5), 10, nil); err == nil {
		t.Fatal("short block accepted")
	}
	b := append(make([]byte, 5), RSEncode(make([]byte, 5), 4)...)
	if _, err := RSDecode(b, 4, []int{99}); err == nil {
		t.Fatal("bad erasure index accepted")
	}
	if _, err := RSDecode(b, 4, []int{0, 1, 2, 3, 4}); err != ErrTooManyErrors {
		t.Fatal("too many erasures accepted")
	}
}
