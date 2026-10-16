package backend_test

import (
	"os"
	"path/filepath"
	"testing"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

const fuel = 100_000_000

func TestExamplesOnVM(t *testing.T) {
	files, _ := filepath.Glob("../examples/*.dom")
	if len(files) == 0 {
		t.Fatal("no examples")
	}
	for _, fn := range files {
		b, _ := os.ReadFile(fn)
		name := filepath.Base(fn)
		base, err := front.Compile(string(b))
		if err != nil {
			t.Fatal(err)
		}
		want := base.Run(fuel)
		for lvl := 0; lvl <= 3; lvl++ {
			m, _ := front.Compile(string(b))
			if _, err := opt.Optimize(m, lvl, true); err != nil {
				t.Fatal(err)
			}
			for _, regs := range []int{4, 5, 6, 8, 12, 16, 32} {
				out, err := backend.Compile(m, backend.Config{NumRegs: regs})
				if err != nil {
					t.Fatalf("%s -O%d regs=%d: %v", name, lvl, regs, err)
				}
				got, _ := out.Prog.Run(fuel)
				if !got.Same(want) {
					t.Errorf("%s -O%d regs=%d: vm %v, want %v", name, lvl, regs, got, want)
				}
			}
		}
	}
}

func TestBackendDoesNotMutateInput(t *testing.T) {
	m, _ := front.Compile(`fn f(a){ if a > 1 { return a; } return 2; } fn main(){ var s=0; for var i=0;i<5;i+=1 { s+=f(i); } return s; }`)
	opt.Optimize(m, 2, true)
	before := m.String()
	if _, err := backend.Compile(m, backend.Config{NumRegs: 6}); err != nil {
		t.Fatal(err)
	}
	if m.String() != before {
		t.Fatal("backend mutated its input module")
	}
	var _ ir.Result
}
