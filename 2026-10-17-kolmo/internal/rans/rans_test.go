package rans

import (
	"bytes"
	"math"
	"math/rand"
	"testing"
)

func TestRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	random := make([]byte, 30000)
	rng.Read(random)
	skew := make([]byte, 30000)
	for i := range skew {
		skew[i] = byte(rng.ExpFloat64() * 4)
	}
	cases := [][]byte{nil, {5}, bytes.Repeat([]byte{9}, 10000), random, skew,
		bytes.Repeat([]byte("hello world, "), 2000)}
	for i, c := range cases {
		for order := 0; order <= 1; order++ {
			enc := Encode(c, order)
			dec, err := Decode(enc, len(c), order)
			if err != nil || !bytes.Equal(dec, c) {
				t.Fatalf("case %d order %d: %v", i, order, err)
			}
		}
	}
}

func TestNearEntropy(t *testing.T) {
	rng := rand.New(rand.NewSource(8))
	src := make([]byte, 200000)
	for i := range src {
		src[i] = byte(rng.ExpFloat64() * 5)
	}
	var cnt [256]float64
	for _, b := range src {
		cnt[b]++
	}
	h := 0.0
	for _, c := range cnt {
		if c > 0 {
			p := c / float64(len(src))
			h -= p * math.Log2(p)
		}
	}
	ideal := h * float64(len(src)) / 8
	got := float64(len(Encode(src, 0)))
	if got > ideal*1.01+400 {
		t.Fatalf("order-0 size %.0f vs entropy bound %.0f", got, ideal)
	}
}

func TestOrder1BeatsOrder0OnMarkov(t *testing.T) {
	src := bytes.Repeat([]byte("abcabcabdabcabc"), 3000)
	if len(Encode(src, 1)) >= len(Encode(src, 0)) {
		t.Fatal("order 1 should win on a deterministic cycle")
	}
}

func TestCorruptNeverPanics(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	src := bytes.Repeat([]byte("some text to squeeze "), 300)
	for order := 0; order <= 1; order++ {
		good := Encode(src, order)
		for i := 0; i < 2000; i++ {
			bad := append([]byte(nil), good...)
			bad[rng.Intn(len(bad))] ^= byte(1 << uint(rng.Intn(8)))
			if rng.Intn(4) == 0 {
				bad = bad[:rng.Intn(len(bad))]
			}
			Decode(bad, len(src), order)
		}
	}
}
