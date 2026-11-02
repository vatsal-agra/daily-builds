// Package tracker is the multi-target tracker: predict, gate, assign, update, manage track lifecycle.
package tracker

import (
	"fmt"
	"math"

	"kestrel/assoc"
	"kestrel/filter"
	"kestrel/mat"
	"kestrel/model"
	"kestrel/smooth"
	"kestrel/stat"
)

// Status is a track's lifecycle stage.
type Status int

const (
	Tentative Status = iota
	Confirmed
	Deleted
)

func (s Status) String() string { return [...]string{"tentative", "confirmed", "deleted"}[s] }

// Factory builds a new filter around an initial state.
type Factory func(x0, p0 *mat.M) (filter.Filter, error)

// Config gathers every tuning knob.
type Config struct {
	Name           string
	Make           Factory
	Dim            int          // state dimension produced by Make
	Radar          *model.Radar // measurement model
	Pd             float64
	ClutterDensity float64
	GateProb       float64 // gate = chi²₂ quantile at this probability
	ConfirmM       int     // confirm after M hits ...
	ConfirmN       int     // ... within the first N scans
	MaxMiss        int     // delete a confirmed track after this many consecutive misses
	VMax           float64 // used to size the initial velocity uncertainty (σv = VMax/3)
	MergeGate      float64 // Mahalanobis² below which two confirmed tracks are duplicates (0 = off)
	Assoc          string  // "gnn" (default) or "jpda"
	ScoreConfirm   float64 // confirm only when the track score also exceeds this
	Trace          bool    // record per-scan filter internals so tracks can be RTS-smoothed
	DeleteDrop     float64 // delete a confirmed track once its score falls this far below its peak (0 = off)
}

func (c *Config) validate() error {
	switch {
	case c.Make == nil || c.Radar == nil:
		return fmt.Errorf("tracker: Make and Radar are required")
	case c.Pd <= 0 || c.Pd >= 1:
		return fmt.Errorf("tracker: Pd must be in (0,1), got %v", c.Pd)
	case c.ClutterDensity <= 0:
		return fmt.Errorf("tracker: ClutterDensity must be positive")
	case c.GateProb <= 0 || c.GateProb >= 1:
		return fmt.Errorf("tracker: GateProb must be in (0,1)")
	case c.ConfirmM < 1 || c.ConfirmN < c.ConfirmM:
		return fmt.Errorf("tracker: need 1 <= ConfirmM <= ConfirmN")
	case c.MaxMiss < 1:
		return fmt.Errorf("tracker: MaxMiss must be >= 1")
	case c.Assoc != "" && c.Assoc != "gnn" && c.Assoc != "jpda":
		return fmt.Errorf("tracker: unknown association %q (gnn|jpda)", c.Assoc)
	}
	return nil
}

// Point is one historical estimate of a track.
type Point struct {
	T             float64
	X, Y          float64
	VX, VY        float64
	PosVar        float64 // trace of the position covariance block
	PXX, PXY, PYY float64 // position covariance block, for uncertainty ellipses
	Updated       bool    // false = coasted (no detection)
	ModeProbs     []float64
}

// Track is one hypothesised target.
type Track struct {
	ID           int
	Status       Status
	F            filter.Filter
	Born         float64
	Hits         int
	Age          int     // scans since birth
	Misses       int     // consecutive misses
	Score        float64 // cumulative log-likelihood ratio: real target vs clutter
	ConfirmScore float64 // score at the moment of confirmation
	MaxScore     float64 // peak score since confirmation
	trace        []smooth.Step
	pend         smooth.Step // step being assembled during the current scan
	hist         []bool      // hit/miss history for M-of-N
	History      []Point
	Died         float64
	DeathReason  string
}

// Tracker holds all live and finished tracks.
type Tracker struct {
	cfg    Config
	gate   float64
	nextID int
	lastT  float64
	begun  bool
	Tracks []*Track // live tracks (tentative + confirmed)
	Dead   []*Track
	// NISLog collects the innovation NIS of every confirmed-track update (consistency checking).
	NISLog     []float64
	pendingErr error
}

func New(cfg Config) (*Tracker, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	g, err := stat.Chi2Quantile(cfg.GateProb, 2)
	if err != nil {
		return nil, err
	}
	return &Tracker{cfg: cfg, gate: g, nextID: 1}, nil
}

// Gate returns the Mahalanobis² gate in use.
func (t *Tracker) Gate() float64 { return t.gate }

// Confirmed returns the live confirmed tracks.
func (t *Tracker) Confirmed() []*Track {
	var out []*Track
	for _, tr := range t.Tracks {
		if tr.Status == Confirmed {
			out = append(out, tr)
		}
	}
	return out
}

// AllTracks returns every track ever created (live then dead).
func (t *Tracker) AllTracks() []*Track {
	return append(append([]*Track{}, t.Dead...), t.Tracks...)
}

// Step processes one scan of detections [range, bearing] at time tm.
func (t *Tracker) Step(tm float64, dets []*mat.M) error {
	dt := 0.0
	if t.begun {
		dt = tm - t.lastT
		if dt <= 0 {
			return fmt.Errorf("tracker: scan times must increase (got %v after %v)", tm, t.lastT)
		}
	}
	for i, z := range dets {
		if z == nil || z.R != 2 || z.C != 1 || z.HasNaN() {
			return fmt.Errorf("tracker: detection %d is malformed (want finite [range, bearing])", i)
		}
	}
	t.begun, t.lastT = true, tm
	rad := t.cfg.Radar

	// 1. predict
	if dt > 0 {
		for _, tr := range t.Tracks {
			var prevX *mat.M
			if t.cfg.Trace {
				prevX = tr.F.X().Clone()
			}
			if err := tr.F.Predict(dt); err != nil {
				t.kill(tr, tm, "predict failed: "+err.Error())
				continue
			}
			if t.cfg.Trace {
				tr.pend = smooth.Step{XP: tr.F.X().Clone(), PP: tr.F.P().Clone()}
				if mf, ok := tr.F.(interface{ Motion() model.Motion }); ok {
					tr.pend.F = mf.Motion().Jac(prevX, dt)
				}
			}
		}
		t.sweep()
	}

	// 2. associate
	fs := make([]filter.Filter, len(t.Tracks))
	for i, tr := range t.Tracks {
		fs[i] = tr.F
	}
	cand, preds, err := assoc.Matrix(fs, rad, dets, t.gate)
	if err != nil {
		return err
	}
	par := assoc.Params{Gate: t.gate, Pd: t.cfg.Pd, ClutterDensity: t.cfg.ClutterDensity}
	used := make([]bool, len(dets))
	if t.cfg.Assoc == "jpda" {
		if err := t.updateJPDA(tm, dets, cand, preds, par, used); err != nil {
			return err
		}
		if t.pendingErr != nil {
			err := t.pendingErr
			t.pendingErr = nil
			return err
		}
	} else {
		pick, err := assoc.GNN(cand, par)
		if err != nil {
			return err
		}
		for i, tr := range t.Tracks {
			if pick[i] < 0 {
				tr.Score += math.Log(1 - t.cfg.Pd)
				t.miss(tr)
				continue
			}
			res, err := tr.F.Correct(rad, preds[i], dets[pick[i]])
			if err != nil {
				t.kill(tr, tm, "update failed: "+err.Error())
				continue
			}
			tr.Score += math.Log(t.cfg.Pd) + res.LogLik - math.Log(t.cfg.ClutterDensity)
			used[pick[i]] = true
			t.hit(tr, res)
		}
	}
	t.sweep()

	// 3. lifecycle: confirm / delete
	for _, tr := range t.Tracks {
		tr.Age++
		switch tr.Status {
		case Tentative:
			if tr.Hits >= t.cfg.ConfirmM && tr.Score >= t.cfg.ScoreConfirm {
				tr.Status = Confirmed
				tr.ConfirmScore, tr.MaxScore = tr.Score, tr.Score
			} else if tr.Age >= t.cfg.ConfirmN || t.cfg.ConfirmN-tr.Age < t.cfg.ConfirmM-tr.Hits {
				t.kill(tr, tm, "never confirmed")
			}
		case Confirmed:
			tr.MaxScore = math.Max(tr.MaxScore, tr.Score)
			if t.cfg.DeleteDrop > 0 && tr.MaxScore-tr.Score > t.cfg.DeleteDrop {
				t.kill(tr, tm, fmt.Sprintf("score fell %.1f below peak", tr.MaxScore-tr.Score))
			} else if tr.Misses > t.cfg.MaxMiss {
				t.kill(tr, tm, fmt.Sprintf("%d consecutive misses", tr.Misses))
			}
		}
		if tr.Status != Deleted {
			tr.History = append(tr.History, snapshot(tr, tm, tr.Misses == 0))
			if t.cfg.Trace {
				tr.pend.XF, tr.pend.PF = tr.F.X().Clone(), tr.F.P().Clone()
				tr.trace = append(tr.trace, tr.pend)
				tr.pend = smooth.Step{}
			}
		}
	}
	t.sweep()
	t.mergeDuplicates(tm)

	// 4. birth: every detection no track claimed seeds a tentative track
	for j, z := range dets {
		if used[j] {
			continue
		}
		if err := t.birth(tm, z); err != nil {
			return err
		}
	}
	return nil
}

func snapshot(tr *Track, tm float64, upd bool) Point {
	x, p := tr.F.X(), tr.F.P()
	pt := Point{T: tm, X: x.D[0], VX: x.D[1], Y: x.D[2], VY: x.D[3], Updated: upd}
	pt.PosVar = p.At(0, 0) + p.At(2, 2)
	pt.PXX, pt.PXY, pt.PYY = p.At(0, 0), p.At(0, 2), p.At(2, 2)
	if im, ok := tr.F.(*filter.IMM); ok {
		pt.ModeProbs = im.Probs()
	}
	return pt
}

func (t *Tracker) hit(tr *Track, res filter.Result) {
	tr.Hits++
	tr.Misses = 0
	tr.hist = append(tr.hist, true)
	if tr.Status == Confirmed && res.S != nil {
		t.NISLog = append(t.NISLog, res.NIS)
	}
}

func (t *Tracker) miss(tr *Track) {
	tr.Misses++
	tr.hist = append(tr.hist, false)
}

func (t *Tracker) kill(tr *Track, tm float64, why string) {
	if tr.Status == Deleted {
		return
	}
	tr.Status, tr.Died, tr.DeathReason = Deleted, tm, why
}

// sweep moves deleted tracks out of the live list. Only confirmed tracks are kept as "dead" records;
// never-confirmed clutter tracks are discarded.
func (t *Tracker) sweep() {
	live := t.Tracks[:0]
	for _, tr := range t.Tracks {
		if tr.Status == Deleted {
			if tr.Hits >= t.cfg.ConfirmM {
				t.Dead = append(t.Dead, tr)
			}
			continue
		}
		live = append(live, tr)
	}
	t.Tracks = live
}

// birth seeds a tentative track from one detection: position from the detection (with its
// first-order Cartesian covariance), velocity unknown with σv = VMax/3.
func (t *Tracker) birth(tm float64, z *mat.M) error {
	rad := t.cfg.Radar
	x, y := rad.ToCartesian(z)
	pc := rad.CartCov(z)
	sv := t.cfg.VMax / 3
	n := t.cfg.Dim
	x0 := mat.New(n, 1)
	p0 := mat.New(n, n)
	x0.D[0], x0.D[2] = x, y
	p0.Set(0, 0, pc.At(0, 0))
	p0.Set(0, 2, pc.At(0, 1))
	p0.Set(2, 0, pc.At(1, 0))
	p0.Set(2, 2, pc.At(1, 1))
	p0.Set(1, 1, sv*sv)
	p0.Set(3, 3, sv*sv)
	if n >= 5 {
		p0.Set(4, 4, 0.05*0.05)
	}
	f, err := t.cfg.Make(x0, p0)
	if err != nil {
		return err
	}
	tr := &Track{ID: t.nextID, Status: Tentative, F: f, Born: tm, Hits: 1, Age: 1, hist: []bool{true}}
	t.nextID++
	tr.History = append(tr.History, snapshot(tr, tm, true))
	if t.cfg.Trace {
		tr.trace = append(tr.trace, smooth.Step{XF: f.X().Clone(), PF: f.P().Clone()})
	}
	t.Tracks = append(t.Tracks, tr)
	return nil
}

// mergeDuplicates removes the weaker of any two confirmed tracks that estimate the same target
// (their state difference is statistically indistinguishable from zero).
func (t *Tracker) mergeDuplicates(tm float64) {
	if t.cfg.MergeGate <= 0 {
		return
	}
	for i := 0; i < len(t.Tracks); i++ {
		for j := i + 1; j < len(t.Tracks); j++ {
			a, b := t.Tracks[i], t.Tracks[j]
			if a.Status == Deleted || b.Status == Deleted {
				continue
			}
			xa, xb := a.F.X(), b.F.X()
			d := mat.Vec(xa.D[0]-xb.D[0], xa.D[1]-xb.D[1], xa.D[2]-xb.D[2], xa.D[3]-xb.D[3])
			pa, pb := a.F.P(), b.F.P()
			idx := []int{0, 1, 2, 3}
			s := mat.New(4, 4)
			for r, ri := range idx {
				for c, ci := range idx {
					s.Set(r, c, pa.At(ri, ci)+pb.At(ri, ci))
				}
			}
			d2, _, err := filter.Mahalanobis(d, s)
			if err != nil || d2 > t.cfg.MergeGate {
				continue
			}
			loser := b
			if b.Hits > a.Hits || (b.Hits == a.Hits && b.Born < a.Born) {
				loser = a
			}
			t.kill(loser, tm, fmt.Sprintf("duplicate of track %d", map[bool]int{true: a.ID, false: b.ID}[loser == b]))
		}
	}
	t.sweep()
}

// Smoothed returns the track's history re-estimated with the RTS smoother using every scan
// (past AND future). It needs Config.Trace and a non-IMM filter.
func (tr *Track) Smoothed() ([]Point, error) {
	if len(tr.trace) == 0 {
		return nil, fmt.Errorf("track %d has no trace (enable Config.Trace; IMM tracks are not smoothable)", tr.ID)
	}
	if len(tr.trace) != len(tr.History) {
		return nil, fmt.Errorf("track %d trace/history length mismatch (%d vs %d)", tr.ID, len(tr.trace), len(tr.History))
	}
	for i := 1; i < len(tr.trace); i++ {
		if tr.trace[i].F == nil {
			return nil, fmt.Errorf("track %d filter does not expose its motion model", tr.ID)
		}
	}
	r, err := smooth.RTS(tr.trace)
	if err != nil {
		return nil, err
	}
	out := make([]Point, len(r.X))
	for i, x := range r.X {
		h := tr.History[i]
		out[i] = Point{T: h.T, X: x.D[0], VX: x.D[1], Y: x.D[2], VY: x.D[3], PosVar: r.P[i].At(0, 0) + r.P[i].At(2, 2), Updated: h.Updated}
	}
	return out, nil
}
