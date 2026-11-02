package tracker

import (
	"kestrel/mat"
	"kestrel/metrics"
	"kestrel/sim"
)

// FrameEst is the confirmed-track picture after one scan.
type FrameEst struct {
	K, T   float64
	Tracks []metrics.Pt
	Truth  []metrics.Pt
}

// Run is a completed tracker-vs-scenario experiment.
type Run struct {
	Scenario sim.Scenario
	Frames   []sim.Frame
	Tracker  *Tracker
	Est      []FrameEst
	Score    metrics.Summary
	OSPA     []float64
}

// RunFrames feeds pre-generated frames to a fresh tracker and scores it against truth.
func RunFrames(sc sim.Scenario, frames []sim.Frame, cfg Config) (*Run, error) {
	tr, err := New(cfg)
	if err != nil {
		return nil, err
	}
	scorer := metrics.NewScorer(1000)
	run := &Run{Scenario: sc, Frames: frames, Tracker: tr}
	for _, fr := range frames {
		zs := make([]*mat.M, len(fr.Dets))
		for i, d := range fr.Dets {
			zs[i] = d.Z
		}
		if err := tr.Step(fr.T, zs); err != nil {
			return nil, err
		}
		var truth, est []metrics.Pt
		for _, g := range fr.Truth {
			if !g.InCoverage {
				continue // a target the radar cannot see is not the tracker's fault
			}
			truth = append(truth, metrics.Pt{ID: g.ID, X: g.X, Y: g.Y})
		}
		for _, c := range tr.Confirmed() {
			x := c.F.X()
			est = append(est, metrics.Pt{ID: c.ID, X: x.D[0], Y: x.D[2]})
		}
		if err := scorer.Add(truth, est); err != nil {
			return nil, err
		}
		run.Est = append(run.Est, FrameEst{K: float64(fr.K), T: fr.T, Tracks: est, Truth: truth})
	}
	run.Score = scorer.Summary()
	run.OSPA = scorer.OSPA
	return run, nil
}
