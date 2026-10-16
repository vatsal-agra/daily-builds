package backend_test

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"dominion/backend"
	"dominion/front"
	"dominion/ir"
	"dominion/opt"
	"dominion/vm"
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

func compileSrc(t *testing.T, src string, level, regs int) (*backend.Output, *ir.Module) {
	t.Helper()
	m, err := front.Compile(src)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := opt.Optimize(m, level, true); err != nil {
		t.Fatal(err)
	}
	o, err := backend.Compile(m, backend.Config{NumRegs: regs})
	if err != nil {
		t.Fatal(err)
	}
	return o, m
}

const pressure = `fn main(){
  var a=1; var b=2; var c=3; var d=4; var e=5; var f=6; var g=7; var h=8; var i=9; var j=10;
  var s = 0;
  for var k = 0; k < 40; k += 1 {
    s = s + a*k + b*k + c + d + e + f + g + h + i + j;
    a += 1; b += 2; c += 3; d += 1; e += 2; f += 3; g += 1; h += 2; i += 3; j += 1;
  }
  print(s + a + b + c + d + e + f + g + h + i + j);
  return s;
}`

func TestRegisterPressureForcesSpillsAndStaysCorrect(t *testing.T) {
	base, _ := front.Compile(pressure)
	want := base.Run(fuel)
	spills := map[int]int{}
	for _, regs := range []int{4, 6, 8, 16, 40} {
		o, _ := compileSrc(t, pressure, 2, regs)
		got, st := o.Prog.Run(fuel)
		if !got.Same(want) {
			t.Fatalf("regs=%d: %v vs %v", regs, got, want)
		}
		for _, r := range o.Report {
			if r.Name == "main" {
				spills[regs] = r.Spilled
			}
		}
		t.Logf("regs=%2d spilled=%2d cycles=%d memops=%d", regs, spills[regs], st.Cycles, st.MemOps)
	}
	if spills[4] == 0 || spills[4] <= spills[16] {
		t.Errorf("4 registers must spill more than 16: %v", spills)
	}
	if spills[40] != 0 {
		t.Errorf("40 registers should not spill: %v", spills)
	}
}

func TestMoreRegistersNeverMakeProgramsSlower(t *testing.T) {
	var prev int64 = 1 << 62
	for _, regs := range []int{4, 6, 8, 12, 24} {
		o, _ := compileSrc(t, pressure, 2, regs)
		_, st := o.Prog.Run(fuel)
		if st.Cycles > prev+prev/20 { // allow 5% noise from heuristics
			t.Errorf("regs=%d: %d cycles, worse than the smaller register file (%d)", regs, st.Cycles, prev)
		}
		prev = st.Cycles
	}
}

func TestValuesLiveAcrossCallsUseCalleeSavedRegisters(t *testing.T) {
	src := `fn id(x){ if x < 0 { return id(x + 1); } return x; } fn main(){ var a = id(3); var b = id(4); var c = a * b; var d = id(c); return a + b + c + d; }`
	for _, regs := range []int{4, 6, 12} {
		o, _ := compileSrc(t, src, 2, regs)
		got, _ := o.Prog.Run(fuel)
		if got.Ret != 3+4+12+12 {
			t.Fatalf("regs=%d: %v", regs, got)
		}
		p := o.Prog
		cs := p.CallerSaved
		// no value defined before a call and used after may sit in r0..cs-1 → verified end to end by the
		// poisoning VM; additionally the prologue must save every callee-saved register it uses
		saves := 0
		for _, in := range p.Code {
			if in.Op == vm.St && in.Comment == "save callee-saved" {
				saves++
				if in.A.R < cs {
					t.Errorf("regs=%d: saved register r%d is not callee-saved", regs, in.A.R)
				}
			}
		}
		if regs == 12 && saves == 0 {
			t.Error("main keeps values across calls but saved no callee-saved registers")
		}
	}
}

func TestParametersLiveInFrameSlotsAndManyArgumentsWork(t *testing.T) {
	var ps, as, sum []string
	for i := 0; i < 32; i++ {
		ps = append(ps, fmt.Sprintf("p%d", i))
		as = append(as, fmt.Sprint(i+1))
		sum = append(sum, fmt.Sprintf("p%d*%d", i, i+1))
	}
	src := fmt.Sprintf("fn f(%s){ return %s; } fn main(){ return f(%s); }", strings.Join(ps, ","), strings.Join(sum, "+"), strings.Join(as, ","))
	want := 0
	for i := 1; i <= 32; i++ {
		want += i * i
	}
	for lvl := 0; lvl <= 3; lvl++ {
		for _, regs := range []int{4, 12} {
			o, _ := compileSrc(t, src, lvl, regs)
			if got, _ := o.Prog.Run(fuel); got.Ret != int64(want) {
				t.Fatalf("-O%d regs=%d: got %v want %d", lvl, regs, got, want)
			}
		}
	}
}

func TestRecursionDepthTrapMatchesInterpreter(t *testing.T) {
	src := `fn f(n){ return f(n + 1) + 1; } fn main(){ return f(0); }`
	m, _ := front.Compile(src)
	if r := m.Run(fuel); r.Trap != ir.TrapStack {
		t.Fatal(r)
	}
	o, _ := compileSrc(t, src, 0, 8)
	if r, _ := o.Prog.Run(fuel); r.Trap != ir.TrapStack {
		t.Fatalf("vm: %v", r)
	}
}

func TestBackendRejectsBadConfigAndInvalidIR(t *testing.T) {
	m, _ := front.Compile(`fn main(){ return 1; }`)
	for _, n := range []int{1, 3, 65, -4} {
		if _, err := backend.Compile(m, backend.Config{NumRegs: n}); err == nil {
			t.Errorf("NumRegs=%d should be rejected", n)
		}
	}
	// invalid IR (use before def) must be refused rather than miscompiled
	bad, err := ir.Parse("func @main() {\ne:\n  %b = add %a, 1\n  %a = add 1, 1\n  ret %b\n}")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := backend.Compile(bad, backend.Config{}); err == nil || !strings.Contains(err.Error(), "invalid IR") {
		t.Fatalf("got %v", err)
	}
}

func TestCriticalEdgesAreSplitForPhiCopies(t *testing.T) {
	// both successors of the first block have phis: copies need edge blocks
	src := `
func @main() {
entry:
  %c = lt 1, 2
  condbr %c, a, b
a:
  %x = phi [1, entry], [%z, b]
  %y = add %x, 1
  %d = lt %y, 5
  condbr %d, b, exit
b:
  %z = phi [10, entry], [%y, a]
  %e = lt %z, 12
  condbr %e, a, exit
exit:
  %r = phi [%y, a], [%z, b]
  print %r
  ret %r
}`
	m, err := ir.Parse(src)
	if err != nil || m.Verify() != nil {
		t.Fatal(err, m.Verify())
	}
	want := m.Run(fuel)
	for _, regs := range []int{4, 8} {
		o, err := backend.Compile(m, backend.Config{NumRegs: regs})
		if err != nil {
			t.Fatal(err)
		}
		if got, _ := o.Prog.Run(fuel); !got.Same(want) {
			t.Fatalf("regs=%d: %v vs %v", regs, got, want)
		}
	}
}

func TestReportAndDisassembly(t *testing.T) {
	o, _ := compileSrc(t, `fn f(a){ return a+1; } fn main(){ return f(1); }`, 0, 6)
	rep := o.ReportString()
	for _, w := range []string{"function", "main", "callee-saved"} {
		if !strings.Contains(rep, w) {
			t.Errorf("report lacks %q:\n%s", w, rep)
		}
	}
	d := o.Prog.Disasm()
	if !strings.Contains(d, "call") || !strings.Contains(d, "setarg") || !strings.Contains(d, "main:") {
		t.Errorf("listing incomplete:\n%s", d)
	}
}
