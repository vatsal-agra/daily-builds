package fuzz

import "testing"

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
