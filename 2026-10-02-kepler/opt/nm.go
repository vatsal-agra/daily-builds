// Package opt contains the derivative-free optimiser used to tune the numeric
// constants embedded in candidate expressions.
package opt

import (
	"math"
	"sort"
)

// NelderMead minimises f starting from x0 with initial step sizes derived from
// x0. It returns the best point and value. maxEval bounds function calls.
func NelderMead(f func([]float64) float64, x0 []float64, maxEval int) ([]float64, float64) {
	n := len(x0)
	if n == 0 {
		return nil, f(nil)
	}
	type vert struct {
		x []float64
		v float64
	}
	evals := 0
	eval := func(x []float64) float64 {
		evals++
		v := f(x)
		if math.IsNaN(v) {
			return math.Inf(1)
		}
		return v
	}
	sim := make([]vert, n+1)
	sim[0] = vert{append([]float64{}, x0...), eval(x0)}
	for i := 0; i < n; i++ {
		x := append([]float64{}, x0...)
		step := 0.25 * math.Abs(x[i])
		if step < 0.1 {
			step = 0.1
		}
		x[i] += step
		sim[i+1] = vert{x, eval(x)}
	}
	for evals < maxEval {
		sort.Slice(sim, func(a, b int) bool { return sim[a].v < sim[b].v })
		best, worst := sim[0], sim[n]
		if math.Abs(worst.v-best.v) <= 1e-14*(1+math.Abs(best.v)) {
			break
		}
		cen := make([]float64, n)
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				cen[j] += sim[i].x[j] / float64(n)
			}
		}
		pt := func(t float64) []float64 {
			p := make([]float64, n)
			for j := range p {
				p[j] = cen[j] + t*(worst.x[j]-cen[j])
			}
			return p
		}
		xr := pt(-1)
		vr := eval(xr)
		switch {
		case vr < best.v:
			xe := pt(-2)
			if ve := eval(xe); ve < vr {
				sim[n] = vert{xe, ve}
			} else {
				sim[n] = vert{xr, vr}
			}
		case vr < sim[n-1].v:
			sim[n] = vert{xr, vr}
		default:
			var xc []float64
			if vr < worst.v {
				xc = pt(-0.5)
			} else {
				xc = pt(0.5)
			}
			if vc := eval(xc); vc < math.Min(vr, worst.v) {
				sim[n] = vert{xc, vc}
			} else { // shrink
				for i := 1; i <= n; i++ {
					for j := 0; j < n; j++ {
						sim[i].x[j] = best.x[j] + 0.5*(sim[i].x[j]-best.x[j])
					}
					sim[i].v = eval(sim[i].x)
				}
			}
		}
	}
	sort.Slice(sim, func(a, b int) bool { return sim[a].v < sim[b].v })
	return sim[0].x, sim[0].v
}
