package lang

import (
	"io"
	"testing"
)

func BenchmarkSort100k(b *testing.B) {
	for i := 0; i < b.N; i++ {
		s, err := NewSession(io.Discard)
		if err != nil {
			b.Fatal(err)
		}
		if _, err := s.Run(`let xs = map (fun i -> (i * 7919) mod 100003) (range 0 100000)
let s = sort compare xs`, true); err != nil {
			b.Fatal(err)
		}
	}
}
