package sable

import (
	"os"
	"path/filepath"
	"testing"
)

func compileTo(t *testing.T, src string) (*Program, *Module) {
	t.Helper()
	p, err := Parse(src)
	if err != nil {
		t.Fatal(err)
	}
	return p, Lower(p)
}

func TestSSABasic(t *testing.T) {
	src := `func fib(n) { if n < 2 { return n; } return fib(n-1) + fib(n-2); }
func main() { var s = 0; for var i = 0; i < 10; i = i + 1 { s = s + fib(i); print(s); } return s; }`
	p, m := compileTo(t, src)
	want := RunAST(p, 1e7)
	if got := RunIR(m, 1e8); !got.Same(want) {
		t.Fatalf("pre-ssa: %v vs %v", got, want)
	}
	if err := VerifyModule(m, false); err != nil {
		t.Fatal(err)
	}
	for _, f := range m.Funcs {
		Mem2Reg(f)
	}
	if err := VerifyModule(m, true); err != nil {
		t.Fatal(err, "\n", m)
	}
	if got := RunIR(m, 1e8); !got.Same(want) {
		t.Fatalf("ssa: %v vs %v\n%s", got, want, m)
	}
	t.Log(want)
}

func corpus(t *testing.T) map[string]string {
	t.Helper()
	files, _ := filepath.Glob("examples/*.sb")
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

func TestCorpusIRLevels(t *testing.T) {
	for name, src := range corpus(t) {
		p, err := Parse(src)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		want := RunAST(p, 1e8)
		if want.Resource() {
			t.Fatalf("%s: oracle %v", name, want)
		}
		for level := 0; level <= 2; level++ {
			m := Lower(p)
			if err := BuildSSA(m); err != nil {
				t.Fatalf("%s: %v", name, err)
			}
			if _, err := Optimize(m, Options{Level: level, Verify: true}); err != nil {
				t.Fatalf("%s O%d: %v", name, level, err)
			}
			got := RunIR(m, 1e9)
			if !got.Same(want) {
				t.Fatalf("%s O%d: got %v want %v\n%s", name, level, got, want, m)
			}
			t.Logf("%-14s O%d  ir-steps=%d (%v)", name, level, got.Steps, want)
		}
	}
}

func TestCorpusBackend(t *testing.T) {
	for name, src := range corpus(t) {
		p, err := Parse(src)
		if err != nil {
			t.Fatal(err)
		}
		want := RunAST(p, 1e8)
		for _, alg := range []Alg{LinearScan, GraphColor} {
			for _, k := range []int{2, 3, 4, 6, 8, 12} {
				for _, lvl := range []int{0, 2} {
					c, err := CompileAST(p, Config{OptLevel: lvl, Regs: k, Alg: alg, Verify: true})
					if err != nil {
						t.Fatalf("%s %v K=%d O%d: %v", name, alg, k, lvl, err)
					}
					got, st := RunProgram(c.Prog, 1e9)
					if !got.Same(want) {
						t.Fatalf("%s %v K=%d O%d: got %v want %v\n", name, alg, k, lvl, got, want)
					}
					if lvl == 2 && (k == 4 || k == 12) {
						t.Logf("%-14s %-11v K=%2d  instrs=%-8d cycles=%-8d ld/st=%d/%d", name, alg, k, st.Instrs, st.Cycles, st.SpillLoads, st.SpillStores)
					}
				}
			}
		}
	}
}
