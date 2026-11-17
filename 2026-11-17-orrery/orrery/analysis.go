package orrery

import (
	"errors"
	"fmt"
	"math"
	"time"
)

// Result is the outcome of Run.
type Result struct {
	Method  Method
	Dt      float64
	T       float64
	Steps   int64
	Evals   int64
	Elapsed time.Duration
	Err     error // non-nil if the run blew up; series up to that point are kept

	Times     []float64
	EnergyErr []float64 // relative energy error (E-E0)/|E0| (absolute if E0 == 0)
	LErr      []float64 // |L-L0|/|L0|
	PDrift    []float64 // |P-P0|
	Virial    []float64
	Traj      [][]Vec3 // Traj[sample][body]

	E0    float64
	Final *System
}

// MaxAbsEnergyErr is max |relative energy error| over samples.
func (r *Result) MaxAbsEnergyErr() float64 { return maxAbs(r.EnergyErr) }

// MaxLErr is the largest relative angular-momentum error.
func (r *Result) MaxLErr() float64 { return maxAbs(r.LErr) }

func maxAbs(x []float64) float64 {
	m := 0.0
	for _, v := range x {
		if math.Abs(v) > m || math.IsNaN(v) {
			m = math.Abs(v)
		}
	}
	return m
}

// Run integrates a clone of sys for time T with step dt (a sampling interval
// for adaptive methods), recording `samples` diagnostic snapshots.
func Run(sys *System, m Method, dt, T float64, samples int, tol float64) (*Result, error) {
	if !(T > 0) || math.IsInf(T, 0) {
		return nil, fmt.Errorf("T must be positive and finite, got %v", T)
	}
	if !(dt > 0) || math.IsInf(dt, 0) {
		return nil, fmt.Errorf("dt must be positive and finite, got %v", dt)
	}
	if dt > T {
		dt = T
	}
	nf := math.Round(T / dt)
	if nf > 2e9 {
		return nil, fmt.Errorf("T/dt = %.3g steps is too many", nf)
	}
	n := int(nf)
	if n < 1 {
		n = 1
	}
	if samples < 2 {
		samples = 2
	}
	work := sys.Clone()
	it, err := NewIntegrator(work, m)
	if err != nil {
		return nil, err
	}
	if tol > 0 {
		it.Tol = tol
	}
	h := T / float64(n)
	every := n / samples
	if every < 1 {
		every = 1
	}
	res := &Result{Method: m, Dt: h, T: T}
	d0 := work.Diagnose()
	res.E0 = d0.E
	L0 := d0.L.Norm()
	p0 := work.Momentum()
	record := func() {
		d := work.Diagnose()
		res.Times = append(res.Times, work.T)
		if d0.E != 0 {
			res.EnergyErr = append(res.EnergyErr, (d.E-d0.E)/math.Abs(d0.E))
		} else {
			res.EnergyErr = append(res.EnergyErr, d.E-d0.E)
		}
		if L0 != 0 {
			res.LErr = append(res.LErr, d.L.Sub(d0.L).Norm()/L0)
		} else {
			res.LErr = append(res.LErr, d.L.Sub(d0.L).Norm())
		}
		res.PDrift = append(res.PDrift, work.Momentum().Sub(p0).Norm())
		res.Virial = append(res.Virial, d.Virial)
		pos := make([]Vec3, len(work.Bodies))
		for i, b := range work.Bodies {
			pos[i] = b.Pos
		}
		res.Traj = append(res.Traj, pos)
	}
	record()
	start := time.Now()
	for k := 1; k <= n; k++ {
		if err := it.Advance(h); err != nil {
			res.Err = err
			break
		}
		if k%every == 0 || k == n {
			record()
		}
	}
	res.Elapsed = time.Since(start)
	res.Steps = it.Steps
	res.Evals = work.Evals
	res.Final = work
	return res, nil
}

// BHReport compares Barnes–Hut accelerations at a given θ with exact ones.
type BHReport struct {
	Theta  float64
	RMSRel float64 // rms of |a_bh - a_exact| / |a_exact|
	MaxRel float64
	Direct time.Duration
	Tree   time.Duration
}

// BHError measures the Barnes–Hut force error for sys at opening angle theta.
func BHError(sys *System, theta float64) (BHReport, error) {
	if !(theta > 0) {
		return BHReport{}, errors.New("theta must be > 0")
	}
	n := len(sys.Bodies)
	if n < 2 {
		return BHReport{}, errors.New("need at least 2 bodies")
	}
	pos := make([]Vec3, n)
	for i, b := range sys.Bodies {
		pos[i] = b.Pos
	}
	ex, ap := make([]Vec3, n), make([]Vec3, n)
	c := sys.Clone()
	c.Theta = theta
	timeIt := func(f func()) time.Duration {
		reps := 0
		t0 := time.Now()
		for time.Since(t0) < 20*time.Millisecond || reps == 0 {
			f()
			reps++
		}
		return time.Since(t0) / time.Duration(reps)
	}
	td := timeIt(func() { c.accelDirect(pos, ex) })
	tt := timeIt(func() { c.accelTree(pos, ap) })
	var sum, mx float64
	for i := range ex {
		en := ex[i].Norm()
		if en == 0 {
			continue
		}
		e := ap[i].Sub(ex[i]).Norm() / en
		sum += e * e
		mx = math.Max(mx, e)
	}
	return BHReport{Theta: theta, RMSRel: math.Sqrt(sum / float64(n)), MaxRel: mx, Direct: td, Tree: tt}, nil
}

// ForceBH exposes tree accelerations for tests regardless of body count.
func (s *System) ForceBH(theta float64) []Vec3 {
	pos := make([]Vec3, len(s.Bodies))
	for i, b := range s.Bodies {
		pos[i] = b.Pos
	}
	out := make([]Vec3, len(pos))
	c := s.Clone()
	c.Theta = theta
	c.accelTree(pos, out)
	return out
}

// ForceDirect exposes exact accelerations.
func (s *System) ForceDirect() []Vec3 {
	pos := make([]Vec3, len(s.Bodies))
	for i, b := range s.Bodies {
		pos[i] = b.Pos
	}
	out := make([]Vec3, len(pos))
	s.accelDirect(pos, out)
	return out
}
