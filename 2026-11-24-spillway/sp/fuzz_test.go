package sp

import "testing"

func TestFuzzQuick(t *testing.T) {
	rep := Fuzz(150, 1, []int{3, 4, 5, 8, 16}, DefaultGen)
	for _, f := range rep.Failures {
		t.Error(f)
	}
	t.Logf("programs=%d allocations=%d executions=%d spilly=%d", rep.Programs, rep.Allocations, rep.Executions, rep.Spilly)
}

func TestFuzzHeavy(t *testing.T) {
	if testing.Short() {
		t.Skip("short")
	}
	rep := Fuzz(500, 1000, []int{3, 4, 6, 10, 24}, GenConfig{Vars: 24, Depth: 4, Stmts: 8})
	for i, f := range rep.Failures {
		if i < 10 {
			t.Error(f)
		}
	}
	t.Logf("programs=%d allocations=%d executions=%d spilly=%d failures=%d", rep.Programs, rep.Allocations, rep.Executions, rep.Spilly, len(rep.Failures))
}
