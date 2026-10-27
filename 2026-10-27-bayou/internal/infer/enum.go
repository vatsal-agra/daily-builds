package infer

import (
	"fmt"
	"math"

	"bayou/internal/bn"
	"bayou/internal/factor"
)

// MaxEnumStates bounds brute-force enumeration.
const MaxEnumStates = 1 << 24

// Enumerate computes P(query | ev) by summing the full joint distribution.
// It is exponential on purpose: it is the oracle every other engine is tested
// against, and shares no code with them beyond the CPT arrays.
func Enumerate(net *bn.Network, query []int, ev bn.Evidence) (*Result, error) {
	if err := checkQuery(net, query, ev); err != nil {
		return nil, err
	}
	total := 1
	for v := range net.Vars {
		total *= net.Card(v)
		if total > MaxEnumStates {
			return nil, fmt.Errorf("enumeration refused: joint has more than %d states", MaxEnumStates)
		}
	}
	qcard := make([]int, len(query))
	qsize := 1
	for i, q := range query {
		qcard[i] = net.Card(q)
		qsize *= qcard[i]
	}
	acc := make([]float64, qsize) // unnormalised, indexed with query[0] slowest
	assign := make([]int, len(net.Vars))
	for {
		ok := true
		for v, s := range ev {
			if assign[v] != s {
				ok = false
				break
			}
		}
		if ok {
			p := 1.0
			for v := range net.Vars {
				p *= net.Vars[v].CPT[net.RowIndex(v, assign)*net.Card(v)+assign[v]]
			}
			qi := 0
			for i, q := range query {
				qi = qi*qcard[i] + assign[q]
			}
			acc[qi] += p
		}
		k := len(assign) - 1
		for ; k >= 0; k-- {
			assign[k]++
			if assign[k] < net.Card(k) {
				break
			}
			assign[k] = 0
		}
		if k < 0 {
			break
		}
	}
	sum := 0.0
	for _, x := range acc {
		sum += x
	}
	if sum == 0 {
		return nil, ErrImpossible
	}
	// Build a factor in sorted-variable layout from the query-ordered table.
	vars := append([]int(nil), query...)
	f := factor.New(vars, qcard, nil)
	for i := range f.Val {
		f.Val[i] = 0
	}
	cnt := make([]int, len(query))
	for qi := 0; qi < qsize; qi++ {
		// decode qi into cnt (query order)
		r := qi
		for i := len(query) - 1; i >= 0; i-- {
			cnt[i] = r % qcard[i]
			r /= qcard[i]
		}
		assignMap := map[int]int{}
		for i, q := range query {
			assignMap[q] = cnt[i]
		}
		idx, stride := 0, 1
		for k := len(f.Vars) - 1; k >= 0; k-- {
			idx += assignMap[f.Vars[k]] * stride
			stride *= f.Card[k]
		}
		f.Val[idx] = acc[qi] / sum
	}
	// factor.New rescaled the all-ones table; reset scale after filling.
	f.LogScale = 0
	post, _ := f.Normalized()
	return &Result{Posterior: post, LogEvidence: math.Log(sum)}, nil
}
