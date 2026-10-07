package simplex

import "math"

// dual runs the bounded dual simplex from a dual-feasible basis. It returns
// Optimal when primal feasible, Infeasible when a row proves emptiness, or
// Cutoff when the (monotone) dual objective exceeds cutoff.
func (s *Solver) dual(cutoff float64) Result {
	m, tot := s.M, s.N+s.M
	cc := make([]float64, m)
	d := make([]float64, tot)
	s.stall = 0
	for {
		if s.Iters > s.MaxIters {
			return IterLimit
		}
		if s.sinceRefac >= refactorEvery {
			if err := s.Refactor(); err != nil {
				return NumFail
			}
		}
		// dual objective = c.x of the basic solution while dual feasible
		if !math.IsInf(cutoff, 1) && !s.perturbed {
			if obj := s.Objective(); obj > cutoff+1e-7*(1+math.Abs(cutoff)) {
				return Cutoff
			}
		}
		// leaving row: most infeasible basic variable
		r, worst := -1, 0.0
		for i, k := range s.Basis {
			x := s.X[k]
			var v float64
			if x < s.Lo[k]-s.tolF(s.Lo[k]) {
				v = s.Lo[k] - x
			} else if x > s.Hi[k]+s.tolF(s.Hi[k]) {
				v = x - s.Hi[k]
			} else {
				continue
			}
			if s.stall > 30 {
				if r < 0 || k < s.Basis[r] {
					r, worst = i, v
				}
			} else if v > worst {
				r, worst = i, v
			}
		}
		if r < 0 {
			return Optimal
		}
		k := s.Basis[r]
		below := s.X[k] < s.Lo[k]
		target := s.Hi[k]
		if below {
			target = s.Lo[k]
		}
		sgn := 1.0 // we need x_r to move by sgn
		if !below {
			sgn = -1
		}
		for i, kk := range s.Basis {
			cc[i] = s.Cost[kk]
		}
		s.reducedCosts(cc, false, d)
		row := s.T[r]
		// Harris pass 1
		tmax := inf
		for j := 0; j < tot; j++ {
			st := s.St[j]
			if st == Basic || s.Lo[j] == s.Hi[j] {
				continue
			}
			t := row[j]
			if math.Abs(t) <= tolPivot {
				continue
			}
			if !dualEligible(st, sgn, t) {
				continue
			}
			if v := (math.Abs(d[j]) + tolOpt) / math.Abs(t); v < tmax {
				tmax = v
			}
		}
		q, bestT := -1, 0.0
		for j := 0; j < tot; j++ {
			st := s.St[j]
			if st == Basic || s.Lo[j] == s.Hi[j] {
				continue
			}
			t := row[j]
			if math.Abs(t) <= tolPivot || !dualEligible(st, sgn, t) {
				continue
			}
			if math.Abs(d[j])/math.Abs(t) <= tmax {
				better := math.Abs(t) > bestT
				if s.stall > 30 {
					better = q < 0 || j < q
				}
				if better {
					q, bestT = j, math.Abs(t)
				}
			}
		}
		if q < 0 {
			if s.sinceRefac > 0 {
				if err := s.Refactor(); err != nil {
					return NumFail
				}
				continue // re-derive the row from fresh factors before claiming a proof
			}
			s.FarkasPos, s.FarkasBasic, s.FarkasUp = r, k, !below
			return Infeasible
		}
		if bestT < tolSmall && s.sinceRefac > 0 {
			if err := s.Refactor(); err != nil {
				return NumFail
			}
			continue
		}
		delta := (s.X[k] - target) / row[q]
		if math.Abs(d[q]) < 1e-11 {
			s.stall++
			if s.stall > 100 && !s.perturbed {
				return Stalled
			}
		} else {
			s.stall = 0
		}
		for i, kk := range s.Basis {
			s.X[kk] -= s.T[i][q] * delta
		}
		s.X[q] += delta
		s.pivot(r, q)
		s.St[q] = Basic
		s.X[k] = target
		if target == s.Hi[k] && s.Lo[k] != s.Hi[k] {
			s.St[k] = AtUpper
		} else {
			s.St[k] = AtLower
		}
	}
}

// dualEligible: can nonbasic column with status st and tableau entry t move
// so that the leaving basic variable moves by sgn?  x_r changes by -t*dz.
func dualEligible(st byte, sgn, t float64) bool {
	switch st {
	case AtLower: // dz > 0 -> need sgn * (-t) > 0
		return sgn*t < 0
	case AtUpper: // dz < 0
		return sgn*t > 0
	case AtFree:
		return true
	}
	return false
}
