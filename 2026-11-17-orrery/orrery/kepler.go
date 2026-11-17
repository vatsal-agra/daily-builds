package orrery

import (
	"errors"
	"math"
)

// stumpff returns the Stumpff functions C(z), S(z).
func stumpff(z float64) (c, s float64) {
	switch {
	case math.Abs(z) < 1e-6:
		return 0.5 - z/24 + z*z/720, 1.0/6 - z/120 + z*z/5040
	case z > 0:
		r := math.Sqrt(z)
		return (1 - math.Cos(r)) / z, (r - math.Sin(r)) / (z * r)
	default:
		r := math.Sqrt(-z)
		return (math.Cosh(r) - 1) / -z, (math.Sinh(r) - r) / (-z * r)
	}
}

// KeplerPropagate advances a two-body state (r0, v0) about a fixed centre of
// gravitational parameter mu by dt using universal variables (valid for
// elliptic, parabolic and hyperbolic orbits). The universal Kepler equation is
// monotonic in the universal anomaly, so a bracketed Newton iteration cannot
// diverge.
func KeplerPropagate(r0, v0 Vec3, mu, dt float64) (Vec3, Vec3, error) {
	if !(mu > 0) {
		return r0, v0, errors.New("mu must be positive")
	}
	if dt == 0 {
		return r0, v0, nil
	}
	rr := r0.Norm()
	if rr == 0 {
		return r0, v0, errors.New("body at the attracting centre")
	}
	sm := math.Sqrt(mu)
	vr := r0.Dot(v0) / sm
	alpha := 2/rr - v0.Norm2()/mu
	if alpha > 1e-12 { // elliptic: reduce by whole periods for accuracy
		per := 2 * math.Pi / (sm * math.Pow(alpha, 1.5))
		dt = math.Remainder(dt, per)
		if dt == 0 {
			return r0, v0, nil
		}
	}
	target := sm * dt
	F := func(x float64) (f, df float64) {
		z := alpha * x * x
		c, s := stumpff(z)
		f = vr*x*x*c + (1-alpha*rr)*x*x*x*s + rr*x - target
		df = vr*x*(1-z*s) + (1-alpha*rr)*x*x*c + rr
		return
	}
	// bracket: F is increasing; F(0) = -target
	lo, hi := 0.0, 0.0
	if target > 0 {
		hi = math.Max(1e-3, sm*dt/rr)
		for k := 0; k < 200; k++ {
			if f, _ := F(hi); f >= 0 {
				break
			}
			lo = hi
			hi *= 2
		}
	} else {
		lo = -math.Max(1e-3, -sm*dt/rr)
		for k := 0; k < 200; k++ {
			if f, _ := F(lo); f <= 0 {
				break
			}
			hi = lo
			lo *= 2
		}
	}
	x := 0.5 * (lo + hi)
	for it := 0; it < 100; it++ {
		f, df := F(x)
		if f > 0 {
			hi = x
		} else {
			lo = x
		}
		nx := x - f/df
		if !(nx > lo && nx < hi) || math.IsNaN(nx) {
			nx = 0.5 * (lo + hi)
		}
		if math.Abs(nx-x) <= 1e-15*math.Max(1, math.Abs(x)) {
			x = nx
			break
		}
		x = nx
	}
	z := alpha * x * x
	c, s := stumpff(z)
	f := 1 - x*x/rr*c
	g := dt - x*x*x/sm*s
	r := r0.Scale(f).AddScaled(v0, g)
	rn := r.Norm()
	fd := sm / (rn * rr) * (z*s - 1) * x
	gd := 1 - x*x/rn*c
	v := r0.Scale(fd).AddScaled(v0, gd)
	return r, v, nil
}

// Elements are classical Keplerian orbital elements.
type Elements struct {
	A, E       float64 // semi-major axis (negative if hyperbolic), eccentricity
	I          float64 // inclination (rad)
	Raan, Argp float64 // longitude of ascending node, argument of periapsis (rad)
	Nu         float64 // true anomaly (rad)
	M          float64 // mean anomaly (rad)
	Period     float64 // NaN if unbound
}

// ElementsFromState converts a relative state to orbital elements.
func ElementsFromState(r, v Vec3, mu float64) (Elements, error) {
	rn := r.Norm()
	if rn == 0 || !(mu > 0) {
		return Elements{}, errors.New("degenerate state")
	}
	h := r.Cross(v)
	hn := h.Norm()
	if hn == 0 {
		return Elements{}, errors.New("radial orbit: elements undefined")
	}
	ev := v.Cross(h).Scale(1 / mu).Sub(r.Scale(1 / rn))
	e := ev.Norm()
	energy := v.Norm2()/2 - mu/rn
	var el Elements
	el.E = e
	if math.Abs(energy) < 1e-14*mu/rn {
		el.A = math.Inf(1) // parabolic
	} else {
		el.A = -mu / (2 * energy)
	}
	el.I = math.Acos(clamp(h.Z/hn, -1, 1))
	nvec := Vec3{-h.Y, h.X, 0}
	nn := nvec.Norm()
	const eps = 1e-11
	switch {
	case nn > eps*hn:
		el.Raan = math.Atan2(nvec.Y, nvec.X)
	default:
		el.Raan = 0
	}
	if e > eps {
		if nn > eps*hn {
			el.Argp = angleBetween(nvec, ev, h)
		} else { // equatorial: measure from x axis
			el.Argp = math.Atan2(ev.Y, ev.X)
			if h.Z < 0 {
				el.Argp = -el.Argp
			}
		}
		el.Nu = angleBetween(ev, r, h)
	} else { // circular: argp = 0, nu measured from ascending node (or x axis)
		el.Argp = 0
		if nn > eps*hn {
			el.Nu = angleBetween(nvec, r, h)
		} else {
			el.Nu = math.Atan2(r.Y, r.X)
			if h.Z < 0 {
				el.Nu = -el.Nu
			}
		}
	}
	el.Raan = wrap2pi(el.Raan)
	el.Argp = wrap2pi(el.Argp)
	el.Nu = wrap2pi(el.Nu)
	el.Period = math.NaN()
	switch {
	case e < 1-1e-12 && el.A > 0:
		E := 2 * math.Atan2(math.Sqrt(1-e)*math.Sin(el.Nu/2), math.Sqrt(1+e)*math.Cos(el.Nu/2))
		el.M = wrap2pi(E - e*math.Sin(E))
		el.Period = 2 * math.Pi * math.Sqrt(el.A*el.A*el.A/mu)
	case e > 1+1e-12:
		nu := el.Nu
		if nu > math.Pi {
			nu -= 2 * math.Pi
		}
		H := 2 * math.Atanh(math.Sqrt((e-1)/(e+1))*math.Tan(nu/2))
		el.M = e*math.Sinh(H) - H
	}
	return el, nil
}

// StateFromElements builds a relative state. Valid for elliptic orbits (e<1)
// where the mean anomaly M is used; solves Kepler's equation by Newton with a
// safe starting guess.
func StateFromElements(el Elements, mu float64) (Vec3, Vec3, error) {
	if !(mu > 0) {
		return Vec3{}, Vec3{}, errors.New("mu must be positive")
	}
	if el.E < 0 || el.E >= 1 {
		return Vec3{}, Vec3{}, errors.New("eccentricity must satisfy 0 <= e < 1")
	}
	if !(el.A > 0) {
		return Vec3{}, Vec3{}, errors.New("semi-major axis must be positive")
	}
	E, err := SolveKepler(el.M, el.E)
	if err != nil {
		return Vec3{}, Vec3{}, err
	}
	a, e := el.A, el.E
	cosE, sinE := math.Cos(E), math.Sin(E)
	// perifocal coordinates
	px, py := a*(cosE-e), a*math.Sqrt(1-e*e)*sinE
	rn := a * (1 - e*cosE)
	k := math.Sqrt(mu*a) / rn
	vx, vy := -k*sinE, k*math.Sqrt(1-e*e)*cosE
	rot := func(x, y float64) Vec3 {
		cO, sO := math.Cos(el.Raan), math.Sin(el.Raan)
		cw, sw := math.Cos(el.Argp), math.Sin(el.Argp)
		ci, si := math.Cos(el.I), math.Sin(el.I)
		return Vec3{
			(cO*cw-sO*sw*ci)*x + (-cO*sw-sO*cw*ci)*y,
			(sO*cw+cO*sw*ci)*x + (-sO*sw+cO*cw*ci)*y,
			(sw*si)*x + (cw*si)*y,
		}
	}
	return rot(px, py), rot(vx, vy), nil
}

// SolveKepler solves M = E - e sin E for E (elliptic).
func SolveKepler(M, e float64) (float64, error) {
	if e < 0 || e >= 1 {
		return 0, errors.New("e out of range")
	}
	M = math.Remainder(M, 2*math.Pi)
	E := M + e*math.Sin(M)
	if e > 0.8 {
		E = math.Pi * sign(M)
	}
	for i := 0; i < 100; i++ {
		d := (E - e*math.Sin(E) - M) / (1 - e*math.Cos(E))
		E -= d
		if math.Abs(d) < 1e-15 {
			return E, nil
		}
	}
	return E, errors.New("Kepler solver did not converge")
}

// KeplerOracle advances elliptic orbit elements analytically (independent of
// the universal-variable code): returns the relative state at time dt later.
func KeplerOracle(r0, v0 Vec3, mu, dt float64) (Vec3, Vec3, error) {
	el, err := ElementsFromState(r0, v0, mu)
	if err != nil {
		return r0, v0, err
	}
	if el.E >= 1 || !(el.A > 0) {
		return r0, v0, errors.New("oracle supports bound orbits only")
	}
	n := math.Sqrt(mu / (el.A * el.A * el.A))
	el.M += n * dt
	return StateFromElements(el, mu)
}

func sign(x float64) float64 {
	if x < 0 {
		return -1
	}
	return 1
}

func clamp(x, lo, hi float64) float64 { return math.Max(lo, math.Min(hi, x)) }

func wrap2pi(a float64) float64 {
	a = math.Mod(a, 2*math.Pi)
	if a < 0 {
		a += 2 * math.Pi
	}
	return a
}

// angleBetween returns the signed angle from a to b about axis n (right-handed).
func angleBetween(a, b, n Vec3) float64 {
	return math.Atan2(a.Cross(b).Dot(n)/n.Norm(), a.Dot(b))
}
