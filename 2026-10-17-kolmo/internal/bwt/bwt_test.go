package bwt

import (
	"bytes"
	"math/rand"
	"sort"
	"testing"
)

func naiveBWT(s []byte) ([]byte, int) {
	n := len(s)
	idx := make([]int, n)
	for i := range idx {
		idx[i] = i
	}
	rot := func(i int) []byte { return append(append([]byte{}, s[i:]...), s[:i]...) }
	sort.SliceStable(idx, func(a, b int) bool { return bytes.Compare(rot(idx[a]), rot(idx[b])) < 0 })
	last := make([]byte, n)
	prim := -1
	for r, i := range idx {
		last[r] = s[(i+n-1)%n]
		if i == 0 && prim < 0 {
			prim = r
		}
	}
	return last, prim
}

func TestTransformMatchesNaive(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	for trial := 0; trial < 400; trial++ {
		n := 1 + rng.Intn(60)
		alpha := 1 + rng.Intn(4)
		s := make([]byte, n)
		for i := range s {
			s[i] = byte('a' + rng.Intn(alpha))
		}
		got, gp := Transform(s)
		want, wp := naiveBWT(s)
		if !bytes.Equal(got, want) {
			t.Fatalf("%q: bwt %q want %q", s, got, want)
		}
		_ = wp
		inv, err := Inverse(got, gp)
		if err != nil || !bytes.Equal(inv, s) {
			t.Fatalf("%q: inverse gave %q (%v)", s, inv, err)
		}
	}
}

func TestBananaKnown(t *testing.T) {
	last, p := Transform([]byte("banana"))
	if string(last) != "nnbaaa" || p != 3 {
		t.Fatalf("got %q %d", last, p)
	}
}

func TestCodecRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(5))
	random := make([]byte, 50000)
	rng.Read(random)
	cases := [][]byte{nil, {7}, bytes.Repeat([]byte{0}, 100000), bytes.Repeat([]byte("abc"), 30000), random,
		bytes.Repeat([]byte("the rain in spain falls mainly on the plain\n"), 4000),
		make([]byte, BlockSize+12345)} // spans two blocks
	for i, c := range cases {
		enc := Encode(c)
		dec, err := Decode(enc, len(c))
		if err != nil || !bytes.Equal(dec, c) {
			t.Fatalf("case %d: %v", i, err)
		}
	}
}

func TestDecodeCorruptNeverPanics(t *testing.T) {
	rng := rand.New(rand.NewSource(9))
	src := bytes.Repeat([]byte("compress me please, "), 500)
	good := Encode(src)
	for i := 0; i < 3000; i++ {
		bad := append([]byte(nil), good...)
		for k := 0; k < 1+rng.Intn(3); k++ {
			bad[rng.Intn(len(bad))] ^= byte(1 << uint(rng.Intn(8)))
		}
		if rng.Intn(4) == 0 {
			bad = bad[:rng.Intn(len(bad))]
		}
		Decode(bad, len(src))
	}
}

func TestCompressesText(t *testing.T) {
	src := bytes.Repeat([]byte("the rain in spain falls mainly on the plain\n"), 4000)
	if len(Encode(src))*20 > len(src) {
		t.Fatalf("poor ratio: %d -> %d", len(src), len(Encode(src)))
	}
}
