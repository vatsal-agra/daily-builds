package infer

import (
	"fmt"
	"math"
	"sort"

	"bayou/internal/bn"
	"bayou/internal/factor"
)

// Outcome is one possible reading of a candidate observation.
type Outcome struct {
	State     int
	Prob      float64        // P(X=state | evidence)
	Posterior *factor.Factor // P(target | evidence, X=state)
}

// VOIRow ranks one candidate observation.
type VOIRow struct {
	Var      int
	Gain     float64 // expected reduction in the target's entropy, nats (= mutual information I(target; X | e))
	Expected float64 // expected entropy of the target after observing X, nats
	Outcomes []Outcome
}

// VOIResult is the ranking of every unobserved variable by information gain.
type VOIResult struct {
	Entropy float64 // current entropy of the target given the evidence, nats
	Rows    []VOIRow
}

// ValueOfInformation ranks the unobserved variables by how much observing each
// would be expected to reduce uncertainty about the target variables:
//
//	gain(X) = H(T | e) − Σ_x P(X=x | e) · H(T | e, X=x) = I(T ; X | e)
//
// It uses one junction-tree calibration per candidate outcome. Candidates
// that are d-separated from the target given e score exactly zero.
func ValueOfInformation(net *bn.Network, target []int, ev bn.Evidence) (*VOIResult, error) {
	if err := checkQuery(net, target, ev); err != nil {
		return nil, err
	}
	if len(target) == 0 {
		return nil, fmt.Errorf("need at least one target variable")
	}
	jt, err := NewJT(net)
	if err != nil {
		return nil, err
	}
	base, err := jt.Calibrate(ev)
	if err != nil {
		return nil, err
	}
	posterior := func(cal *Calibrated, e bn.Evidence) (*factor.Factor, error) {
		if len(target) == 1 {
			return cal.Marginal(target[0]), nil
		}
		if f, err := cal.Joint(target...); err == nil {
			return f, nil
		}
		r, err := VE(net, target, e)
		if err != nil {
			return nil, err
		}
		return r.Posterior, nil
	}
	h0f, err := posterior(base, ev)
	if err != nil {
		return nil, err
	}
	res := &VOIResult{Entropy: h0f.Entropy()}
	isTarget := map[int]bool{}
	for _, t := range target {
		isTarget[t] = true
	}
	for x := range net.Vars {
		if _, obs := ev[x]; obs || isTarget[x] {
			continue
		}
		px := base.Marginal(x).Probs()
		row := VOIRow{Var: x}
		for s, p := range px {
			if p <= 0 {
				continue
			}
			e2 := bn.Evidence{}
			for k, v := range ev {
				e2[k] = v
			}
			e2[x] = s
			cal, err := jt.Calibrate(e2)
			if err != nil {
				return nil, err
			}
			post, err := posterior(cal, e2)
			if err != nil {
				return nil, err
			}
			row.Expected += p * post.Entropy()
			row.Outcomes = append(row.Outcomes, Outcome{State: s, Prob: p, Posterior: post})
		}
		row.Gain = math.Max(0, res.Entropy-row.Expected) // clamp rounding noise
		res.Rows = append(res.Rows, row)
	}
	sort.SliceStable(res.Rows, func(i, j int) bool { return res.Rows[i].Gain > res.Rows[j].Gain })
	return res, nil
}
