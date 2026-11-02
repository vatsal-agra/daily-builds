// Package stat has seeded Gaussian sampling and chi-square distribution functions.
package stat

import (
	"errors"
	"math"
	"math/rand"

	"kestrel/mat"
)

// RNG wraps a seeded source so every simulation is reproducible.
type RNG struct{ r *rand.Rand }

func NewRNG(seed int64) *RNG { return &RNG{rand.New(rand.NewSource(seed))} }

func (g *RNG) Float() float64               { return g.r.Float64() }
func (g *RNG) Norm() float64                { return g.r.NormFloat64() }
func (g *RNG) Uniform(a, b float64) float64 { return a + (b-a)*g.r.Float64() }
func (g *RNG) Poisson(lambda float64) int {
	// Knuth; fine for the small means used for clutter.
	l, k, p := math.Exp(-lambda), 0, 1.0
	for {
		p *= g.r.Float64()
		if p <= l {
			return k
		}
		k++
	}
}

// MVN samples N(mean, cov) as a column vector.
func (g *RNG) MVN(mean, cov *mat.M) (*mat.M, error) {
	l, err := cov.Chol()
	if err != nil {
		return nil, err
	}
	z := mat.New(mean.R, 1)
	for i := range z.D {
		z.D[i] = g.r.NormFloat64()
	}
	return mean.Add(l.Mul(z)), nil
}

// gammaP is the regularised lower incomplete gamma function P(a, x).
func gammaP(a, x float64) float64 {
	if x <= 0 {
		return 0
	}
	lg, _ := math.Lgamma(a)
	if x < a+1 { // series
		sum, term := 1/a, 1/a
		for n := 1; n < 1000; n++ {
			term *= x / (a + float64(n))
			sum += term
			if math.Abs(term) < math.Abs(sum)*1e-16 {
				break
			}
		}
		return sum * math.Exp(-x+a*math.Log(x)-lg)
	}
	// continued fraction (Lentz) for Q, then 1-Q
	const tiny = 1e-300
	b := x + 1 - a
	c := 1 / tiny
	d := 1 / b
	h := d
	for i := 1; i < 1000; i++ {
		an := -float64(i) * (float64(i) - a)
		b += 2
		d = an*d + b
		if math.Abs(d) < tiny {
			d = tiny
		}
		c = b + an/c
		if math.Abs(c) < tiny {
			c = tiny
		}
		d = 1 / d
		del := d * c
		h *= del
		if math.Abs(del-1) < 1e-16 {
			break
		}
	}
	return 1 - math.Exp(-x+a*math.Log(x)-lg)*h
}

// Chi2CDF is P(X <= x) for X ~ chi-square with k degrees of freedom.
func Chi2CDF(x float64, k int) float64 { return gammaP(float64(k)/2, x/2) }

// Chi2Quantile inverts Chi2CDF by bracketing + bisection (p in (0,1)).
func Chi2Quantile(p float64, k int) (float64, error) {
	if !(p > 0 && p < 1) || k < 1 {
		return 0, errors.New("stat: Chi2Quantile needs 0<p<1 and k>=1")
	}
	lo, hi := 0.0, float64(k)+10
	for Chi2CDF(hi, k) < p {
		hi *= 2
		if hi > 1e9 {
			return 0, errors.New("stat: quantile bracket failed")
		}
	}
	for i := 0; i < 200; i++ {
		mid := 0.5 * (lo + hi)
		if Chi2CDF(mid, k) < p {
			lo = mid
		} else {
			hi = mid
		}
	}
	return 0.5 * (lo + hi), nil
}

// WrapAngle maps an angle to (-π, π].
func WrapAngle(a float64) float64 {
	a = math.Mod(a+math.Pi, 2*math.Pi)
	if a <= 0 {
		a += 2 * math.Pi
	}
	return a - math.Pi
}
