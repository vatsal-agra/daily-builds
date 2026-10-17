package huff

import (
	"math/rand"
	"testing"

	"kolmo/internal/bitio"
)

func kraft(l []uint8) float64 {
	s := 0.0
	for _, v := range l {
		if v > 0 {
			s += 1 / float64(uint64(1)<<v)
		}
	}
	return s
}

func TestLengthLimitAndOptimality(t *testing.T) {
	// Fibonacci frequencies force a very deep unconstrained tree.
	f := []int{1, 1}
	for len(f) < 30 {
		f = append(f, f[len(f)-1]+f[len(f)-2])
	}
	l := Lengths(f, 10)
	for _, v := range l {
		if v == 0 || v > 10 {
			t.Fatalf("length %d out of range", v)
		}
	}
	if kraft(l) != 1 {
		t.Fatalf("code not complete: kraft=%v", kraft(l))
	}
	// unconstrained case: known optimal lengths for {1,1,2,4,8}
	l = Lengths([]int{1, 1, 2, 4, 8}, 15)
	want := []uint8{4, 4, 3, 2, 1}
	for i := range want {
		if l[i] != want[i] {
			t.Fatalf("got %v want %v", l, want)
		}
	}
}

func TestSingleAndEmpty(t *testing.T) {
	if l := Lengths([]int{0, 5, 0}, 15); l[1] != 1 {
		t.Fatal("single symbol should get length 1")
	}
	if l := Lengths([]int{0, 0}, 15); l[0] != 0 || l[1] != 0 {
		t.Fatal("no symbols")
	}
}

func TestEncodeDecode(t *testing.T) {
	rng := rand.New(rand.NewSource(2))
	freq := make([]int, 60)
	for i := range freq {
		freq[i] = rng.Intn(1000)
	}
	lens := Lengths(freq, 12)
	codes := Codes(lens)
	var syms []int
	for i := 0; i < 5000; i++ {
		s := rng.Intn(60)
		if lens[s] > 0 {
			syms = append(syms, s)
		}
	}
	w := &bitio.Writer{}
	for _, s := range syms {
		w.WriteBitsRev(codes[s], uint(lens[s]))
	}
	d, err := NewDecoder(lens)
	if err != nil {
		t.Fatal(err)
	}
	r := bitio.NewReader(w.Bytes())
	for i, s := range syms {
		got, err := d.Decode(r)
		if err != nil || got != s {
			t.Fatalf("symbol %d: got %d (%v) want %d", i, got, err, s)
		}
	}
}

func TestRejectsBadCodes(t *testing.T) {
	if _, err := NewDecoder([]uint8{1, 1, 1}); err == nil {
		t.Fatal("over-subscribed code accepted")
	}
	if _, err := NewDecoder([]uint8{2, 2, 2}); err == nil {
		t.Fatal("incomplete multi-symbol code accepted")
	}
}
