package opt_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

const fuel = 50_000_000

func examples(t *testing.T) map[string]string {
	files, _ := filepath.Glob("../examples/*.dom")
	if len(files) == 0 {
		t.Fatal("no examples found")
	}
	out := map[string]string{}
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		out[filepath.Base(f)] = string(b)
	}
	return out
}

func TestExamplesAllLevels(t *testing.T) {
	for name, src := range examples(t) {
		base, err := front.Compile(src)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		want := base.Run(fuel)
		if want.Trap != "" {
			t.Fatalf("%s: baseline trapped: %v", name, want)
		}
		for lvl := 1; lvl <= 3; lvl++ {
			m, _ := front.Compile(src)
			if _, err := opt.Optimize(m, lvl, true); err != nil {
				t.Fatalf("%s -O%d: %v\n%s", name, lvl, err, m)
			}
			got := m.Run(fuel)
			if !got.Same(want) {
				t.Errorf("%s -O%d: got %v want %v", name, lvl, got, want)
			}
			if got.Steps >= want.Steps {
				t.Errorf("%s -O%d: no speedup (%d vs %d steps)", name, lvl, got.Steps, want.Steps)
			}
		}
	}
}

// every single pass in isolation (after mem2reg) must preserve behaviour
func TestEachPassInIsolation(t *testing.T) {
	for name, src := range examples(t) {
		base, _ := front.Compile(src)
		want := base.Run(fuel)
		for _, p := range opt.PassNames() {
			m, _ := front.Compile(src)
			if _, err := opt.Run(m, []string{"simplifycfg", "mem2reg", p}, opt.Options{Verify: true}); err != nil {
				t.Fatalf("%s/%s: %v", name, p, err)
			}
			if got := m.Run(fuel); !got.Same(want) {
				t.Errorf("%s/%s: got %v want %v", name, p, got, want)
			}
		}
	}
}

func TestRoundTripAfterOpt(t *testing.T) {
	for name, src := range examples(t) {
		m, _ := front.Compile(src)
		want := m.Run(fuel)
		opt.Optimize(m, 2, true)
		m2, err := ir.Parse(m.String())
		if err != nil {
			t.Fatalf("%s: reparse: %v", name, err)
		}
		if err := m2.Verify(); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if got := m2.Run(fuel); !got.Same(want) {
			t.Errorf("%s: %v vs %v", name, got, want)
		}
	}
}

func TestMem2RegRemovesAllScalarAllocas(t *testing.T) {
	m, _ := front.Compile(`fn main(){ var s=0; for var i=0;i<10;i+=1 { s+=i; } return s; }`)
	opt.Run(m, []string{"simplifycfg", "mem2reg"}, opt.Options{Verify: true})
	if strings.Contains(m.String(), "alloca") || strings.Contains(m.String(), "load") {
		t.Fatalf("scalar memory remains:\n%s", m)
	}
	if !strings.Contains(m.String(), "phi") {
		t.Fatalf("expected phis:\n%s", m)
	}
}
