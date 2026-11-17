package orrery

import (
	"errors"
	"fmt"
	"math"
)

// Body is a point mass.
type Body struct {
	Name string
	M    float64
	Pos  Vec3
	Vel  Vec3
}

// System is a set of bodies plus the physics parameters.
type System struct {
	Title  string
	G      float64 // gravitational constant
	Eps    float64 // Plummer softening length
	Theta  float64 // Barnes–Hut opening angle; 0 = exact direct summation
	Bodies []Body
	T      float64 // current time

	Evals int64 // number of acceleration evaluations performed (cost metric)
}

// Clone returns a deep copy (counters reset).
func (s *System) Clone() *System {
	c := *s
	c.Bodies = append([]Body(nil), s.Bodies...)
	c.Evals = 0
	return &c
}

// Validate checks the system is physically meaningful.
func (s *System) Validate() error {
	if len(s.Bodies) == 0 {
		return errors.New("system has no bodies")
	}
	if !(s.G > 0) || math.IsInf(s.G, 0) {
		return fmt.Errorf("G must be positive and finite, got %v", s.G)
	}
	if s.Eps < 0 || math.IsNaN(s.Eps) {
		return fmt.Errorf("softening must be >= 0, got %v", s.Eps)
	}
	if s.Theta < 0 || math.IsNaN(s.Theta) {
		return fmt.Errorf("theta must be >= 0, got %v", s.Theta)
	}
	if s.Eps == 0 {
		for i := 0; i < len(s.Bodies); i++ {
			for j := i + 1; j < len(s.Bodies); j++ {
				if s.Bodies[i].Pos == s.Bodies[j].Pos {
					return fmt.Errorf("bodies %d (%s) and %d (%s) occupy the same point; the potential is infinite (use eps > 0 or move one)",
						i, s.Bodies[i].Name, j, s.Bodies[j].Name)
				}
			}
		}
	}
	seen := map[string]bool{}
	for i, b := range s.Bodies {
		if !(b.M > 0) || math.IsInf(b.M, 0) {
			return fmt.Errorf("body %d (%s): mass must be positive and finite, got %v", i, b.Name, b.M)
		}
		for _, v := range []float64{b.Pos.X, b.Pos.Y, b.Pos.Z, b.Vel.X, b.Vel.Y, b.Vel.Z} {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return fmt.Errorf("body %d (%s): non-finite state", i, b.Name)
			}
		}
		if b.Name != "" {
			if seen[b.Name] {
				return fmt.Errorf("duplicate body name %q", b.Name)
			}
			seen[b.Name] = true
		}
	}
	return nil
}

// TotalMass returns the sum of masses.
func (s *System) TotalMass() float64 {
	m := 0.0
	for _, b := range s.Bodies {
		m += b.M
	}
	return m
}

// COM returns centre-of-mass position and velocity.
func (s *System) COM() (pos, vel Vec3) {
	M := s.TotalMass()
	for _, b := range s.Bodies {
		pos = pos.AddScaled(b.Pos, b.M)
		vel = vel.AddScaled(b.Vel, b.M)
	}
	return pos.Scale(1 / M), vel.Scale(1 / M)
}

// ToBarycentric shifts the system so COM is at the origin and at rest.
func (s *System) ToBarycentric() {
	p, v := s.COM()
	for i := range s.Bodies {
		s.Bodies[i].Pos = s.Bodies[i].Pos.Sub(p)
		s.Bodies[i].Vel = s.Bodies[i].Vel.Sub(v)
	}
}

// Kinetic energy.
func (s *System) Kinetic() float64 {
	k := 0.0
	for _, b := range s.Bodies {
		k += 0.5 * b.M * b.Vel.Norm2()
	}
	return k
}

// Potential energy with Plummer softening, exact O(N²) (used for diagnostics
// regardless of the force solver so energy is always measured honestly).
func (s *System) Potential() float64 {
	u := 0.0
	e2 := s.Eps * s.Eps
	for i := 0; i < len(s.Bodies); i++ {
		for j := i + 1; j < len(s.Bodies); j++ {
			d := s.Bodies[i].Pos.Sub(s.Bodies[j].Pos)
			u -= s.G * s.Bodies[i].M * s.Bodies[j].M / math.Sqrt(d.Norm2()+e2)
		}
	}
	return u
}

// Energy is kinetic + potential.
func (s *System) Energy() float64 { return s.Kinetic() + s.Potential() }

// Momentum is the total linear momentum.
func (s *System) Momentum() Vec3 {
	var p Vec3
	for _, b := range s.Bodies {
		p = p.AddScaled(b.Vel, b.M)
	}
	return p
}

// AngularMomentum about the origin.
func (s *System) AngularMomentum() Vec3 {
	var l Vec3
	for _, b := range s.Bodies {
		l = l.Add(b.Pos.Cross(b.Vel).Scale(b.M))
	}
	return l
}

// Diag is a snapshot of conserved quantities.
type Diag struct {
	T        float64
	E        float64
	Virial   float64 // 2K/|U|
	P        float64 // |total momentum|
	L        Vec3
	COMDrift float64 // |COM position - COM position at t0 - V t| computed by caller
}

// Diagnose snapshots the conserved quantities.
func (s *System) Diagnose() Diag {
	k, u := s.Kinetic(), s.Potential()
	v := math.NaN()
	if u != 0 {
		v = 2 * k / math.Abs(u)
	}
	return Diag{T: s.T, E: k + u, Virial: v, P: s.Momentum().Norm(), L: s.AngularMomentum()}
}

// Index finds a body by name, or -1.
func (s *System) Index(name string) int {
	for i, b := range s.Bodies {
		if b.Name == name {
			return i
		}
	}
	return -1
}
