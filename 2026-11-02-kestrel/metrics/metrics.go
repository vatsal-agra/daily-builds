// Package metrics scores trackers: OSPA, RMSE, ID switches, and statistical consistency (NEES/NIS).
package metrics

import (
	"errors"
	"math"

	"kestrel/assoc"
	"kestrel/stat"
)

// Pt is a labelled 2-D position.
type Pt struct {
	ID   int
	X, Y float64
}

func dist(a, b Pt) float64 { return math.Hypot(a.X-b.X, a.Y-b.Y) }

// OSPA is the Optimal Sub-Pattern Assignment distance (Schuhmacher, Vo & Vo 2008) with cutoff c
// and order p: it blends localisation error and cardinality error into one number in [0, c].
// It also returns the two components.
func OSPA(truth, est []Pt, c, p float64) (total, loc, card float64, err error) {
	if c <= 0 || p < 1 {
		return 0, 0, 0, errors.New("metrics: OSPA needs c>0 and p>=1")
	}
	m, n := len(truth), len(est)
	if m == 0 && n == 0 {
		return 0, 0, 0, nil
	}
	if m == 0 || n == 0 {
		return c, 0, c, nil
	}
	a, b := truth, est
	if m > n {
		a, b = est, truth
	}
	cost := make([][]float64, len(a))
	for i := range a {
		cost[i] = make([]float64, len(b))
		for j := range b {
			cost[i][j] = math.Pow(math.Min(dist(a[i], b[j]), c), p)
		}
	}
	_, sum, err := assoc.Hungarian(cost)
	if err != nil {
		return 0, 0, 0, err
	}
	big := float64(max(m, n))
	cardTerm := math.Pow(c, p) * float64(max(m, n)-min(m, n))
	total = math.Pow((sum+cardTerm)/big, 1/p)
	loc = math.Pow(sum/big, 1/p)
	card = math.Pow(cardTerm/big, 1/p)
	return
}

// Summary aggregates a whole run.
type Summary struct {
	Frames            int
	MeanOSPA          float64
	MeanLoc, MeanCard float64
	PosRMSE           float64 // over matched truth/track pairs
	IDSwitches        int
	FalseTrackScans   int // confirmed-track-scans matched to no target
	MissedScans       int // truth-scans with no confirmed track
	TruthScans        int
	Coverage          float64 // 1 - MissedScans/TruthScans
	Tracks            int     // distinct confirmed track IDs seen
}

// Scorer accumulates per-frame results.
type Scorer struct {
	Cutoff float64
	sum    Summary
	se     float64
	nMatch int
	last   map[int]int // track ID -> truth ID it was last matched to
	seen   map[int]bool
	OSPA   []float64 // per-frame OSPA series
}

func NewScorer(cutoff float64) *Scorer {
	return &Scorer{Cutoff: cutoff, last: map[int]int{}, seen: map[int]bool{}}
}

// Add scores one frame: truth vs confirmed-track estimates.
func (s *Scorer) Add(truth, est []Pt) error {
	tot, loc, card, err := OSPA(truth, est, s.Cutoff, 2)
	if err != nil {
		return err
	}
	s.OSPA = append(s.OSPA, tot)
	s.sum.Frames++
	s.sum.MeanOSPA += tot
	s.sum.MeanLoc += loc
	s.sum.MeanCard += card
	s.sum.TruthScans += len(truth)
	for _, e := range est {
		s.seen[e.ID] = true
	}
	matchedTruth := map[int]bool{}
	matchedEst := map[int]bool{}
	if len(truth) > 0 && len(est) > 0 {
		// Pad so rows<=cols: rows = estimates; dummy columns allow "no match".
		n, m := len(est), len(truth)
		cost := make([][]float64, n)
		for i := range est {
			cost[i] = make([]float64, m+n)
			for j := 0; j < m; j++ {
				d := dist(est[i], truth[j])
				if d <= s.Cutoff {
					cost[i][j] = d
				} else {
					cost[i][j] = math.Inf(1)
				}
			}
			for j := 0; j < n; j++ {
				cost[i][m+j] = math.Inf(1)
			}
			cost[i][m+i] = s.Cutoff
		}
		col, _, err := assoc.Hungarian(cost)
		if err != nil {
			return err
		}
		for i, j := range col {
			if j >= m {
				continue
			}
			matchedTruth[j], matchedEst[i] = true, true
			d := dist(est[i], truth[j])
			s.se += d * d
			s.nMatch++
			if prev, ok := s.last[est[i].ID]; ok && prev != truth[j].ID {
				s.sum.IDSwitches++
			}
			s.last[est[i].ID] = truth[j].ID
		}
	}
	s.sum.FalseTrackScans += len(est) - len(matchedEst)
	s.sum.MissedScans += len(truth) - len(matchedTruth)
	return nil
}

func (s *Scorer) Summary() Summary {
	r := s.sum
	if r.Frames > 0 {
		f := float64(r.Frames)
		r.MeanOSPA /= f
		r.MeanLoc /= f
		r.MeanCard /= f
	}
	if s.nMatch > 0 {
		r.PosRMSE = math.Sqrt(s.se / float64(s.nMatch))
	}
	if r.TruthScans > 0 {
		r.Coverage = 1 - float64(r.MissedScans)/float64(r.TruthScans)
	} else {
		r.Coverage = 1
	}
	r.Tracks = len(s.seen)
	return r
}

// ---------------------------------------------------------------- consistency

// Consistency is the result of a chi-square average-NEES/NIS test.
type Consistency struct {
	N          int
	DOF        int
	Mean       float64
	Lo, Hi     float64 // two-sided acceptance interval for the mean
	Consistent bool
	FracInside float64 // fraction of samples under the individual upper gate
}

// ConsistencyTest checks whether samples (each ~ χ²_dof under a correct filter) have the right mean:
// N·mean ~ χ²_{N·dof}, so the mean must fall inside the [α/2, 1-α/2] quantiles of that law / N.
func ConsistencyTest(samples []float64, dof int, alpha float64) (Consistency, error) {
	n := len(samples)
	if n == 0 {
		return Consistency{}, errors.New("metrics: no samples")
	}
	if alpha <= 0 || alpha >= 1 {
		return Consistency{}, errors.New("metrics: alpha must be in (0,1)")
	}
	sum := 0.0
	for _, v := range samples {
		if math.IsNaN(v) || v < 0 {
			return Consistency{}, errors.New("metrics: samples must be finite and non-negative")
		}
		sum += v
	}
	lo, err := stat.Chi2Quantile(alpha/2, n*dof)
	if err != nil {
		return Consistency{}, err
	}
	hi, err := stat.Chi2Quantile(1-alpha/2, n*dof)
	if err != nil {
		return Consistency{}, err
	}
	gate, _ := stat.Chi2Quantile(1-alpha/2, dof)
	in := 0
	for _, v := range samples {
		if v <= gate {
			in++
		}
	}
	c := Consistency{N: n, DOF: dof, Mean: sum / float64(n), Lo: lo / float64(n), Hi: hi / float64(n), FracInside: float64(in) / float64(n)}
	c.Consistent = c.Mean >= c.Lo && c.Mean <= c.Hi
	return c, nil
}
