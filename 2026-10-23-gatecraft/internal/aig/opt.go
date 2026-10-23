package aig

import "time"

// PassReport records one optimisation step.
type PassReport struct {
	Name          string
	Before, After Stats
	Elapsed       time.Duration
	Note          string
}

// OptOptions selects the pipeline.
type OptOptions struct {
	Seed       int64
	Iterations int  // maximum full-pipeline iterations (default 3)
	NoFraig    bool // skip SAT sweeping
	NoSeq      bool // skip sequential cleanup
	// Check, if set, is called after every pass with (before, after); a non-nil error aborts.
	Check func(pass string, before, after *AIG) error
}

// Optimize runs sweep → rewrite → balance → fraig → seqclean to a fixpoint.
func Optimize(g *AIG, o OptOptions) (*AIG, []PassReport, error) {
	if o.Iterations == 0 {
		o.Iterations = 3
	}
	var reports []PassReport
	cur := g
	step := func(name string, f func(*AIG) (*AIG, string)) error {
		t0 := time.Now()
		before := cur.Stats()
		next, note := f(cur)
		rep := PassReport{Name: name, Before: before, After: next.Stats(), Elapsed: time.Since(t0), Note: note}
		if o.Check != nil {
			if err := o.Check(name, cur, next); err != nil {
				return err
			}
		}
		reports = append(reports, rep)
		cur = next
		return nil
	}
	plain := func(f func(*AIG) *AIG) func(*AIG) (*AIG, string) {
		return func(a *AIG) (*AIG, string) { return f(a), "" }
	}
	if err := step("sweep", plain(Sweep)); err != nil {
		return nil, reports, err
	}
	for it := 0; it < o.Iterations; it++ {
		start := cur.Stats()
		if err := step("rewrite", plain(Rewrite)); err != nil {
			return nil, reports, err
		}
		if !o.NoFraig {
			if err := step("fraig", func(a *AIG) (*AIG, string) {
				r, st := Fraig(a, o.Seed+int64(it))
				return r, fmtFraig(st)
			}); err != nil {
				return nil, reports, err
			}
		}
		if !o.NoSeq {
			if err := step("seqclean", func(a *AIG) (*AIG, string) {
				r, n := SeqClean(a)
				return r, fmtSeq(n)
			}); err != nil {
				return nil, reports, err
			}
		}
		if err := step("balance", plain(Balance)); err != nil {
			return nil, reports, err
		}
		end := cur.Stats()
		if end.Ands >= start.Ands && end.Latches >= start.Latches && end.Depth >= start.Depth {
			break
		}
	}
	return cur, reports, nil
}

func fmtFraig(s FraigStats) string {
	return "candidates=" + itoa(s.Candidates) + " proved=" + itoa(s.Proved) + " refuted=" + itoa(s.Refuted) + " rounds=" + itoa(s.Rounds)
}
func fmtSeq(n int) string { return "latches removed=" + itoa(n) }

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}
