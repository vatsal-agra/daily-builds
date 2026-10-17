package crc

import (
	"hash/crc32"
	"math/rand"
	"testing"
)

func TestMatchesStdlib(t *testing.T) {
	if Sum([]byte("123456789")) != 0xCBF43926 {
		t.Fatal("check value wrong")
	}
	rng := rand.New(rand.NewSource(1))
	for n := 0; n < 300; n++ {
		b := make([]byte, n)
		rng.Read(b)
		if Sum(b) != crc32.ChecksumIEEE(b) {
			t.Fatalf("len %d mismatch", n)
		}
	}
	a, b := []byte("hello "), []byte("world")
	if Update(Sum(a), b) != Sum([]byte("hello world")) {
		t.Fatal("incremental update broken")
	}
}
