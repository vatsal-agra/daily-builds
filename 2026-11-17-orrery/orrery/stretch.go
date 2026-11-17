package orrery

import (
	"errors"
	"fmt"
	"math"
	"math/rand"
)

// OrderPoint is one (dt, error) sample of a convergence study.
type OrderPoint struct {
	Dt  float64
	Err float64
}

// OrderStudy is the outcome of MeasureOrder.
type OrderStudy struct {
	Method   Method
	Points   []OrderPoint
	Observed float64   // least-squares slope of log(err) vs log(dt)
	Slopes   []float64 // local slopes between successive points
}

// MeasureOrder integrates a bound two-body system for 1.37 orbital periods with
// a halving sequence of step sizes and compares the final relative state
// (position and velocity) with the analytic Kepler oracle. The observed order is the slope of
// log(error) against log(dt), computed only over points above the round-off
// floor. Adaptive methods are rejected: their order is in the tolerance.
func MeasureOrder(sys *System, m Method, stepsPerPeriod []int) (*OrderStudy, error) {
	if m == DOPRI5 {
		return nil, errors.New("dopri5 is adaptive: its step size is set by -tol, so a dt convergence study does not apply")
	}
	if len(sys.Bodies) != 2 {
		return nil, fmt.Errorf("order study needs a two-body system (analytic oracle), got %d bodies", len(sys.Bodies))
	}
	if len(stepsPerPeriod) < 3 {
		return nil, errors.New("need at least 3 step sizes")
	}
	rel := sys.Bodies[1].Pos.Sub(sys.Bodies[0].Pos)
	vel := sys.Bodies[1].Vel.Sub(sys.Bodies[0].Vel)
	mu := sys.G * sys.TotalMass()
	el, err := ElementsFromState(rel, vel, mu)
	if err != nil {
		return nil, err
	}
	if !(el.E < 1) || !(el.A > 0) {
		return nil, errors.New("order study needs a bound orbit")
	}
	if sys.Eps != 0 {
		return nil, errors.New("order study needs zero softening (the oracle is the pure Kepler problem)")
	}
	// 1.37 periods, not 1: at an exact period the O(h) phase error of first-order
	// schemes can cancel (a time-shifted orbit closes on itself), which
	// understates their order.
	end := 1.37 * el.Period
	want, wantV, err := KeplerOracle(rel, vel, mu, end)
	if err != nil {
		return nil, err
	}
	st := &OrderStudy{Method: m}
	for _, n := range stepsPerPeriod {
		if n < 2 {
			return nil, fmt.Errorf("steps per period must be >= 2, got %d", n)
		}
		h := el.Period / float64(n)
		res, err := Run(sys, m, h, end, 2, 0)
		if err != nil {
			return nil, err
		}
		if res.Err != nil {
			return nil, res.Err
		}
		f := res.Final
		dr := f.Bodies[1].Pos.Sub(f.Bodies[0].Pos).Sub(want)
		dv := f.Bodies[1].Vel.Sub(f.Bodies[0].Vel).Sub(wantV)
		e := math.Sqrt(dr.Norm2() + dv.Norm2()) // full phase-space error
		st.Points = append(st.Points, OrderPoint{Dt: res.Dt, Err: e})
	}
	// fit on points above the round-off floor
	var xs, ys []float64
	for i, p := range st.Points {
		if p.Err > 1e-11 && !math.IsNaN(p.Err) {
			xs = append(xs, math.Log(p.Dt))
			ys = append(ys, math.Log(p.Err))
		}
		if i > 0 && p.Err > 0 && st.Points[i-1].Err > 0 {
			st.Slopes = append(st.Slopes, math.Log(st.Points[i-1].Err/p.Err)/math.Log(st.Points[i-1].Dt/p.Dt))
		} else if i > 0 {
			st.Slopes = append(st.Slopes, math.NaN())
		}
	}
	if len(xs) < 3 {
		return nil, errors.New("too few points above the round-off floor; use coarser steps")
	}
	st.Observed = slope(xs, ys)
	return st, nil
}

func slope(x, y []float64) float64 {
	n := float64(len(x))
	var sx, sy, sxx, sxy float64
	for i := range x {
		sx += x[i]
		sy += y[i]
		sxx += x[i] * x[i]
		sxy += x[i] * y[i]
	}
	return (n*sxy - sx*sy) / (n*sxx - sx*sx)
}

// ReverseResult is the outcome of a time-reversal test.
type ReverseResult struct {
	Method    Method
	PosErr    float64 // max body displacement after forward T then backward T
	VelErr    float64
	RelPosErr float64 // PosErr / system size
}

// ReverseTest integrates forward for T, then backward for T with the same
// steps, and measures how far the system is from where it started. A
// time-reversible scheme (leapfrog, Yoshida, Wisdom–Holman) returns to within
// round-off amplified by the dynamics; others do not.
func ReverseTest(sys *System, m Method, dt, T float64) (*ReverseResult, error) {
	if !(dt > 0) || !(T > 0) || math.IsInf(T, 0) || math.IsInf(dt, 0) {
		return nil, errors.New("dt and T must be positive and finite")
	}
	n := int(math.Round(T / dt))
	if n < 1 {
		n = 1
	}
	if n > 100_000_000 {
		return nil, errors.New("too many steps")
	}
	h := T / float64(n)
	work := sys.Clone()
	it, err := NewIntegrator(work, m)
	if err != nil {
		return nil, err
	}
	for k := 0; k < n; k++ {
		if err := it.Advance(h); err != nil {
			return nil, err
		}
	}
	for k := 0; k < n; k++ {
		if err := it.Advance(-h); err != nil {
			return nil, err
		}
	}
	r := &ReverseResult{Method: m}
	size := 0.0
	for i, b := range sys.Bodies {
		r.PosErr = math.Max(r.PosErr, work.Bodies[i].Pos.Sub(b.Pos).Norm())
		r.VelErr = math.Max(r.VelErr, work.Bodies[i].Vel.Sub(b.Vel).Norm())
		size = math.Max(size, b.Pos.Norm())
	}
	if size == 0 {
		size = 1
	}
	r.RelPosErr = r.PosErr / size
	return r, nil
}

// LyapunovPoint is a running estimate.
type LyapunovPoint struct{ T, Lambda float64 }

// LyapunovResult holds the largest-Lyapunov-exponent estimate.
type LyapunovResult struct {
	Lambda float64 // final estimate (per unit time) over the whole run
	// LambdaLate is the growth rate over the second half of the run, free of
	// the initial transient; Trend is LambdaLate divided by the rate over the
	// third quarter. Trend ≈ 1 means the log-separation grows linearly
	// (exponential divergence: chaos); Trend ≈ 0.5 or lower means growth
	// is slowing like ln t (regular motion).
	LambdaLate float64
	Trend      float64
	// EFolds is how many e-foldings of separation growth the second half of
	// the run produced. Shear in regular orbits yields only a few (growth ~
	// ln t); exponential divergence yields many, so this is what the verdict
	// rests on.
	EFolds  float64
	Verdict string // "chaotic", "transient", "regular" or "inconclusive"
	Series  []LyapunovPoint
	Renorms int
}

// Lyapunov estimates the largest Lyapunov exponent with the Benettin
// shadow-orbit method: a perturbed copy of the system is evolved alongside the
// reference, its separation (Euclidean over all positions and velocities) is
// measured every `renorm` steps and rescaled back to d0, and the exponent is
// the mean log growth rate. Regular orbits give λ→0 (like ln t / t); chaotic
// ones converge to a positive value.
func Lyapunov(sys *System, m Method, dt, T float64, seed int64) (*LyapunovResult, error) {
	if !(dt > 0) || !(T > 0) || math.IsInf(T, 0) {
		return nil, errors.New("dt and T must be positive and finite")
	}
	n := int(math.Round(T / dt))
	if n < 20 {
		return nil, errors.New("need at least 20 steps; reduce dt")
	}
	if n > 200_000_000 {
		return nil, errors.New("too many steps")
	}
	h := T / float64(n)
	renorm := n / 400
	if renorm < 1 {
		renorm = 1
	}
	ref := sys.Clone()
	sh := sys.Clone()
	const d0 = 1e-8
	rng := rand.New(rand.NewSource(seed))
	// random unit direction in the 6N-dimensional phase space
	dir := make([]float64, 6*len(sh.Bodies))
	var nn float64
	for i := range dir {
		dir[i] = rng.NormFloat64()
		nn += dir[i] * dir[i]
	}
	nn = math.Sqrt(nn)
	apply := func(base *System, vec []float64, scale float64) {
		for i := range base.Bodies {
			base.Bodies[i].Pos = base.Bodies[i].Pos.Add(Vec3{vec[6*i], vec[6*i+1], vec[6*i+2]}.Scale(scale))
			base.Bodies[i].Vel = base.Bodies[i].Vel.Add(Vec3{vec[6*i+3], vec[6*i+4], vec[6*i+5]}.Scale(scale))
		}
	}
	apply(sh, dir, d0/nn)
	iR, err := NewIntegrator(ref, m)
	if err != nil {
		return nil, err
	}
	iS, err := NewIntegrator(sh, m)
	if err != nil {
		return nil, err
	}
	res := &LyapunovResult{}
	sum := 0.0
	done := 0
	for done < n {
		k := renorm
		if done+k > n {
			k = n - done
		}
		for j := 0; j < k; j++ {
			if err := iR.Advance(h); err != nil {
				return nil, fmt.Errorf("reference orbit: %w", err)
			}
			if err := iS.Advance(h); err != nil {
				return nil, fmt.Errorf("shadow orbit: %w", err)
			}
		}
		done += k
		// separation vector
		diff := make([]float64, 6*len(ref.Bodies))
		var d2 float64
		for i := range ref.Bodies {
			dp := sh.Bodies[i].Pos.Sub(ref.Bodies[i].Pos)
			dv := sh.Bodies[i].Vel.Sub(ref.Bodies[i].Vel)
			diff[6*i], diff[6*i+1], diff[6*i+2] = dp.X, dp.Y, dp.Z
			diff[6*i+3], diff[6*i+4], diff[6*i+5] = dv.X, dv.Y, dv.Z
			d2 += dp.Norm2() + dv.Norm2()
		}
		d := math.Sqrt(d2)
		if !(d > 0) || math.IsInf(d, 0) {
			return nil, errors.New("shadow orbit separation became degenerate")
		}
		sum += math.Log(d / d0)
		res.Renorms++
		// rescale shadow back to distance d0 from the reference
		for i := range sh.Bodies {
			sh.Bodies[i].Pos = ref.Bodies[i].Pos.Add(Vec3{diff[6*i], diff[6*i+1], diff[6*i+2]}.Scale(d0 / d))
			sh.Bodies[i].Vel = ref.Bodies[i].Vel.Add(Vec3{diff[6*i+3], diff[6*i+4], diff[6*i+5]}.Scale(d0 / d))
		}
		iS.Invalidate()
		t := float64(done) * h
		res.Series = append(res.Series, LyapunovPoint{T: t, Lambda: sum / t})
	}
	res.Lambda = res.Series[len(res.Series)-1].Lambda
	S := func(frac float64) float64 { // cumulative log growth at time frac*T
		best := res.Series[0]
		for _, p := range res.Series {
			if math.Abs(p.T-frac*T) < math.Abs(best.T-frac*T) {
				best = p
			}
		}
		return best.Lambda * best.T
	}
	s4, s2, s1 := S(0.25), S(0.5), S(1)
	res.LambdaLate = (s1 - s2) / (0.5 * T)
	if early := (s2 - s4) / (0.25 * T); early > 0 {
		res.Trend = res.LambdaLate / early
	} else {
		res.Trend = math.NaN()
	}
	res.EFolds = res.LambdaLate * T / 2
	switch {
	case res.EFolds >= 8 && res.Trend >= 0.5 && res.Trend <= 2:
		res.Verdict = "chaotic"
	case res.EFolds < 3 && s2 >= 15: // shear alone gives ~ln(ωT) ≈ 6–9 e-folds, so demand clearly more
		res.Verdict = "transient" // strong early divergence, then settled (e.g. scattering ends in a binary + escaper)
	case res.EFolds < 3:
		res.Verdict = "regular"
	default:
		res.Verdict = "inconclusive"
	}
	return res, nil
}
