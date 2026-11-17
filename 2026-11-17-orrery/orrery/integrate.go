package orrery

import (
	"errors"
	"fmt"
	"math"
	"sort"
)

// Method names an integration scheme.
type Method string

const (
	Euler         Method = "euler"    // explicit Euler (order 1, not symplectic)
	SymplecticEul Method = "symeuler" // semi-implicit Euler (order 1, symplectic)
	Leapfrog      Method = "leapfrog" // kick-drift-kick Störmer–Verlet (order 2, symplectic)
	Yoshida4      Method = "yoshida4" // Yoshida triple-jump leapfrog (order 4, symplectic)
	RK4           Method = "rk4"      // classical Runge–Kutta (order 4, not symplectic)
	DOPRI5        Method = "dopri5"   // adaptive Dormand–Prince 5(4) with FSAL
	WisdomHolman  Method = "wh"       // democratic-heliocentric Kepler-drift map (order 2, symplectic)
)

// Methods lists every method in presentation order.
func Methods() []Method {
	return []Method{Euler, SymplecticEul, Leapfrog, Yoshida4, RK4, DOPRI5, WisdomHolman}
}

// ParseMethod validates a method name.
func ParseMethod(s string) (Method, error) {
	for _, m := range Methods() {
		if string(m) == s {
			return m, nil
		}
	}
	names := make([]string, 0, 7)
	for _, m := range Methods() {
		names = append(names, string(m))
	}
	sort.Strings(names)
	return "", fmt.Errorf("unknown method %q (choose from %v)", s, names)
}

// Symplectic reports whether the method is a symplectic map.
func (m Method) Symplectic() bool {
	switch m {
	case SymplecticEul, Leapfrog, Yoshida4, WisdomHolman:
		return true
	}
	return false
}

// Order is the nominal convergence order.
func (m Method) Order() int {
	switch m {
	case Euler, SymplecticEul:
		return 1
	case Leapfrog, WisdomHolman:
		return 2
	case Yoshida4, RK4:
		return 4
	case DOPRI5:
		return 5
	}
	return 0
}

// Integrator advances a System in time.
type Integrator struct {
	Method Method
	Sys    *System
	Tol    float64 // DOPRI5 tolerance (abs and rel), default 1e-10

	Steps    int64 // accepted steps
	Rejected int64 // rejected adaptive steps

	acc      []Vec3
	accValid bool
	h        float64 // adaptive step size memory
	kStage   [7][]float64
	fsalOK   bool
}

// NewIntegrator creates an integrator; WisdomHolman needs body 0 to be the
// dominant central mass and zero softening.
func NewIntegrator(sys *System, m Method) (*Integrator, error) {
	if err := sys.Validate(); err != nil {
		return nil, err
	}
	if _, err := ParseMethod(string(m)); err != nil {
		return nil, err
	}
	if m == WisdomHolman {
		if sys.Eps != 0 {
			return nil, errors.New("wh requires zero softening")
		}
		if len(sys.Bodies) < 2 {
			return nil, errors.New("wh needs a central body and at least one more")
		}
		for i := 1; i < len(sys.Bodies); i++ {
			if sys.Bodies[i].M > sys.Bodies[0].M {
				return nil, fmt.Errorf("wh requires body 0 to be the most massive (body %d is heavier)", i)
			}
		}
	}
	return &Integrator{Method: m, Sys: sys, Tol: 1e-10, acc: make([]Vec3, len(sys.Bodies))}, nil
}

// Invalidate must be called if the system state is modified externally.
func (it *Integrator) Invalidate() { it.accValid = false; it.fsalOK = false }

func (it *Integrator) positions() []Vec3 {
	p := make([]Vec3, len(it.Sys.Bodies))
	for i, b := range it.Sys.Bodies {
		p[i] = b.Pos
	}
	return p
}

func (it *Integrator) refreshAcc() {
	if it.accValid {
		return
	}
	it.Sys.Accel(it.positions(), it.acc)
	it.accValid = true
}

// Advance integrates the system forward by dt (may be negative for fixed-step
// methods; time reversal is part of the verification suite). Adaptive
// DOPRI5 takes as many internal steps as needed to land exactly on t+dt.
func (it *Integrator) Advance(dt float64) error {
	if math.IsNaN(dt) || math.IsInf(dt, 0) {
		return errors.New("non-finite time step")
	}
	s := it.Sys
	switch it.Method {
	case Euler:
		it.refreshAcc()
		for i := range s.Bodies {
			b := &s.Bodies[i]
			b.Pos = b.Pos.AddScaled(b.Vel, dt)
			b.Vel = b.Vel.AddScaled(it.acc[i], dt)
		}
		it.accValid = false
	case SymplecticEul:
		it.refreshAcc()
		for i := range s.Bodies {
			b := &s.Bodies[i]
			b.Vel = b.Vel.AddScaled(it.acc[i], dt)
			b.Pos = b.Pos.AddScaled(b.Vel, dt)
		}
		it.accValid = false
	case Leapfrog:
		it.refreshAcc()
		for i := range s.Bodies {
			s.Bodies[i].Vel = s.Bodies[i].Vel.AddScaled(it.acc[i], dt/2)
			s.Bodies[i].Pos = s.Bodies[i].Pos.AddScaled(s.Bodies[i].Vel, dt)
		}
		it.recompute()
		for i := range s.Bodies {
			s.Bodies[i].Vel = s.Bodies[i].Vel.AddScaled(it.acc[i], dt/2)
		}
	case Yoshida4:
		cb := math.Cbrt(2)
		w1 := 1 / (2 - cb)
		w0 := -cb / (2 - cb)
		c := [4]float64{w1 / 2, (w0 + w1) / 2, (w0 + w1) / 2, w1 / 2}
		d := [3]float64{w1, w0, w1}
		for k := 0; k < 4; k++ {
			for i := range s.Bodies {
				s.Bodies[i].Pos = s.Bodies[i].Pos.AddScaled(s.Bodies[i].Vel, c[k]*dt)
			}
			if k < 3 {
				it.recompute()
				for i := range s.Bodies {
					s.Bodies[i].Vel = s.Bodies[i].Vel.AddScaled(it.acc[i], d[k]*dt)
				}
			}
		}
		it.accValid = false
	case RK4:
		it.rk4(dt)
	case DOPRI5:
		return it.dopri(dt) // advances s.T and Steps itself
	case WisdomHolman:
		if err := it.wisdomHolman(dt); err != nil {
			return err
		}
	}
	s.T += dt
	it.Steps++
	return it.checkFinite()
}

// recompute refreshes the cached acceleration at the current positions.
func (it *Integrator) recompute() {
	it.Sys.Accel(it.positions(), it.acc)
	it.accValid = true
}

func (it *Integrator) checkFinite() error {
	for _, b := range it.Sys.Bodies {
		if math.IsNaN(b.Pos.X+b.Pos.Y+b.Pos.Z+b.Vel.X+b.Vel.Y+b.Vel.Z) ||
			math.IsInf(b.Pos.X+b.Pos.Y+b.Pos.Z+b.Vel.X+b.Vel.Y+b.Vel.Z, 0) {
			return fmt.Errorf("state became non-finite at t=%g (body %s): step too large or a collision", it.Sys.T, b.Name)
		}
	}
	return nil
}

// ------------------------------------------------------------ flat-state ODE

func (it *Integrator) pack() []float64 {
	n := len(it.Sys.Bodies)
	y := make([]float64, 6*n)
	for i, b := range it.Sys.Bodies {
		y[3*i], y[3*i+1], y[3*i+2] = b.Pos.X, b.Pos.Y, b.Pos.Z
		y[3*n+3*i], y[3*n+3*i+1], y[3*n+3*i+2] = b.Vel.X, b.Vel.Y, b.Vel.Z
	}
	return y
}

func (it *Integrator) unpack(y []float64) {
	n := len(it.Sys.Bodies)
	for i := range it.Sys.Bodies {
		it.Sys.Bodies[i].Pos = Vec3{y[3*i], y[3*i+1], y[3*i+2]}
		it.Sys.Bodies[i].Vel = Vec3{y[3*n+3*i], y[3*n+3*i+1], y[3*n+3*i+2]}
	}
	it.accValid = false
}

// deriv writes dy/dt for state y.
func (it *Integrator) deriv(y, dy []float64) {
	n := len(it.Sys.Bodies)
	pos := make([]Vec3, n)
	for i := range pos {
		pos[i] = Vec3{y[3*i], y[3*i+1], y[3*i+2]}
	}
	a := make([]Vec3, n)
	it.Sys.Accel(pos, a)
	copy(dy[:3*n], y[3*n:])
	for i := range a {
		dy[3*n+3*i], dy[3*n+3*i+1], dy[3*n+3*i+2] = a[i].X, a[i].Y, a[i].Z
	}
}

func (it *Integrator) rk4(h float64) {
	y := it.pack()
	m := len(y)
	k1, k2, k3, k4, t := make([]float64, m), make([]float64, m), make([]float64, m), make([]float64, m), make([]float64, m)
	it.deriv(y, k1)
	for i := range y {
		t[i] = y[i] + 0.5*h*k1[i]
	}
	it.deriv(t, k2)
	for i := range y {
		t[i] = y[i] + 0.5*h*k2[i]
	}
	it.deriv(t, k3)
	for i := range y {
		t[i] = y[i] + h*k3[i]
	}
	it.deriv(t, k4)
	for i := range y {
		y[i] += h / 6 * (k1[i] + 2*k2[i] + 2*k3[i] + k4[i])
	}
	it.unpack(y)
}

// Dormand–Prince coefficients.
var (
	dpC = [7]float64{0, 1.0 / 5, 3.0 / 10, 4.0 / 5, 8.0 / 9, 1, 1}
	dpA = [7][6]float64{
		{},
		{1.0 / 5},
		{3.0 / 40, 9.0 / 40},
		{44.0 / 45, -56.0 / 15, 32.0 / 9},
		{19372.0 / 6561, -25360.0 / 2187, 64448.0 / 6561, -212.0 / 729},
		{9017.0 / 3168, -355.0 / 33, 46732.0 / 5247, 49.0 / 176, -5103.0 / 18656},
		{35.0 / 384, 0, 500.0 / 1113, 125.0 / 192, -2187.0 / 6784, 11.0 / 84},
	}
	dpB5 = [7]float64{35.0 / 384, 0, 500.0 / 1113, 125.0 / 192, -2187.0 / 6784, 11.0 / 84, 0}
	dpB4 = [7]float64{5179.0 / 57600, 0, 7571.0 / 16695, 393.0 / 640, -92097.0 / 339200, 187.0 / 2100, 1.0 / 40}
)

func (it *Integrator) dopri(span float64) error {
	if span == 0 {
		return nil
	}
	s := it.Sys
	y := it.pack()
	m := len(y)
	for i := range it.kStage {
		if len(it.kStage[i]) != m {
			it.kStage[i] = make([]float64, m)
			it.fsalOK = false
		}
	}
	tmp, ynew := make([]float64, m), make([]float64, m)
	dir := 1.0
	if span < 0 {
		dir = -1
	}
	remaining := math.Abs(span)
	if it.h <= 0 {
		it.h = math.Min(remaining, 1e-3)
	}
	tol := it.Tol
	if !(tol > 0) {
		tol = 1e-10
	}
	const maxSteps = 50_000_000
	for steps := 0; remaining > 0; steps++ {
		if steps > maxSteps {
			return errors.New("dopri5: too many steps")
		}
		h := math.Min(it.h, remaining)
		last := h >= remaining
		if !it.fsalOK {
			it.deriv(y, it.kStage[0])
		}
		hs := dir * h
		for st := 1; st < 7; st++ {
			for i := 0; i < m; i++ {
				acc := 0.0
				for j := 0; j < st; j++ {
					acc += dpA[st][j] * it.kStage[j][i]
				}
				tmp[i] = y[i] + hs*acc
			}
			it.deriv(tmp, it.kStage[st])
		}
		errn := 0.0
		for i := 0; i < m; i++ {
			a5, a4 := 0.0, 0.0
			for j := 0; j < 7; j++ {
				a5 += dpB5[j] * it.kStage[j][i]
				a4 += dpB4[j] * it.kStage[j][i]
			}
			ynew[i] = y[i] + hs*a5
			sc := tol + tol*math.Max(math.Abs(y[i]), math.Abs(ynew[i]))
			e := hs * (a5 - a4) / sc
			errn += e * e
		}
		errn = math.Sqrt(errn / float64(m))
		if math.IsNaN(errn) {
			return fmt.Errorf("dopri5: non-finite error estimate at t=%g", s.T)
		}
		if errn <= 1 {
			copy(y, ynew)
			copy(it.kStage[0], it.kStage[6]) // FSAL
			it.fsalOK = true
			s.T += hs
			it.Steps++
			if last {
				remaining = 0
			} else {
				remaining -= h
			}
		} else {
			it.Rejected++
		}
		fac := 0.9 * math.Pow(math.Max(errn, 1e-10), -0.2)
		fac = math.Min(5, math.Max(0.2, fac))
		if errn <= 1 && last {
			// don't let the clipped final step shrink the remembered step
			it.h = math.Max(it.h, h*fac)
			if it.h > 1e9 {
				it.h = 1e9
			}
		} else {
			it.h = h * fac
		}
		if it.h < 1e-14*math.Max(1, math.Abs(s.T)) {
			return fmt.Errorf("dopri5: step size underflow at t=%g (collision?)", s.T)
		}
	}
	it.unpack(y)
	return it.checkFinite()
}

// ------------------------------------------------------- Wisdom–Holman map

// wisdomHolman performs one democratic-heliocentric Kepler-drift step: kick the
// planet–planet interaction for h/2, drift the Sun term h/2, advance every
// planet on its exact Kepler orbit about body 0 for h, then repeat the drift
// and kick. Body 0 is the central mass.
func (it *Integrator) wisdomHolman(h float64) error {
	s := it.Sys
	n := len(s.Bodies)
	m0 := s.Bodies[0].M
	mu := s.G * m0
	M := s.TotalMass()
	R, V := s.COM()

	Q := make([]Vec3, n) // heliocentric positions (index 0 unused)
	u := make([]Vec3, n) // barycentric velocities (v - V)
	for i := 1; i < n; i++ {
		Q[i] = s.Bodies[i].Pos.Sub(s.Bodies[0].Pos)
		u[i] = s.Bodies[i].Vel.Sub(V)
	}
	kick := func(dt float64) {
		a := make([]Vec3, n)
		for i := 1; i < n; i++ {
			for j := i + 1; j < n; j++ {
				d := Q[j].Sub(Q[i])
				r2 := d.Norm2()
				inv := 1 / (r2 * math.Sqrt(r2))
				a[i] = a[i].AddScaled(d, s.G*s.Bodies[j].M*inv)
				a[j] = a[j].AddScaled(d, -s.G*s.Bodies[i].M*inv)
			}
		}
		for i := 1; i < n; i++ {
			u[i] = u[i].AddScaled(a[i], dt)
		}
	}
	sunDrift := func(dt float64) {
		var p Vec3
		for i := 1; i < n; i++ {
			p = p.AddScaled(u[i], s.Bodies[i].M)
		}
		d := p.Scale(dt / m0)
		for i := 1; i < n; i++ {
			Q[i] = Q[i].Add(d)
		}
	}
	s.Evals++
	kick(h / 2)
	sunDrift(h / 2)
	for i := 1; i < n; i++ {
		q, v, err := KeplerPropagate(Q[i], u[i], mu, h)
		if err != nil {
			return fmt.Errorf("wh: body %s: %v", s.Bodies[i].Name, err)
		}
		Q[i], u[i] = q, v
	}
	sunDrift(h / 2)
	kick(h / 2)

	// reconstruct inertial state
	Rn := R.AddScaled(V, h)
	var wq, wu Vec3
	for i := 1; i < n; i++ {
		wq = wq.AddScaled(Q[i], s.Bodies[i].M)
		wu = wu.AddScaled(u[i], s.Bodies[i].M)
	}
	r0 := Rn.Sub(wq.Scale(1 / M))
	s.Bodies[0].Pos = r0
	s.Bodies[0].Vel = wu.Scale(-1 / m0).Add(V)
	for i := 1; i < n; i++ {
		s.Bodies[i].Pos = r0.Add(Q[i])
		s.Bodies[i].Vel = u[i].Add(V)
	}
	it.accValid = false
	return nil
}
