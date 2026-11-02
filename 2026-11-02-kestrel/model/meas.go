package model

import (
	"math"

	"kestrel/mat"
	"kestrel/stat"
)

// Meas is a measurement model z = h(x) + v, v ~ N(0, R).
type Meas interface {
	Name() string
	Dim() int
	H(x *mat.M) *mat.M   // predicted measurement
	Jac(x *mat.M) *mat.M // ∂h/∂x
	R() *mat.M
	// Resid returns a−b with any circular components wrapped (bearing).
	Resid(a, b *mat.M) *mat.M
}

// LinearMeas is implemented when h(x) = Hx exactly.
type LinearMeas interface {
	Meas
	HMat(stateDim int) *mat.M
}

// ---------------------------------------------------------------- Cartesian

// Cartesian observes (x, y) directly.
type Cartesian struct {
	IX, IY int
	Sigma  float64
}

func NewCartesian(ix, iy int, sigma float64) *Cartesian { return &Cartesian{ix, iy, sigma} }
func (c *Cartesian) Name() string                       { return "cartesian" }
func (c *Cartesian) Dim() int                           { return 2 }
func (c *Cartesian) H(x *mat.M) *mat.M                  { return mat.Vec(x.D[c.IX], x.D[c.IY]) }
func (c *Cartesian) R() *mat.M                          { return mat.Diag(c.Sigma*c.Sigma, c.Sigma*c.Sigma) }
func (c *Cartesian) Resid(a, b *mat.M) *mat.M           { return a.Sub(b) }
func (c *Cartesian) HMat(n int) *mat.M {
	h := mat.New(2, n)
	h.Set(0, c.IX, 1)
	h.Set(1, c.IY, 1)
	return h
}
func (c *Cartesian) Jac(x *mat.M) *mat.M { return c.HMat(x.R) }

// ---------------------------------------------------------------- Radar

// Radar measures range and bearing (atan2(dy, dx), radians from +x axis)
// from a sensor at (SX, SY).
type Radar struct {
	IX, IY     int
	SX, SY     float64
	SigR, SigB float64
}

func NewRadar(ix, iy int, sx, sy, sigR, sigB float64) *Radar {
	return &Radar{ix, iy, sx, sy, sigR, sigB}
}
func (r *Radar) Name() string { return "radar" }
func (r *Radar) Dim() int     { return 2 }
func (r *Radar) H(x *mat.M) *mat.M {
	dx, dy := x.D[r.IX]-r.SX, x.D[r.IY]-r.SY
	return mat.Vec(math.Hypot(dx, dy), math.Atan2(dy, dx))
}
func (r *Radar) Jac(x *mat.M) *mat.M {
	dx, dy := x.D[r.IX]-r.SX, x.D[r.IY]-r.SY
	rho2 := dx*dx + dy*dy
	rho := math.Sqrt(rho2)
	if rho < 1e-9 { // target on top of the sensor: bearing undefined, use a safe finite slope
		rho, rho2 = 1e-9, 1e-18
	}
	j := mat.New(2, x.R)
	j.Set(0, r.IX, dx/rho)
	j.Set(0, r.IY, dy/rho)
	j.Set(1, r.IX, -dy/rho2)
	j.Set(1, r.IY, dx/rho2)
	return j
}
func (r *Radar) R() *mat.M { return mat.Diag(r.SigR*r.SigR, r.SigB*r.SigB) }
func (r *Radar) Resid(a, b *mat.M) *mat.M {
	return mat.Vec(a.D[0]-b.D[0], stat.WrapAngle(a.D[1]-b.D[1]))
}

// ToCartesian converts a radar detection to a position (used to birth tracks).
func (r *Radar) ToCartesian(z *mat.M) (x, y float64) {
	return r.SX + z.D[0]*math.Cos(z.D[1]), r.SY + z.D[0]*math.Sin(z.D[1])
}

// CartCov is the first-order Cartesian covariance of a radar detection (range ρ, bearing θ).
func (r *Radar) CartCov(z *mat.M) *mat.M {
	rho, th := z.D[0], z.D[1]
	c, s := math.Cos(th), math.Sin(th)
	j := mat.From(2, 2, c, -rho*s, s, rho*c)
	return j.Mul(r.R()).Mul(j.T())
}
