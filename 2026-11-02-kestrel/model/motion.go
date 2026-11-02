// Package model defines motion (process) models and measurement models.
package model

import (
	"math"

	"kestrel/mat"
)

// Motion is a discrete-time process model x' = f(x, dt) + w, w ~ N(0, Q(dt)).
type Motion interface {
	Name() string
	Dim() int
	// PosIdx gives the state indices holding east (x) and north (y) position.
	PosIdx() (ix, iy int)
	Step(x *mat.M, dt float64) *mat.M
	Jac(x *mat.M, dt float64) *mat.M // ∂f/∂x at x
	Q(x *mat.M, dt float64) *mat.M
}

// Linear is implemented by motion models whose Step is exactly F·x.
type Linear interface {
	Motion
	F(dt float64) *mat.M
}

// ---------------------------------------------------------------- CV

// CV is nearly-constant velocity (discrete white-noise acceleration).
// Dim 4 = [x vx y vy]. Dim 5 appends a turn-rate slot that is pinned to zero,
// so CV and CT can share a state space inside an IMM.
type CV struct {
	Q0   float64 // acceleration spectral density (m²/s³)
	N    int     // 4 or 5
	QTau float64 // variance floor for the pinned ω slot (N==5)
}

func NewCV(q float64, dim int) *CV {
	if dim != 4 && dim != 5 {
		panic("model.NewCV: dim must be 4 or 5")
	}
	return &CV{Q0: q, N: dim, QTau: 1e-10}
}
func (m *CV) Name() string       { return "CV" }
func (m *CV) Dim() int           { return m.N }
func (m *CV) PosIdx() (int, int) { return 0, 2 }
func (m *CV) F(dt float64) *mat.M {
	f := mat.New(m.N, m.N)
	f.Set(0, 0, 1)
	f.Set(0, 1, dt)
	f.Set(1, 1, 1)
	f.Set(2, 2, 1)
	f.Set(2, 3, dt)
	f.Set(3, 3, 1)
	return f // slot 4 (if present) maps to zero: ω is pinned
}
func (m *CV) Step(x *mat.M, dt float64) *mat.M { return m.F(dt).Mul(x) }
func (m *CV) Jac(_ *mat.M, dt float64) *mat.M  { return m.F(dt) }
func (m *CV) Q(_ *mat.M, dt float64) *mat.M {
	q := mat.New(m.N, m.N)
	blk := func(o int) {
		q.Set(o, o, m.Q0*dt*dt*dt/3)
		q.Set(o, o+1, m.Q0*dt*dt/2)
		q.Set(o+1, o, m.Q0*dt*dt/2)
		q.Set(o+1, o+1, m.Q0*dt)
	}
	blk(0)
	blk(2)
	if m.N == 5 {
		q.Set(4, 4, m.QTau)
	}
	return q
}

// ---------------------------------------------------------------- CA

// CA is nearly-constant acceleration (Wiener-process jerk). State [x vx ax y vy ay].
type CA struct{ Q0 float64 }

func NewCA(q float64) *CA        { return &CA{q} }
func (m *CA) Name() string       { return "CA" }
func (m *CA) Dim() int           { return 6 }
func (m *CA) PosIdx() (int, int) { return 0, 3 }
func (m *CA) F(dt float64) *mat.M {
	f := mat.Eye(6)
	for _, o := range []int{0, 3} {
		f.Set(o, o+1, dt)
		f.Set(o, o+2, dt*dt/2)
		f.Set(o+1, o+2, dt)
	}
	return f
}
func (m *CA) Step(x *mat.M, dt float64) *mat.M { return m.F(dt).Mul(x) }
func (m *CA) Jac(_ *mat.M, dt float64) *mat.M  { return m.F(dt) }
func (m *CA) Q(_ *mat.M, dt float64) *mat.M {
	q := mat.New(6, 6)
	d2, d3, d4, d5 := dt*dt, dt*dt*dt, dt*dt*dt*dt, dt*dt*dt*dt*dt
	for _, o := range []int{0, 3} {
		v := [3][3]float64{
			{d5 / 20, d4 / 8, d3 / 6},
			{d4 / 8, d3 / 3, d2 / 2},
			{d3 / 6, d2 / 2, dt},
		}
		for i := 0; i < 3; i++ {
			for j := 0; j < 3; j++ {
				q.Set(o+i, o+j, m.Q0*v[i][j])
			}
		}
	}
	return q
}

// ---------------------------------------------------------------- CT

// CT is the coordinated-turn model with turn rate ω in the state: [x vx y vy ω].
// It is genuinely nonlinear, so it needs an EKF or UKF.
type CT struct {
	Q0 float64 // acceleration spectral density
	QW float64 // turn-rate random-walk spectral density (rad²/s³)
}

func NewCT(q, qw float64) *CT    { return &CT{q, qw} }
func (m *CT) Name() string       { return "CT" }
func (m *CT) Dim() int           { return 5 }
func (m *CT) PosIdx() (int, int) { return 0, 2 }

// sincoef returns sin(wT)/w and (1-cos(wT))/w with the w→0 limits (T and 0).
func sincoef(w, t float64) (s, c float64) {
	if math.Abs(w*t) < 1e-6 {
		return t - w*w*t*t*t/6, w * t * t / 2
	}
	return math.Sin(w*t) / w, (1 - math.Cos(w*t)) / w
}

func (m *CT) Step(x *mat.M, dt float64) *mat.M {
	px, vx, py, vy, w := x.D[0], x.D[1], x.D[2], x.D[3], x.D[4]
	s, c := sincoef(w, dt)
	cw, sw := math.Cos(w*dt), math.Sin(w*dt)
	return mat.Vec(
		px+s*vx-c*vy,
		cw*vx-sw*vy,
		py+c*vx+s*vy,
		sw*vx+cw*vy,
		w,
	)
}

// Jac: analytic for the position/velocity block, central difference for the ω column
// (whose closed form has an ugly removable singularity at ω=0).
func (m *CT) Jac(x *mat.M, dt float64) *mat.M {
	w := x.D[4]
	s, c := sincoef(w, dt)
	cw, sw := math.Cos(w*dt), math.Sin(w*dt)
	j := mat.New(5, 5)
	j.Set(0, 0, 1)
	j.Set(0, 1, s)
	j.Set(0, 3, -c)
	j.Set(1, 1, cw)
	j.Set(1, 3, -sw)
	j.Set(2, 1, c)
	j.Set(2, 2, 1)
	j.Set(2, 3, s)
	j.Set(3, 1, sw)
	j.Set(3, 3, cw)
	j.Set(4, 4, 1)
	h := 1e-6
	xp, xm := x.Clone(), x.Clone()
	xp.D[4] += h
	xm.D[4] -= h
	fp, fm := m.Step(xp, dt), m.Step(xm, dt)
	for i := 0; i < 4; i++ {
		j.Set(i, 4, (fp.D[i]-fm.D[i])/(2*h))
	}
	return j
}
func (m *CT) Q(_ *mat.M, dt float64) *mat.M {
	q := mat.New(5, 5)
	for _, o := range []int{0, 2} {
		q.Set(o, o, m.Q0*dt*dt*dt/3)
		q.Set(o, o+1, m.Q0*dt*dt/2)
		q.Set(o+1, o, m.Q0*dt*dt/2)
		q.Set(o+1, o+1, m.Q0*dt)
	}
	q.Set(4, 4, m.QW*dt)
	return q
}
