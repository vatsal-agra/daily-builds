package opt_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"dominion/backend"
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
			// the IR step count is not a cost model (strength reduction adds instructions that are
			// cheaper); compare VM cycles instead
			cyc := func(m *ir.Module) int64 {
				o, err := backend.Compile(m, backend.Config{NumRegs: 12})
				if err != nil {
					t.Fatalf("%s: %v", name, err)
				}
				_, st := o.Prog.Run(fuel)
				return st.Cycles
			}
			base2, _ := front.Compile(src)
			if c0, c1 := cyc(base2), cyc(m); c1 >= c0 {
				t.Errorf("%s -O%d: no speedup (%d vs %d cycles)", name, lvl, c1, c0)
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

// Division / remainder by powers of two are strength-reduced to shifts and masks; the signed
// rounding rules for negative operands are the classic place to go wrong.
func TestStrengthReducedDivision(t *testing.T) {
	src := `
fn probe(x) {
    print(x / 2); print(x / 4); print(x / 8); print(x / 1024);
    print(x % 2); print(x % 4); print(x % 16);
    print((x % 2) == 0); print((x % 8) != 0);
    print(x * 8 + x * 3 - x * 1);
    return 0;
}
fn main() {
    var vals[12];
    vals[0] = 0; vals[1] = 1; vals[2] = -1; vals[3] = 7; vals[4] = -7; vals[5] = 8;
    vals[6] = -8; vals[7] = 1023; vals[8] = -1025; vals[9] = 9223372036854775807;
    vals[10] = -9223372036854775807 - 1; vals[11] = -3;
    for var i = 0; i < 12; i += 1 { probe(vals[i]); }
    return 0;
}`
	base, _ := front.Compile(src)
	want := base.Run(fuel)
	if want.Trap != "" {
		t.Fatal(want)
	}
	for lvl := 1; lvl <= 3; lvl++ {
		m, _ := front.Compile(src)
		if _, err := opt.Optimize(m, lvl, true); err != nil {
			t.Fatal(err)
		}
		if got := m.Run(fuel); !got.Same(want) {
			t.Fatalf("-O%d: strength reduction changed results\n got %q\nwant %q", lvl, got.Out, want.Out)
		}
		o, err := backend.Compile(m, backend.Config{NumRegs: 8})
		if err != nil {
			t.Fatal(err)
		}
		if got, _ := o.Prog.Run(fuel); !got.Same(want) {
			t.Fatalf("-O%d vm mismatch", lvl)
		}
		if lvl >= 2 && strings.Contains(m.String(), "div") {
			t.Errorf("-O%d: division by constant power of two was not strength-reduced:\n%s", lvl, m)
		}
	}
}
