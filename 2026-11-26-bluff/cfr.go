package main

// Solver runs CFR+ (Tammelin 2014): regret-matching+ (regrets floored at zero),
// alternating player updates, and linear averaging of the strategy.
type Solver struct {
	T      *Tree
	regret [][]float64
	inc    [][]float64
	sum    [][]float64
	Iter   int
}

// NewSolver prepares a solver over a compiled tree.
func NewSolver(t *Tree) *Solver {
	s := &Solver{T: t}
	for _, is := range t.Sets {
		n := len(is.Actions)
		s.regret = append(s.regret, make([]float64, n))
		s.inc = append(s.inc, make([]float64, n))
		s.sum = append(s.sum, make([]float64, n))
	}
	return s
}

func regretMatch(reg []float64, out []float64) {
	tot := 0.0
	for _, r := range reg {
		if r > 0 {
			tot += r
		}
	}
	for i, r := range reg {
		switch {
		case tot > 0 && r > 0:
			out[i] = r / tot
		case tot > 0:
			out[i] = 0
		default:
			out[i] = 1 / float64(len(reg))
		}
	}
}

// Step runs one CFR+ iteration (one pass for each player).
func (s *Solver) Step() {
	s.Iter++
	for p := 0; p < 2; p++ {
		s.walk(0, p, 1, 1)
		for i, is := range s.T.Sets {
			if is.Player != p {
				continue
			}
			for a := range s.regret[i] {
				v := s.regret[i][a] + s.inc[i][a]
				if v < 0 {
					v = 0
				}
				s.regret[i][a] = v
				s.inc[i][a] = 0
			}
		}
	}
}

func (s *Solver) walk(id, i int, piI, piO float64) float64 {
	n := &s.T.Nodes[id]
	if n.Term {
		if i == 0 {
			return n.Util
		}
		return -n.Util
	}
	if n.Player == -1 {
		v := 0.0
		for a, k := range n.Kids {
			v += n.Prob[a] * s.walk(k, i, piI, piO*n.Prob[a])
		}
		return v
	}
	na := len(n.Kids)
	strat := make([]float64, na)
	regretMatch(s.regret[n.IS], strat)
	if n.Player == i {
		util := make([]float64, na)
		v := 0.0
		for a, k := range n.Kids {
			util[a] = s.walk(k, i, piI*strat[a], piO)
			v += strat[a] * util[a]
		}
		w := float64(s.Iter)
		for a := range util {
			s.inc[n.IS][a] += piO * (util[a] - v)
			s.sum[n.IS][a] += w * piI * strat[a]
		}
		return v
	}
	v := 0.0
	for a, k := range n.Kids {
		v += strat[a] * s.walk(k, i, piI, piO*strat[a])
	}
	return v
}

// Average returns the time-averaged (equilibrium-approximating) strategy.
func (s *Solver) Average() Profile {
	p := make(Profile, len(s.sum))
	for i, row := range s.sum {
		p[i] = make([]float64, len(row))
		tot := 0.0
		for _, v := range row {
			tot += v
		}
		for a, v := range row {
			if tot > 0 {
				p[i][a] = v / tot
			} else {
				p[i][a] = 1 / float64(len(row))
			}
		}
	}
	return p
}
