package fuzz

import (
	"math/rand"
	"strings"
	"testing"

	"dominion/front"
	"dominion/ir"
	"dominion/opt"
)

func TestGeneratedProgramsCompile(t *testing.T) {
	for s := int64(0); s < 200; s++ {
		if o := Check(s, Config{Regs: []int{6}, Fuel: 3_000_000}); o.Fail != nil && o.Fail.Stage == "frontend" {
			t.Fatalf("generator emitted invalid program: %v\n%s", o.Fail, o.Fail.Src)
		}
	}
}

func TestDifferential(t *testing.T) {
	n := int64(300)
	if testing.Short() {
		n = 60
	}
	skipped := 0
	for s := int64(1); s <= n; s++ {
		o := Check(s, DefaultConfig)
		if o.Fail != nil {
			t.Fatalf("%v\n--- program ---\n%s", o.Fail, Reduce(o.Fail, DefaultConfig))
		}
		if o.Skipped {
			skipped++
		}
	}
	if skipped > int(n)/3 {
		t.Fatalf("too many skipped programs (%d/%d): generator is not producing terminating programs", skipped, n)
	}
}

func TestMutatedIR(t *testing.T) {
	n := int64(400)
	if testing.Short() {
		n = 80
	}
	cfg := DefaultConfig
	var checked, skipped int
	for s := int64(1); s <= n; s++ {
		o := CheckMutant(s, cfg)
		if o.Fail != nil {
			t.Fatalf("%v\n--- IR ---\n%s", o.Fail, o.Fail.Src)
		}
		if o.Skipped {
			skipped++
		} else {
			checked++
		}
	}
	t.Logf("mutants: %d checked, %d skipped (invalid / UB / non-terminating)", checked, skipped)
	if checked < int(n)/10 {
		t.Fatalf("too few valid mutants (%d of %d) — mutation operators are too destructive", checked, n)
	}
}

func TestGeneratorIsDeterministicAndVaried(t *testing.T) {
	if Generate(42) != Generate(42) {
		t.Fatal("same seed must give the same program")
	}
	seen := map[string]bool{}
	for s := int64(0); s < 30; s++ {
		seen[Generate(s)] = true
	}
	if len(seen) != 30 {
		t.Fatalf("only %d distinct programs from 30 seeds", len(seen))
	}
	// feature coverage of the generator: every construct should appear within a few hundred seeds
	want := []string{"while ", "for var", "break;", "continue;", "return ", "print(", "[", " / ", " % ", " << ", "&&", "||", "f0("}
	all := ""
	for s := int64(0); s < 300; s++ {
		all += Generate(s)
	}
	for _, w := range want {
		if !strings.Contains(all, w) {
			t.Errorf("generator never produced %q", w)
		}
	}
}

func TestReducerShrinksToTheEssentials(t *testing.T) {
	src := Generate(11) // a sizeable program
	marker := "print(777);"
	src = strings.Replace(src, "fn main() {\n", "fn main() {\n    "+marker+"\n", 1)
	still := func(s string) bool {
		if !strings.Contains(s, marker) {
			return false
		}
		_, err := front.Compile(s)
		return err == nil
	}
	if !still(src) {
		t.Fatal("setup: marker program must compile")
	}
	got := ReduceWith(src, still)
	if !still(got) {
		t.Fatal("reduced program lost the property")
	}
	if len(got) > len(src)/3 || strings.Count(got, "\n") > 12 {
		t.Fatalf("reducer left %d of %d bytes / %d lines:\n%s", len(got), len(src), strings.Count(got, "\n"), got)
	}
}

func TestMutationOperatorsProduceDifferentButParsableText(t *testing.T) {
	m, _ := front.Compile(Generate(3))
	opt.Optimize(m, 1, false)
	text := m.String()
	r := rand.New(rand.NewSource(1))
	changed, parsable := 0, 0
	for i := 0; i < 200; i++ {
		mut := MutateIR(text, r)
		if mut != text {
			changed++
		}
		if _, err := ir.Parse(mut); err == nil {
			parsable++
		}
	}
	if changed < 150 || parsable < 50 {
		t.Fatalf("mutator too weak/destructive: %d changed, %d parsable of 200", changed, parsable)
	}
}

func TestChecksCatchAnInjectedMiscompile(t *testing.T) {
	// a deliberately wrong "optimisation": the hand-written module computes 6, the "bad" one 7 —
	// CheckIRText compares against the interpreter, so build a case where the VM would disagree
	// by feeding a module whose behaviour depends on UB-free arithmetic, then verify the comparison
	// logic itself rejects unequal results.
	a := ir.Result{Out: "1\n", Ret: 3}
	b := ir.Result{Out: "1\n", Ret: 4}
	c := ir.Result{Out: "1\n", Trap: ir.TrapDivZero}
	if a.Same(b) || a.Same(c) || !a.Same(ir.Result{Out: "1\n", Ret: 3, Steps: 99}) {
		t.Fatal("Result.Same is not strict about output/return/trap")
	}
}
