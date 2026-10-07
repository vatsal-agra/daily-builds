package model

import (
	"math/rand"
	"strings"
	"testing"
)

// Mutation fuzzing: no input may panic the parser, and anything it accepts
// must survive a format/parse round trip with a stable result.
func TestParserMutationFuzz(t *testing.T) {
	r := rand.New(rand.NewSource(77))
	alphabet := []byte("abxyz019 \n\t+-*/:<>=.e\\#()[]_@$,\"'")
	seeds := []string{sample, "Minimize\n o: x\nSubject To\n c: x >= 1\nEnd", "Maximize\n 3x+2y\nSubject To\n a: x+y<=4\nBounds\n x free\nInteger\n y\nEnd"}
	accepted, rejected := 0, 0
	for it := 0; it < 30000; it++ {
		b := []byte(seeds[r.Intn(len(seeds))])
		for k := r.Intn(6); k >= 0; k-- {
			if len(b) == 0 {
				break
			}
			switch r.Intn(3) {
			case 0:
				p := r.Intn(len(b))
				b = append(b[:p], b[p+1:]...)
			case 1:
				p := r.Intn(len(b) + 1)
				b = append(b[:p], append([]byte{alphabet[r.Intn(len(alphabet))]}, b[p:]...)...)
			default:
				b[r.Intn(len(b))] = alphabet[r.Intn(len(alphabet))]
			}
		}
		src := string(b)
		func() {
			defer func() {
				if e := recover(); e != nil {
					t.Fatalf("parser panicked on %q: %v", src, e)
				}
			}()
			m, err := Parse(src)
			if err != nil {
				rejected++
				return
			}
			accepted++
			out := Format(m)
			m2, err := Parse(out)
			if err != nil {
				t.Fatalf("formatted model does not re-parse: %v\ninput: %q\noutput:\n%s", err, src, out)
			}
			if Format(m2) != out {
				t.Fatalf("round trip unstable for %q\n%s\n---\n%s", src, out, Format(m2))
			}
		}()
	}
	if accepted < 1000 || rejected < 1000 {
		t.Fatalf("fuzzer imbalance: accepted %d rejected %d", accepted, rejected)
	}
	_ = strings.TrimSpace
}
