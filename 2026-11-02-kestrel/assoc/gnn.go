package assoc

import (
	"math"

	"kestrel/filter"
	"kestrel/mat"
	"kestrel/model"
)

// Candidate is one (track, detection) pairing that survived gating.
type Candidate struct {
	D2     float64 // Mahalanobis² distance
	LogLik float64 // log N(y; 0, S)
}

// Params are the association tuning knobs.
type Params struct {
	Gate           float64 // Mahalanobis² gate (chi-square quantile)
	Pd             float64 // probability of detection
	ClutterDensity float64 // expected false alarms per unit measurement-space volume
}

// Matrix gates every track against every detection. out[i][j] is nil when the
// pairing falls outside the gate; preds[i] is track i's measurement prediction.
func Matrix(fs []filter.Filter, mm model.Meas, dets []*mat.M, gate float64) (out [][]*Candidate, preds []filter.Pred, err error) {
	out = make([][]*Candidate, len(fs))
	preds = make([]filter.Pred, len(fs))
	for i, f := range fs {
		p, e := f.Measure(mm)
		if e != nil {
			return nil, nil, e
		}
		preds[i] = p
		out[i] = make([]*Candidate, len(dets))
		for j, z := range dets {
			y := mm.Resid(z, p.Z)
			d2, ll, e := filter.Mahalanobis(y, p.S)
			if e != nil {
				return nil, nil, e
			}
			if d2 <= gate {
				out[i][j] = &Candidate{d2, ll}
			}
		}
	}
	return out, preds, nil
}

// GNN performs global-nearest-neighbour association: the jointly optimal one-to-one
// assignment of detections to tracks, where each track may also choose "missed".
//
// Costs are negative log likelihood ratios. Pairing track i with detection j costs
//
//	-ln( Pd · N(y;0,S) / λ ),
//
// declaring track i missed costs -ln(1-Pd). A pairing is therefore only chosen when a
// real target explains the detection better than clutter plus a miss does.
// Returns assign[i] = detection index or -1.
func GNN(cand [][]*Candidate, par Params) ([]int, error) {
	n := len(cand)
	if n == 0 {
		return nil, nil
	}
	m := 0
	if n > 0 {
		m = len(cand[0])
	}
	missCost := -math.Log(math.Max(1-par.Pd, 1e-12))
	cost := make([][]float64, n)
	for i := range cost {
		cost[i] = make([]float64, m+n)
		for j := range cost[i] {
			cost[i][j] = math.Inf(1)
		}
		for j := 0; j < m; j++ {
			if c := cand[i][j]; c != nil {
				cost[i][j] = -(math.Log(par.Pd) + c.LogLik - math.Log(par.ClutterDensity))
			}
		}
		cost[i][m+i] = missCost
	}
	col, _, err := Hungarian(cost)
	if err != nil {
		return nil, err
	}
	out := make([]int, n)
	for i, j := range col {
		if j < m {
			out[i] = j
		} else {
			out[i] = -1
		}
	}
	return out, nil
}
