package sp

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func mustParse(t *testing.T, src string) *Function {
	t.Helper()
	f, err := Parse(src)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return f
}

func TestInterpreterHandComputed(t *testing.T) {
	f := mustParse(t, `func f(2) {
e:
  a = arg 0
  b = arg 1
  s = add a, b
  p = mul s, 3
  d = div p, 0
  q = rem 17, 5
  print p
  print d
  print q
  ret p
}`)
	r, err := Run(f, []int64{4, 6}, 1000)
	if err != nil {
		t.Fatal(err)
	}
	if r.Ret != 30 || len(r.Output) != 3 || r.Output[0] != 30 || r.Output[1] != 0 || r.Output[2] != 2 {
		t.Fatalf("got ret=%d out=%v", r.Ret, r.Output)
	}
}

func TestLivenessHandComputed(t *testing.T) {
	f := mustParse(t, `func f(1) {
e:
  n = arg 0
  s = const 0
  jmp h
h:
  c = lt s, n
  br c, b, d
b:
  s = add s, 1
  jmp h
d:
  ret s
}`)
	lv := f.Liveness()
	name := func(b Bitset) string {
		var out []string
		b.each(func(r int) { out = append(out, f.RegName(r)) })
		return strings.Join(out, ",")
	}
	// registers are numbered by first appearance: n=0 s=1 c=2
	if got := name(lv.In[1]); got != "n,s" {
		t.Errorf("live-in(h)=%q want n,s", got)
	}
	if got := name(lv.Out[2]); got != "n,s" {
		t.Errorf("live-out(b)=%q want n,s", got)
	}
	if got := name(lv.In[3]); got != "s" {
		t.Errorf("live-in(d)=%q want s", got)
	}
	if d := f.LoopDepth(); d[0] != 0 || d[1] != 1 || d[2] != 1 || d[3] != 0 {
		t.Errorf("loop depth %v", d)
	}
}

func TestAllocatorsOnExamples(t *testing.T) {
	files, _ := filepath.Glob("../examples/*.ir")
	if len(files) < 5 {
		t.Fatalf("expected examples, found %d", len(files))
	}
	for _, p := range files {
		src, _ := os.ReadFile(p)
		f := mustParse(t, string(src))
		if err := f.Validate(); err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		for _, al := range Allocators {
			for _, K := range []int{3, 4, 6, 9, 16} {
				a, err := Allocate(f, al, K, Options{Coalesce: true})
				if err != nil {
					t.Fatalf("%s %s K=%d: %v", p, al, K, err)
				}
				if _, err := Verify(f, a, [][]int64{{0}, {1}, {7}, {20}}); err != nil {
					t.Fatalf("%s %s K=%d: %v", p, al, K, err)
				}
			}
		}
	}
}
