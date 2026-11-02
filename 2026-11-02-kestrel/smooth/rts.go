// Package smooth implements the Rauch–Tung–Striebel fixed-interval smoother.
package smooth

import (
	"errors"

	"kestrel/mat"
)

// Step is one recorded filter cycle. For the first step of a sequence only XF/PF are set.
type Step struct {
	F      *mat.M // transition Jacobian used to get from the previous step to this one
	XP, PP *mat.M // predicted state / covariance at this step (before the measurement update)
	XF, PF *mat.M // filtered state / covariance (after the update, or = prediction when missed)
}

// Result is a smoothed estimate for each step.
type Result struct{ X, P []*mat.M }

// RTS runs the backward recursion. Cost O(n·d³).
//
//	C_k   = P_k|k Fᵀ_{k+1} P⁻¹_{k+1|k}
//	x_k|N = x_k|k + C_k (x_{k+1|N} − x_{k+1|k})
//	P_k|N = P_k|k + C_k (P_{k+1|N} − P_{k+1|k}) C_kᵀ
func RTS(steps []Step) (*Result, error) {
	n := len(steps)
	if n == 0 {
		return nil, errors.New("smooth: empty sequence")
	}
	for i, s := range steps {
		if s.XF == nil || s.PF == nil {
			return nil, errors.New("smooth: step without a filtered estimate")
		}
		if i > 0 && (s.F == nil || s.XP == nil || s.PP == nil) {
			return nil, errors.New("smooth: step without its prediction")
		}
	}
	res := &Result{X: make([]*mat.M, n), P: make([]*mat.M, n)}
	res.X[n-1], res.P[n-1] = steps[n-1].XF.Clone(), steps[n-1].PF.Clone()
	for k := n - 2; k >= 0; k-- {
		nx := steps[k+1]
		ppInv, err := nx.PP.Inv()
		if err != nil {
			return nil, err
		}
		c := steps[k].PF.Mul(nx.F.T()).Mul(ppInv)
		res.X[k] = steps[k].XF.Add(c.Mul(res.X[k+1].Sub(nx.XP)))
		res.P[k] = steps[k].PF.Add(c.Mul(res.P[k+1].Sub(nx.PP)).Mul(c.T())).Sym()
	}
	return res, nil
}
