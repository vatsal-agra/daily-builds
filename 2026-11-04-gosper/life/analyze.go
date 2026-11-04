package life

import (
	"fmt"
	"math"
	"sort"
	"strings"
)

// ---------------------------------------------------------------- shapes

// normalise translates cells so the bounding box starts at (0,0) and sorts them.
func normalise(pts []Point) ([]Point, int64, int64) {
	if len(pts) == 0 {
		return nil, 0, 0
	}
	x0, y0, _, _ := boundsOf(pts)
	out := make([]Point, len(pts))
	for i, p := range pts {
		out[i] = Point{p.X - x0, p.Y - y0}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Y != out[j].Y {
			return out[i].Y < out[j].Y
		}
		return out[i].X < out[j].X
	})
	return out, x0, y0
}

func samePoints(a, b []Point) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func keyOf(pts []Point) string {
	var sb strings.Builder
	for _, p := range pts {
		fmt.Fprintf(&sb, "%d,%d;", p.X, p.Y)
	}
	return sb.String()
}

// canonicalKey is invariant under translation and the 8 rotations/reflections.
func canonicalKey(pts []Point) string {
	best := ""
	for t := 0; t < 8; t++ {
		tp := make([]Point, len(pts))
		for i, p := range pts {
			x, y := p.X, p.Y
			if t&1 != 0 {
				x = -x
			}
			if t&2 != 0 {
				y = -y
			}
			if t&4 != 0 {
				x, y = y, x
			}
			tp[i] = Point{x, y}
		}
		n, _, _ := normalise(tp)
		k := keyOf(n)
		if best == "" || k < best {
			best = k
		}
	}
	return best
}

// ---------------------------------------------------------------- period analysis

// Kind classifies the long-term behaviour of an isolated pattern.
type Kind string

const (
	KindEmpty      Kind = "empty"
	KindStill      Kind = "still life"
	KindOscillator Kind = "oscillator"
	KindSpaceship  Kind = "spaceship"
	KindDies       Kind = "dies out"
	KindAperiodic  Kind = "not periodic"
)

// PeriodResult is the outcome of searching for exact translation-periodicity.
type PeriodResult struct {
	Kind       Kind
	Period     int
	Dx, Dy     int64
	DiesAt     uint64
	Population uint64
	W, H       int64
}

// Speed renders a spaceship's speed like "c/4 diagonal" or "(2,1)c/6".
func (r PeriodResult) Speed() string {
	if r.Kind != KindSpaceship {
		return ""
	}
	ax, ay := abs64(r.Dx), abs64(r.Dy)
	d := fmt.Sprintf("%dc/%d", max(ax, ay), r.Period)
	switch {
	case ax == ay:
		return d + " diagonal"
	case ax == 0 || ay == 0:
		return d + " orthogonal"
	default:
		return fmt.Sprintf("(%d,%d)c/%d oblique", ax, ay, r.Period)
	}
}

func abs64(a int64) int64 {
	if a < 0 {
		return -a
	}
	return a
}

const maxShapeCells = 400_000

// FindPeriod steps a copy of the pattern one generation at a time looking for
// the first generation whose shape equals the initial one up to translation.
func FindPeriod(rule Rule, pts []Point, maxPeriod int) (PeriodResult, error) {
	s := NewSim(rule)
	if err := s.SetCells(append([]Point(nil), pts...), true); err != nil {
		return PeriodResult{}, err
	}
	res := PeriodResult{Kind: KindAperiodic, Population: s.Population()}
	if s.Population() == 0 {
		res.Kind = KindEmpty
		return res, nil
	}
	if s.Population() > maxShapeCells {
		return res, fmt.Errorf("pattern too large for period search (%d cells)", s.Population())
	}
	c0, _ := s.Cells(0)
	base, bx, by := normalise(c0)
	_, _, w1, h1 := boundsOf(base)
	res.W, res.H = w1+1, h1+1
	for t := 1; t <= maxPeriod; t++ {
		if err := s.Step(1); err != nil {
			return res, err
		}
		if s.Population() == 0 {
			res.Kind, res.DiesAt = KindDies, uint64(t)
			return res, nil
		}
		if s.Population() != uint64(len(base)) {
			continue
		}
		cs, _ := s.Cells(0)
		n, x0, y0 := normalise(cs)
		if samePoints(n, base) {
			res.Period, res.Dx, res.Dy = t, x0-bx, y0-by
			switch {
			case res.Dx != 0 || res.Dy != 0:
				res.Kind = KindSpaceship
			case t == 1:
				res.Kind = KindStill
			default:
				res.Kind = KindOscillator
			}
			return res, nil
		}
		if s.U.Size() > 2_000_000 {
			s.U.Compact(s.Root)
		}
	}
	return res, nil
}

// ---------------------------------------------------------------- growth

// Checkpoint is the population at generation 2^J.
type Checkpoint struct {
	J   int
	Gen uint64
	Pop uint64
	// Width/Height of the bounding box (saturating).
	W, H uint64
}

// GrowthClass summarises asymptotic population growth.
type GrowthClass struct {
	Label    string
	Exponent float64 // fitted alpha in pop ~ t^alpha
}

// GrowthReport runs the pattern to generations 2^0..2^maxJ using Hashlife and
// records the population at each one.
func GrowthReport(rule Rule, pts []Point, maxJ int) ([]Checkpoint, GrowthClass, error) {
	s := NewSim(rule)
	if err := s.SetCells(append([]Point(nil), pts...), true); err != nil {
		return nil, GrowthClass{}, err
	}
	var cps []Checkpoint
	for j := 0; j <= maxJ; j++ {
		var err error
		if j == 0 {
			err = s.Step(1)
		} else {
			err = s.StepPow(j - 1)
		}
		if err != nil {
			return cps, ClassifyGrowth(cps), fmt.Errorf("stopped at generation 2^%d: %w", j, err)
		}
		cp := Checkpoint{J: j, Gen: s.Gen, Pop: s.Population()}
		if x0, y0, x1, y1, ok := s.BBox(); ok {
			cp.W, cp.H = uint64(x1-x0+1), uint64(y1-y0+1)
		}
		cps = append(cps, cp)
	}
	return cps, ClassifyGrowth(cps), nil
}

// ClassifyGrowth fits log2(pop) against log2(t) over the tail of the checkpoints.
func ClassifyGrowth(cps []Checkpoint) GrowthClass {
	if len(cps) == 0 {
		return GrowthClass{"unknown", 0}
	}
	last := cps[len(cps)-1]
	if last.Pop == 0 {
		return GrowthClass{"extinct", 0}
	}
	tail := cps
	if len(tail) > 8 {
		tail = tail[len(tail)-8:]
	}
	if len(tail) < 4 {
		return GrowthClass{"too short to classify", 0}
	}
	var sx, sy, sxx, sxy float64
	n := float64(len(tail))
	for _, c := range tail {
		if c.Pop == 0 {
			continue
		}
		x, y := float64(c.J), math.Log2(float64(c.Pop))
		sx, sy, sxx, sxy = sx+x, sy+y, sxx+x*x, sxy+x*y
	}
	den := n*sxx - sx*sx
	alpha := 0.0
	if den != 0 {
		alpha = (n*sxy - sx*sy) / den
	}
	label := ""
	switch {
	case alpha < 0.12:
		label = "bounded (settles)"
	case alpha < 0.85:
		label = "sub-linear growth"
	case alpha <= 1.15:
		label = "linear growth"
	case alpha < 1.85:
		label = "super-linear growth"
	default:
		label = "quadratic growth"
	}
	if math.Abs(alpha) < 0.005 {
		alpha = 0 // avoid printing "-0.00"
	}
	return GrowthClass{label, alpha}
}

// ---------------------------------------------------------------- settling

// Settle is the result of running a pattern until its population becomes periodic.
type Settle struct {
	Settled     bool
	AtGen       uint64
	PopPeriod   int
	FinalPop    uint64
	PeakPop     uint64
	PeakGen     uint64
	Generations uint64 // generations simulated
	HorizonGen  uint64 // generation of the Hashlife look-ahead check (0 = not run)
	HorizonOK   bool
	HorizonPop  uint64
	HorizonWant uint64
	DiedAt      uint64
	Died        bool
	PopSeries   []uint64
}

// FindSettle single-steps up to maxGens, then looks for a population-periodic
// tail. If horizonJ>0 it additionally jumps 2^horizonJ generations ahead with
// Hashlife and checks that the population matches the periodic prediction.
func FindSettle(rule Rule, pts []Point, maxGens int, horizonJ int) (*Settle, error) {
	s := NewSim(rule)
	st := &Settle{}
	if err := s.SetCells(append([]Point(nil), pts...), true); err != nil {
		return st, err
	}
	series := []uint64{s.Population()}
	st.PeakPop = s.Population()
	for g := 1; g <= maxGens; g++ {
		if err := s.Step(1); err != nil {
			return st, err
		}
		p := s.Population()
		series = append(series, p)
		if p > st.PeakPop {
			st.PeakPop, st.PeakGen = p, uint64(g)
		}
		if p == 0 {
			st.Died, st.DiedAt, st.Settled, st.AtGen = true, uint64(g), true, uint64(g)
			st.Generations, st.PopSeries = uint64(g), series
			return st, nil
		}
		if s.U.Size() > 2_000_000 {
			s.U.Compact(s.Root)
		}
		// Early exit once a long tail is clearly periodic.
		if g%250 == 0 {
			if at, _, ok := periodicTail(series); ok && len(series)-at >= 500 {
				break
			}
		}
	}
	st.PopSeries = series
	st.Generations = uint64(len(series) - 1)
	st.FinalPop = series[len(series)-1]
	if at, per, ok := periodicTail(series); ok {
		st.Settled, st.AtGen, st.PopPeriod = true, uint64(at), per
	}
	if st.Settled && horizonJ > 0 && st.PopPeriod > 0 {
		// Predict the population at generation H from the periodic tail, then
		// verify the prediction by actually jumping there with Hashlife.
		H := uint64(1) << uint(horizonJ)
		cur := s.Gen
		if H > cur {
			per := uint64(st.PopPeriod)
			d := (H - cur) % per
			back := (per - d) % per
			want := series[cur-back]
			if err := s.Step(H - cur); err != nil {
				return st, err
			}
			st.HorizonGen, st.HorizonPop, st.HorizonWant = H, s.Population(), want
			st.HorizonOK = st.HorizonPop == want
		}
	}
	return st, nil
}

// periodicTail finds the smallest period p (<= 120) for which the series is
// p-periodic over a tail of at least max(3p, 60) samples, and returns the
// earliest index from which that periodicity holds.
func periodicTail(series []uint64) (at int, period int, ok bool) {
	n := len(series)
	for p := 1; p <= 120; p++ {
		need := max(3*p, 60)
		if n < need {
			break
		}
		start := n - p
		for start > 0 && series[start-1] == series[start-1+p] {
			start--
		}
		if n-start >= need {
			return start, p, true
		}
	}
	return 0, 0, false
}
