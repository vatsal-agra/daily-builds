package sp

import (
	"fmt"
	"strings"
)

// StepBudget bounds every execution.
const StepBudget = 5_000_000

// Row is one allocator's measured outcome on one input.
type Row struct {
	Allocator string
	K         int
	Alloc     *Allocation
	Static    StaticStats
	Dyn       Stats
	Err       error // allocation or execution error
	Verified  bool  // machine run matched the reference run
}

// CheckTerminates runs the reference interpreter on every input and reports a
// clear error if any run exceeds the step budget (an infinite loop would
// otherwise surface as a confusing per-allocator failure).
func CheckTerminates(f *Function, inputs [][]int64) error {
	for _, in := range inputs {
		if _, err := Run(f, in, StepBudget); err != nil {
			if err == ErrStepLimit {
				return fmt.Errorf("program did not finish within %d steps on input %v (infinite loop?)", StepBudget, in)
			}
			return fmt.Errorf("input %v: %w", in, err)
		}
	}
	return nil
}

// Verify runs the reference IR and the allocated machine code on every input
// vector and demands identical return value, output and memory.
func Verify(f *Function, a *Allocation, inputs [][]int64) (Stats, error) {
	var total Stats
	if len(inputs) == 0 {
		inputs = [][]int64{nil}
	}
	for _, in := range inputs {
		ref, err := Run(f, in, StepBudget)
		if err != nil {
			return total, fmt.Errorf("reference run %v: %w", in, err)
		}
		got, err := Run(a.Machine, in, StepBudget*8)
		if err != nil {
			return total, fmt.Errorf("machine run %v: %w", in, err)
		}
		if err := Equivalent(ref, got); err != nil {
			return total, fmt.Errorf("MISCOMPILE on input %v: %w", in, err)
		}
		total.Steps += got.Stats.Steps
		total.Cycles += got.Stats.Cycles
		total.SpillLoads += got.Stats.SpillLoads
		total.SpillStores += got.Stats.SpillStores
		total.Moves += got.Stats.Moves
		total.MemOps += got.Stats.MemOps
	}
	return total, nil
}

// Compare allocates f with every allocator at a given K and measures each.
// Dynamic stats are totals over all input vectors.
func Compare(f *Function, K int, inputs [][]int64, coalesce bool) []Row {
	return CompareOpt(f, K, inputs, Options{Coalesce: coalesce})
}

// CompareOpt is Compare with full allocation options.
func CompareOpt(f *Function, K int, inputs [][]int64, opt Options) []Row {
	var rows []Row
	for _, name := range Allocators {
		r := Row{Allocator: name, K: K}
		a, err := Allocate(f, name, K, opt)
		if err != nil {
			r.Err = err
			rows = append(rows, r)
			continue
		}
		r.Alloc, r.Static = a, a.Static()
		r.Dyn, r.Err = Verify(f, a, inputs)
		r.Verified = r.Err == nil
		rows = append(rows, r)
	}
	return rows
}

// Sweep compares allocators for every K in [kmin,kmax].
func Sweep(f *Function, kmin, kmax int, inputs [][]int64, coalesce bool) [][]Row {
	var out [][]Row
	for k := kmin; k <= kmax; k++ {
		out = append(out, Compare(f, k, inputs, coalesce))
	}
	return out
}

// FormatTable renders rows as an aligned text table.
func FormatTable(rows []Row) string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "%-7s %3s %7s %6s %6s %6s %7s %9s %8s %8s  %s\n",
		"alloc", "K", "instrs", "sp.ld", "sp.st", "movs", "spilled", "cycles", "dyn.spill", "dyn.mov", "verified")
	for _, r := range rows {
		if r.Alloc == nil {
			fmt.Fprintf(&sb, "%-7s %3d  ERROR: %v\n", r.Allocator, r.K, r.Err)
			continue
		}
		v := "yes"
		if !r.Verified {
			v = "NO: " + r.Err.Error()
		}
		fmt.Fprintf(&sb, "%-7s %3d %7d %6d %6d %6d %7d %9d %8d %8d  %s\n", r.Allocator, r.K,
			r.Static.Instrs, r.Static.SpillLoads, r.Static.SpillStores, r.Static.Moves, r.Alloc.SpilledVars,
			r.Dyn.Cycles, r.Dyn.SpillLoads+r.Dyn.SpillStores, r.Dyn.Moves, v)
	}
	return sb.String()
}
