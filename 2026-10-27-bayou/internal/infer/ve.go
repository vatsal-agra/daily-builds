// Package infer implements exact inference (enumeration oracle, variable
// elimination, MPE/MAP, junction-tree calibration) and approximate inference
// (likelihood weighting, Gibbs sampling).
package infer

import (
	"errors"
	"fmt"
	"math"
	"sort"

	"bayou/internal/bn"
	"bayou/internal/factor"
)

// ErrImpossible is returned when the evidence has probability zero.
var ErrImpossible = errors.New("evidence has probability zero")

// Result of a posterior query.
type Result struct {
	Posterior   *factor.Factor // normalised joint posterior over the query variables
	LogEvidence float64        // log P(evidence)
	MaxClique   int            // largest intermediate factor scope (VE) – a cost measure
}

func checkQuery(net *bn.Network, query []int, ev bn.Evidence) error {
	seen := map[int]bool{}
	for _, q := range query {
		if q < 0 || q >= len(net.Vars) {
			return fmt.Errorf("query variable id %d out of range", q)
		}
		if seen[q] {
			return fmt.Errorf("query variable %s listed twice", net.Vars[q].Name)
		}
		seen[q] = true
		if _, obs := ev[q]; obs {
			return fmt.Errorf("variable %s is both queried and observed", net.Vars[q].Name)
		}
	}
	for v, s := range ev {
		if v < 0 || v >= len(net.Vars) || s < 0 || s >= net.Card(v) {
			return fmt.Errorf("invalid evidence (variable %d, state %d)", v, s)
		}
	}
	return nil
}

// relevantFactors returns the CPT factors of the ancestors of keep ∪ evidence,
// reduced by the evidence (barren-node pruning: descendants that are neither
// queried nor observed sum to one and are dropped).
func relevantFactors(net *bn.Network, keep []int, ev bn.Evidence) (fs []*factor.Factor, rel map[int]bool) {
	roots := append([]int(nil), keep...)
	for v := range ev {
		roots = append(roots, v)
	}
	rel = net.Ancestors(roots)
	ids := make([]int, 0, len(rel))
	for v := range rel {
		ids = append(ids, v)
	}
	sort.Ints(ids)
	for _, v := range ids {
		f := net.CPTFactor(v)
		for e, s := range ev {
			if f.Has(e) {
				f = f.Reduce(e, s)
			}
		}
		fs = append(fs, f)
	}
	return fs, rel
}

// eliminate removes every variable in vars from the factor list by greedy
// min-fill ordering (on the live interaction graph) using op(sum or max).
// It returns the new list, the elimination sequence and the largest scope seen.
func eliminate(fs []*factor.Factor, vars []int, card func(int) int, isMax bool, arg map[int]*factor.Factor) ([]*factor.Factor, []int, int) {
	todo := map[int]bool{}
	for _, v := range vars {
		todo[v] = true
	}
	var seq []int
	maxScope := 0
	for len(todo) > 0 {
		// interaction neighbours of each todo variable
		best, bf, bw := -1, 0, 0.0
		ids := make([]int, 0, len(todo))
		for v := range todo {
			ids = append(ids, v)
		}
		sort.Ints(ids)
		for _, v := range ids {
			nb := map[int]bool{}
			for _, f := range fs {
				if f.Has(v) {
					for _, u := range f.Vars {
						if u != v {
							nb[u] = true
						}
					}
				}
			}
			list := make([]int, 0, len(nb))
			for u := range nb {
				list = append(list, u)
			}
			sort.Ints(list)
			fill := 0
			for i, a := range list {
				for _, b := range list[i+1:] {
					adj := false
					for _, f := range fs {
						if f.Has(a) && f.Has(b) {
							adj = true
							break
						}
					}
					if !adj {
						fill++
					}
				}
			}
			w := float64(card(v))
			for _, u := range list {
				w *= float64(card(u))
			}
			if best == -1 || fill < bf || (fill == bf && w < bw) {
				best, bf, bw = v, fill, w
			}
		}
		v := best
		var in, out []*factor.Factor
		for _, f := range fs {
			if f.Has(v) {
				in = append(in, f)
			} else {
				out = append(out, f)
			}
		}
		prod := factor.ProductAll(in)
		if len(prod.Vars) > maxScope {
			maxScope = len(prod.Vars)
		}
		var res *factor.Factor
		if isMax {
			res = prod.MaxOut(arg, v)
		} else {
			res = prod.SumOut(v)
		}
		fs = append(out, res)
		seq = append(seq, v)
		delete(todo, v)
	}
	return fs, seq, maxScope
}

// VE computes the posterior joint P(query | ev) by variable elimination.
func VE(net *bn.Network, query []int, ev bn.Evidence) (*Result, error) {
	if err := checkQuery(net, query, ev); err != nil {
		return nil, err
	}
	fs, rel := relevantFactors(net, query, ev)
	qset := map[int]bool{}
	for _, q := range query {
		qset[q] = true
	}
	var elim []int
	for v := range rel {
		if _, obs := ev[v]; !obs && !qset[v] {
			elim = append(elim, v)
		}
	}
	fs, _, ms := eliminate(fs, elim, net.Card, false, nil)
	joint := factor.ProductAll(fs)
	le := joint.LogTotal()
	if math.IsInf(le, -1) {
		return nil, ErrImpossible
	}
	post, _ := joint.Normalized()
	if len(post.Vars) != len(query) {
		return nil, fmt.Errorf("internal error: posterior scope %v does not match query", post.Vars)
	}
	return &Result{Posterior: post, LogEvidence: le, MaxClique: ms}, nil
}

// LogEvidence computes log P(ev) by variable elimination.
func LogEvidence(net *bn.Network, ev bn.Evidence) (float64, error) {
	r, err := VE(net, nil, ev)
	if err != nil {
		return math.Inf(-1), err
	}
	return r.LogEvidence, nil
}

// MAPResult is a maximum-a-posteriori assignment.
type MAPResult struct {
	Assign      map[int]int // chosen states of the MAP variables
	LogJoint    float64     // log P(assign, evidence)
	LogPost     float64     // log P(assign | evidence)
	LogEvidence float64
}

// MAP finds argmax over the states of mapVars of P(mapVars | ev), summing out
// every other hidden variable (marginal MAP). With mapVars = all hidden
// variables this is the most probable explanation (MPE). Ties resolve to the
// lowest state index of the variable eliminated last.
func MAP(net *bn.Network, mapVars []int, ev bn.Evidence) (*MAPResult, error) {
	if err := checkQuery(net, mapVars, ev); err != nil {
		return nil, err
	}
	logPe, err := LogEvidence(net, ev)
	if err != nil {
		return nil, err
	}
	fs, rel := relevantFactors(net, mapVars, ev)
	mset := map[int]bool{}
	for _, m := range mapVars {
		mset[m] = true
	}
	var sumVars []int
	for v := range rel {
		if _, obs := ev[v]; !obs && !mset[v] {
			sumVars = append(sumVars, v)
		}
	}
	fs, _, _ = eliminate(fs, sumVars, net.Card, false, nil)
	arg := map[int]*factor.Factor{}
	fs, seq, _ := eliminate(fs, mapVars, net.Card, true, arg)
	final := factor.ProductAll(fs)
	if len(final.Vars) != 0 {
		return nil, fmt.Errorf("internal error: MAP left scope %v", final.Vars)
	}
	lj := final.LogTotal()
	if math.IsInf(lj, -1) {
		return nil, ErrImpossible
	}
	assign := map[int]int{}
	for i := len(seq) - 1; i >= 0; i-- {
		v := seq[i]
		am := arg[v]
		idx, stride := 0, 1
		for k := len(am.Vars) - 1; k >= 0; k-- {
			s, ok := assign[am.Vars[k]]
			if !ok {
				return nil, fmt.Errorf("internal error: traceback needs unassigned variable %d", am.Vars[k])
			}
			idx += s * stride
			stride *= am.Card[k]
		}
		assign[v] = int(am.Val[idx])
	}
	return &MAPResult{Assign: assign, LogJoint: lj, LogPost: lj - logPe, LogEvidence: logPe}, nil
}

// HiddenVars lists variables not in ev, ascending.
func HiddenVars(net *bn.Network, ev bn.Evidence) []int {
	var h []int
	for v := range net.Vars {
		if _, ok := ev[v]; !ok {
			h = append(h, v)
		}
	}
	return h
}
