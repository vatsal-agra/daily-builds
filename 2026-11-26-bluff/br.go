package main

import "math"

// Value is the expected payoff to player 0 when both players follow prof.
func (t *Tree) Value(prof Profile) float64 {
	var f func(id int) float64
	f = func(id int) float64 {
		n := &t.Nodes[id]
		if n.Term {
			return n.Util
		}
		v := 0.0
		for a, k := range n.Kids {
			p := 0.0
			if n.Player == -1 {
				p = n.Prob[a]
			} else {
				p = prof[n.IS][a]
			}
			if p > 0 {
				v += p * f(k)
			}
		}
		return v
	}
	return f(0)
}

// BestResponse computes player i's exact best response to the opponent's strategy in prof
// (prof[i] is ignored). It returns i's best-response profile (pure) and i's expected payoff.
// Info sets are resolved deepest-first; by perfect recall every node of an info set has the same
// depth, so deeper decisions are already fixed when a shallower info set is evaluated.
func (t *Tree) BestResponse(prof Profile, i int) (Profile, float64) {
	// reach probability of each node contributed by chance and the opponent only
	reach := make([]float64, len(t.Nodes))
	var fill func(id int, r float64)
	fill = func(id int, r float64) {
		reach[id] = r
		n := &t.Nodes[id]
		if n.Term {
			return
		}
		for a, k := range n.Kids {
			switch {
			case n.Player == -1:
				fill(k, r*n.Prob[a])
			case n.Player == i:
				fill(k, r)
			default:
				fill(k, r*prof[n.IS][a])
			}
		}
	}
	fill(0, 1)

	br := make(Profile, len(t.Sets))
	for si, s := range t.Sets {
		br[si] = make([]float64, len(s.Actions))
		if s.Player != i {
			copy(br[si], prof[si])
		}
	}
	val := make([]float64, len(t.Nodes))
	done := make([]bool, len(t.Nodes))
	sign := 1.0
	if i == 1 {
		sign = -1
	}
	var value func(id int) float64
	value = func(id int) float64 {
		if done[id] {
			return val[id]
		}
		n := &t.Nodes[id]
		var v float64
		switch {
		case n.Term:
			v = sign * n.Util
		case n.Player == -1:
			for a, k := range n.Kids {
				v += n.Prob[a] * value(k)
			}
		default:
			for a, k := range n.Kids {
				if p := br[n.IS][a]; p > 0 {
					v += p * value(k)
				}
			}
		}
		val[id], done[id] = v, true
		return v
	}

	maxD := 0
	for _, s := range t.Sets {
		if s.Player == i && s.Depth > maxD {
			maxD = s.Depth
		}
	}
	for d := maxD; d >= 0; d-- {
		for si, s := range t.Sets {
			if s.Player != i || s.Depth != d {
				continue
			}
			best, bestV := 0, math.Inf(-1)
			for a := range s.Actions {
				cv := 0.0
				for _, nid := range s.Nodes {
					cv += reach[nid] * value(t.Nodes[nid].Kids[a])
				}
				if cv > bestV+1e-12 {
					best, bestV = a, cv
				}
			}
			br[si][best] = 1
		}
	}
	return br, value(0)
}

// Exploitability returns (BR0 + BR1)/2 : how many chips per hand the average best-responder gains.
// It is 0 exactly at a Nash equilibrium. Also returns the individual best-response values.
func (t *Tree) Exploitability(prof Profile) (expl, br0, br1 float64) {
	_, br0 = t.BestResponse(prof, 0)
	_, br1 = t.BestResponse(prof, 1)
	return (br0 + br1) / 2, br0, br1
}

// Compose builds a profile where player 0 follows a and player 1 follows b.
func (t *Tree) Compose(a, b Profile) Profile {
	out := make(Profile, len(t.Sets))
	for i, s := range t.Sets {
		src := a
		if s.Player == 1 {
			src = b
		}
		out[i] = append([]float64(nil), src[i]...)
	}
	return out
}

// ActionValues returns, for an information set, the expected final payoff (to the acting
// player, in chips including chips already committed) of each action given everyone then
// follows prof. It is conditioned on actually being in the information set.
func (t *Tree) ActionValues(prof Profile, set int) []float64 {
	s := t.Sets[set]
	i := s.Player
	sign := 1.0
	if i == 1 {
		sign = -1
	}
	var val func(id int) float64
	val = func(id int) float64 {
		n := &t.Nodes[id]
		if n.Term {
			return sign * n.Util
		}
		v := 0.0
		for a, k := range n.Kids {
			p := 0.0
			if n.Player == -1 {
				p = n.Prob[a]
			} else {
				p = prof[n.IS][a]
			}
			if p > 0 {
				v += p * val(k)
			}
		}
		return v
	}
	// opponent+chance reach of each node of the set
	reach := func(target int) float64 {
		var f func(id int, r float64) float64
		f = func(id int, r float64) float64 {
			if id == target {
				return r
			}
			n := &t.Nodes[id]
			if n.Term {
				return -1
			}
			for a, k := range n.Kids {
				rr := r
				switch {
				case n.Player == -1:
					rr *= n.Prob[a]
				case n.Player != i:
					rr *= prof[n.IS][a]
				}
				if got := f(k, rr); got >= 0 {
					return got
				}
			}
			return -1
		}
		return f(0, 1)
	}
	out := make([]float64, len(s.Actions))
	tot := 0.0
	for _, nid := range s.Nodes {
		r := reach(nid)
		tot += r
		for a, k := range t.Nodes[nid].Kids {
			out[a] += r * val(k)
		}
	}
	if tot > 0 {
		for a := range out {
			out[a] /= tot
		}
	}
	return out
}
