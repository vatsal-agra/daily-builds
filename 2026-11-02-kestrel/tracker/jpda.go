package tracker

import (
	"fmt"
	"math"

	"kestrel/assoc"
	"kestrel/filter"
	"kestrel/mat"
)

// maxEvents caps joint-event enumeration per cluster; bigger clusters fall back to GNN.
const maxEvents = 200000

// jpdaClaim: a detection with posterior β ≥ this for some track is "explained" and will not seed a new track.
const jpdaClaim = 0.25

// updateJPDA performs Joint Probabilistic Data Association. Instead of committing to a
// single hard assignment, each track is updated with a probability-weighted blend of every
// detection in its gate. The joint events (every consistent way of explaining the scan)
// are enumerated exactly per cluster of tracks that share detections.
func (t *Tracker) updateJPDA(tm float64, dets []*mat.M, cand [][]*assoc.Candidate, preds []filter.Pred, par assoc.Params, used []bool) error {
	rad := t.cfg.Radar
	// JPDA runs over CONFIRMED tracks only. Tentative tracks have enormous, mostly-clutter gates;
	// letting them into the joint events steals probability mass from real tracks.
	var trs []*Track
	var sc [][]*assoc.Candidate
	var sp []filter.Pred
	var rest []int
	for i, tr := range t.Tracks {
		if tr.Status == Confirmed {
			trs, sc, sp = append(trs, tr), append(sc, cand[i]), append(sp, preds[i])
		} else {
			rest = append(rest, i)
		}
	}
	cand, preds = sc, sp
	n := len(trs)
	for _, tr := range trs {
		if _, ok := tr.F.(*filter.IMM); ok {
			return fmt.Errorf("tracker: JPDA does not support IMM filters")
		}
	}
	// ---- clusters via union-find over shared detections
	parent := make([]int, n)
	for i := range parent {
		parent[i] = i
	}
	var find func(int) int
	find = func(a int) int {
		for parent[a] != a {
			parent[a] = parent[parent[a]]
			a = parent[a]
		}
		return a
	}
	owner := make([]int, len(dets))
	for j := range owner {
		owner[j] = -1
	}
	for i := 0; i < n; i++ {
		for j := range dets {
			if cand[i][j] == nil {
				continue
			}
			if owner[j] < 0 {
				owner[j] = i
			} else {
				parent[find(i)] = find(owner[j])
			}
		}
	}
	clusters := map[int][]int{}
	for i := 0; i < n; i++ {
		r := find(i)
		clusters[r] = append(clusters[r], i)
	}

	beta := make([][]float64, n) // beta[i][j], beta0[i]
	beta0 := make([]float64, n)
	for i := range beta {
		beta[i] = make([]float64, len(dets))
	}
	lam := math.Log(par.ClutterDensity)
	for _, members := range clusters {
		// candidate lists per track
		opts := make([][]int, len(members))
		for a, i := range members {
			for j := range dets {
				if cand[i][j] != nil {
					opts[a] = append(opts[a], j)
				}
			}
		}
		w := make([][]float64, len(members)) // log weights per option
		for a, i := range members {
			for _, j := range opts[a] {
				w[a] = append(w[a], math.Log(par.Pd)+cand[i][j].LogLik-lam)
			}
		}
		lmiss := math.Log(1 - par.Pd)
		type acc struct {
			beta  [][]float64
			beta0 []float64
			total float64
			count int
		}
		A := acc{beta: make([][]float64, len(members)), beta0: make([]float64, len(members))}
		for a := range A.beta {
			A.beta[a] = make([]float64, len(opts[a]))
		}
		takenDet := map[int]bool{}
		choice := make([]int, len(members)) // -1 = miss, else index in opts
		overflow := false
		// weights are accumulated relative to the all-miss event to avoid under/overflow
		var dfs func(a int, logw float64)
		dfs = func(a int, logw float64) {
			if overflow {
				return
			}
			if a == len(members) {
				A.count++
				if A.count > maxEvents {
					overflow = true
					return
				}
				e := math.Exp(logw - float64(len(members))*lmiss)
				A.total += e
				for b, c := range choice {
					if c < 0 {
						A.beta0[b] += e
					} else {
						A.beta[b][c] += e
					}
				}
				return
			}
			choice[a] = -1
			dfs(a+1, logw+lmiss)
			for oi, j := range opts[a] {
				if takenDet[j] {
					continue
				}
				takenDet[j] = true
				choice[a] = oi
				dfs(a+1, logw+w[a][oi])
				takenDet[j] = false
			}
			choice[a] = -1
		}
		dfs(0, 0)
		if overflow {
			// fall back: hard GNN over this cluster
			sub := make([][]*assoc.Candidate, len(members))
			for a, i := range members {
				sub[a] = cand[i]
			}
			pick, err := assoc.GNN(sub, par)
			if err != nil {
				return err
			}
			for a, i := range members {
				if pick[a] < 0 {
					beta0[i] = 1
				} else {
					beta[i][pick[a]] = 1
				}
			}
			continue
		}
		for a, i := range members {
			beta0[i] = A.beta0[a] / A.total
			for oi, j := range opts[a] {
				beta[i][j] = A.beta[a][oi] / A.total
			}
		}
	}

	// ---- per-track probabilistic update
	for i, tr := range trs {
		var js []int
		for j := range dets {
			if beta[i][j] > 1e-9 {
				js = append(js, j)
			}
		}
		if len(js) == 0 || beta0[i] > 0.999999 {
			tr.Score += math.Log(1 - par.Pd)
			t.miss(tr)
			continue
		}
		p := preds[i]
		sinv, err := p.S.Inv()
		if err != nil {
			t.kill(tr, tm, "singular innovation covariance")
			continue
		}
		k := p.Pxz.Mul(sinv)
		ybar := mat.New(2, 1)
		ys := make(map[int]*mat.M, len(js))
		for _, j := range js {
			y := rad.Resid(dets[j], p.Z)
			ys[j] = y
			ybar = ybar.Add(y.Scale(beta[i][j]))
		}
		spread := mat.New(2, 2)
		for _, j := range js {
			spread = spread.Add(ys[j].Mul(ys[j].T()).Scale(beta[i][j]))
		}
		spread = spread.Sub(ybar.Mul(ybar.T()))
		x := tr.F.X().Add(k.Mul(ybar))
		pc := tr.F.P().Sub(k.Mul(p.S).Mul(k.T()))
		pnew := tr.F.P().Scale(beta0[i]).Add(pc.Scale(1 - beta0[i])).Add(k.Mul(spread).Mul(k.T()))
		tr.F.SetState(x, pnew.Sym())
		// data likelihood ratio of this scan for the track: (1-Pd) + Pd·Σ_j N_j/λ
		sum := 1 - par.Pd
		for _, j := range js {
			sum += par.Pd * math.Exp(cand[i][j].LogLik) / par.ClutterDensity
		}
		if 1-beta0[i] >= 0.5 {
			t.hit(tr, filter.Result{})
		} else {
			t.miss(tr)
		}
		tr.Score += math.Log(sum)
		// A detection gated by a confirmed track is never a birth candidate: with soft
		// association it is already (partly) explained, and seeding a new track from it
		// is what makes JPDA breed duplicate "coalesced" tracks.
		if tr.Status == Confirmed {
			for _, j := range js {
				if beta[i][j] >= jpdaClaim {
					used[j] = true
				}
			}
		}
	}
	t.updateTentativeGNN(tm, dets, rest, used, par)
	return nil
}

// updateTentativeGNN associates tentative tracks to the detections JPDA left unclaimed, by hard GNN.
func (t *Tracker) updateTentativeGNN(tm float64, dets []*mat.M, idx []int, used []bool, par assoc.Params) {
	if len(idx) == 0 {
		return
	}
	rad := t.cfg.Radar
	fs := make([]filter.Filter, len(idx))
	for a, i := range idx {
		fs[a] = t.Tracks[i].F
	}
	free := make([]*mat.M, 0, len(dets))
	freeIdx := make([]int, 0, len(dets))
	for j, z := range dets {
		if !used[j] {
			free, freeIdx = append(free, z), append(freeIdx, j)
		}
	}
	cand, preds, err := assoc.Matrix(fs, rad, free, t.gate)
	if err != nil {
		t.pendingErr = err
		return
	}
	pick, err := assoc.GNN(cand, par)
	if err != nil {
		t.pendingErr = err
		return
	}
	for a, i := range idx {
		tr := t.Tracks[i]
		if pick[a] < 0 {
			tr.Score += math.Log(1 - par.Pd)
			t.miss(tr)
			continue
		}
		res, err := tr.F.Correct(rad, preds[a], free[pick[a]])
		if err != nil {
			t.kill(tr, tm, "update failed: "+err.Error())
			continue
		}
		tr.Score += math.Log(par.Pd) + res.LogLik - math.Log(par.ClutterDensity)
		used[freeIdx[pick[a]]] = true
		t.hit(tr, res)
	}
}
