package tabula

import (
	"fmt"
	"strings"
	"time"
)

// Options control Solve.
type Options struct {
	Seed         int64
	ConstructFor time.Duration // budget for the feasibility search
	AnnealFor    time.Duration // budget for optimisation (0 = skip)
	AnnealIters  int           // if >0, fixed iteration count instead of time (deterministic)
	Previous     *Assignment   // for re-solving with minimal disruption
}

// Report summarises a solve.
type Report struct {
	Diagnostics []Diagnostic
	Construct   *ConstructResult
	Anneal      AnnealStats
	Initial     int // cost right after construction
	Elapsed     time.Duration
}

// Solve runs diagnostics, construction and optimisation. On failure the
// returned error carries the reason; Report is always non-nil.
func (in *Instance) Solve(o Options) (*Assignment, *Report, error) {
	t0 := time.Now()
	rep := &Report{}
	rep.Diagnostics = in.Diagnose()
	if HasFatal(rep.Diagnostics) {
		rep.Elapsed = time.Since(t0)
		return nil, rep, fmt.Errorf("no timetable can exist: %s", firstFatal(rep.Diagnostics))
	}
	if o.ConstructFor == 0 {
		o.ConstructFor = 20 * time.Second
	}
	in.prev = o.Previous
	// Stage 1: complete backtracking search (fast on easy/medium instances, and the only
	// stage that can say "give up" cheaply). Stage 2: min-conflicts tabu repair for tight ones.
	btBudget := o.ConstructFor / 4
	if btBudget > time.Second {
		btBudget = time.Second
	}
	cr := in.Construct(o.Seed, btBudget, o.Previous)
	rep.Construct = cr
	if cr.A == nil {
		a, left, conflicts := in.Repair(o.Seed, o.ConstructFor-btBudget, o.Previous)
		if a == nil {
			rep.Elapsed = time.Since(t0)
			return nil, rep, fmt.Errorf("could not find a timetable without clashes in %s: best attempt still has %d hard violation(s) [%s]; hardest sessions: %v",
				o.ConstructFor, left, strings.Join(conflicts, "; "), cr.Hardest)
		}
		cr.A, cr.UsedRepair = a, true
	}
	rep.Initial, _ = in.Cost(cr.A)
	a := cr.A
	if o.AnnealFor > 0 || o.AnnealIters > 0 {
		a, rep.Anneal = in.Anneal(cr.A, o.Seed+1, o.AnnealFor, o.AnnealIters)
	}
	rep.Elapsed = time.Since(t0)
	return a, rep, nil
}

func firstFatal(ds []Diagnostic) string {
	for _, d := range ds {
		if d.Fatal {
			return d.Msg
		}
	}
	return ""
}
