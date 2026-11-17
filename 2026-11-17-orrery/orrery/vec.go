// Package orrery is an N-body gravity laboratory: integrators, a Barnes–Hut
// tree, an exact Kepler solver, scenarios and diagnostics. Units are chosen by
// the scenario through the gravitational constant G (default 1).
package orrery

import "math"

// Vec3 is a 3-vector.
type Vec3 struct{ X, Y, Z float64 }

func (a Vec3) Add(b Vec3) Vec3      { return Vec3{a.X + b.X, a.Y + b.Y, a.Z + b.Z} }
func (a Vec3) Sub(b Vec3) Vec3      { return Vec3{a.X - b.X, a.Y - b.Y, a.Z - b.Z} }
func (a Vec3) Scale(s float64) Vec3 { return Vec3{a.X * s, a.Y * s, a.Z * s} }
func (a Vec3) Dot(b Vec3) float64   { return a.X*b.X + a.Y*b.Y + a.Z*b.Z }
func (a Vec3) Cross(b Vec3) Vec3 {
	return Vec3{a.Y*b.Z - a.Z*b.Y, a.Z*b.X - a.X*b.Z, a.X*b.Y - a.Y*b.X}
}
func (a Vec3) Norm2() float64 { return a.Dot(a) }
func (a Vec3) Norm() float64  { return math.Sqrt(a.Dot(a)) }

// AddScaled returns a + s*b.
func (a Vec3) AddScaled(b Vec3, s float64) Vec3 {
	return Vec3{a.X + s*b.X, a.Y + s*b.Y, a.Z + s*b.Z}
}
