package lang

import (
	"fmt"
	"io"
	"math/rand"
	"strings"
	"testing"
)

// Differential test of the exhaustiveness/redundancy analysis against brute force: random match
// expressions over  (t * bool * int)  with  type t = A | B of t | C of t * t  are analysed, and the
// verdict is compared with direct enumeration of every value up to a depth that covers the patterns.

type fv struct { // a value of the universe
	con  string // "A" "B" "C" for t values
	args []*fv
}

func universeT(depth int) []*fv {
	if depth == 0 {
		return []*fv{{con: "A"}}
	}
	prev := universeT(depth - 1)
	out := []*fv{{con: "A"}}
	for _, x := range prev {
		out = append(out, &fv{con: "B", args: []*fv{x}})
	}
	for _, x := range prev {
		for _, y := range prev {
			out = append(out, &fv{con: "C", args: []*fv{x, y}})
		}
	}
	return out
}

// pattern tree for the generator (printed to source and matched by brute force)
type fp struct {
	kind string // wild, A, B, C, or (nested or-pattern), lit (int), bool
	subs []*fp
	lit  int
	b    bool
}

func (p *fp) src() string {
	switch p.kind {
	case "wild":
		return "_"
	case "A":
		return "A"
	case "B":
		return "B (" + p.subs[0].src() + ")"
	case "C":
		return "C (" + p.subs[0].src() + ", " + p.subs[1].src() + ")"
	case "or":
		return "(" + p.subs[0].src() + " | " + p.subs[1].src() + ")"
	case "lit":
		return fmt.Sprint(p.lit)
	case "bool":
		return fmt.Sprint(p.b)
	}
	panic("bad kind")
}

func (p *fp) matchT(v *fv) bool {
	switch p.kind {
	case "wild":
		return true
	case "or":
		return p.subs[0].matchT(v) || p.subs[1].matchT(v)
	case "A", "B", "C":
		if p.kind != v.con {
			return false
		}
		for i, s := range p.subs {
			if !s.matchT(v.args[i]) {
				return false
			}
		}
		return true
	}
	panic("bad kind for t: " + p.kind)
}

func genT(r *rand.Rand, depth int) *fp {
	if depth == 0 {
		if r.Intn(2) == 0 {
			return &fp{kind: "wild"}
		}
		return &fp{kind: "A"}
	}
	switch r.Intn(7) {
	case 0, 1:
		return &fp{kind: "wild"}
	case 2:
		return &fp{kind: "A"}
	case 3:
		return &fp{kind: "B", subs: []*fp{genT(r, depth-1)}}
	case 4:
		return &fp{kind: "or", subs: []*fp{genT(r, depth-1), genT(r, depth-1)}}
	default:
		return &fp{kind: "C", subs: []*fp{genT(r, depth-1), genT(r, depth-1)}}
	}
}

type arm struct{ t, b, i *fp }

func genArm(r *rand.Rand) arm {
	a := arm{t: genT(r, 2)}
	if r.Intn(3) == 0 {
		a.b = &fp{kind: "wild"}
	} else {
		a.b = &fp{kind: "bool", b: r.Intn(2) == 0}
	}
	switch r.Intn(4) {
	case 0, 1:
		a.i = &fp{kind: "wild"}
	default:
		a.i = &fp{kind: "lit", lit: r.Intn(2)}
	}
	return a
}

func (a arm) matches(t *fv, b bool, n int) bool {
	if !a.t.matchT(t) {
		return false
	}
	if a.b.kind == "bool" && a.b.b != b {
		return false
	}
	if a.i.kind == "lit" && a.i.lit != n {
		return false
	}
	return true
}

func TestExhaustivenessAgainstBruteForce(t *testing.T) {
	s, _ := newSession(t)
	s.Interp.M.Out = io.Discard
	if _, err := s.Run("type t = A | B of t | C of t * t", false); err != nil {
		t.Fatal(err)
	}
	uni := universeT(3)
	r := rand.New(rand.NewSource(7))
	exhaustive, nonExh, redundantCases := 0, 0, 0
	for iter := 0; iter < 1500; iter++ {
		n := 1 + r.Intn(5)
		arms := make([]arm, n)
		var b strings.Builder
		b.WriteString("let f x =\n  match x with\n")
		for i := range arms {
			arms[i] = genArm(r)
			fmt.Fprintf(&b, "  | (%s, %s, %s) -> %d\n", arms[i].t.src(), arms[i].b.src(), arms[i].i.src(), i)
		}
		src := b.String()
		outs, err := s.Run(src, false)
		if err != nil {
			t.Fatalf("iter %d: %v\n%s", iter, err, src)
		}
		// brute force: first matching arm of every value (ints 0,1,2 stand for "any other int" too)
		first := make([]bool, n)
		var unmatched bool
		for _, tv := range uni {
			for _, bv := range []bool{false, true} {
				for _, iv := range []int{0, 1, 2} {
					hit := -1
					for k, a := range arms {
						if a.matches(tv, bv, iv) {
							hit = k
							break
						}
					}
					if hit < 0 {
						unmatched = true
					} else {
						first[hit] = true
					}
				}
			}
		}
		gotNonExh := false
		redundant := map[int]bool{}
		for _, w := range outs[len(outs)-1].Warnings {
			if strings.Contains(w.Msg, "not exhaustive") {
				gotNonExh = true
			}
			if strings.Contains(w.Msg, "never match") {
				redundant[w.Span.Start.Line-3] = true // arm i is on source line 3+i
			}
		}
		if gotNonExh != unmatched {
			t.Fatalf("iter %d: checker non-exhaustive=%v but brute force found unmatched=%v\n%s", iter, gotNonExh, unmatched, src)
		}
		for k := range arms {
			if redundant[k] == first[k] {
				t.Fatalf("iter %d: arm %d redundant=%v but brute force says it first-matches=%v\n%s", iter, k, redundant[k], first[k], src)
			}
		}
		if unmatched {
			nonExh++
		} else {
			exhaustive++
		}
		if len(redundant) > 0 {
			redundantCases++
		}
	}
	t.Logf("agreed on %d exhaustive and %d non-exhaustive matches (%d with redundant arms)", exhaustive, nonExh, redundantCases)
	if exhaustive < 50 || nonExh < 50 || redundantCases < 50 {
		t.Errorf("generator is not exercising enough variety: %d/%d/%d", exhaustive, nonExh, redundantCases)
	}
}
