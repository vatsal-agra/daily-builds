package gp

import (
	"math"

	"kepler/data"
	"kepler/expr"
	"kepler/opt"
)

// Problem caches what fitness needs about a dataset.
type Problem struct {
	X     [][]float64
	Y     []float64
	denom float64 // sum (y - mean)^2
}

// NewProblem prepares a dataset for scoring.
func NewProblem(d *data.Dataset) *Problem {
	p := &Problem{X: d.X, Y: d.Y}
	var m float64
	for _, y := range d.Y {
		m += y
	}
	m /= float64(len(d.Y))
	for _, y := range d.Y {
		p.denom += (y - m) * (y - m)
	}
	if p.denom == 0 {
		p.denom = 1 // constant target: fall back to raw SSE
	}
	return p
}

// NMSE is the normalised mean squared error: 0 = perfect, 1 = as good as the
// mean, >1 worse. Any non-finite prediction makes the expression invalid (+Inf).
func (p *Problem) NMSE(n *expr.Node) float64 {
	var sse float64
	for i, x := range p.X {
		d := n.Eval(x) - p.Y[i]
		sse += d * d
		if math.IsNaN(sse) || math.IsInf(sse, 0) {
			return math.Inf(1)
		}
	}
	return sse / p.denom
}

// R2 = 1 - NMSE.
func (p *Problem) R2(n *expr.Node) float64 { return 1 - p.NMSE(n) }

// FitConstants tunes every numeric leaf of n in place with Nelder-Mead
// (restarting from the best point a few times) and returns the final NMSE.
func (p *Problem) FitConstants(n *expr.Node, maxEval int, restarts int) float64 {
	cs := n.Consts()
	if len(cs) == 0 {
		return p.NMSE(n)
	}
	x0 := make([]float64, len(cs))
	for i, c := range cs {
		x0[i] = c.Val
	}
	f := func(v []float64) float64 {
		for i, c := range cs {
			c.Val = v[i]
		}
		return p.NMSE(n)
	}
	best, bv := opt.NelderMead(f, x0, maxEval)
	for r := 0; r < restarts; r++ {
		nx, nv := opt.NelderMead(f, best, maxEval)
		if nv < bv {
			best, bv = nx, nv
		} else {
			break
		}
	}
	for i, c := range cs {
		c.Val = best[i]
	}
	return p.NMSE(n)
}

// Snap rounds each constant to a "nice" value (integers, halves, quarters,
// tenths/hundredths, pi multiples) whenever doing so keeps the error within
// tol relative to its current value (or below an absolute floor). It makes
// discovered laws readable: 1.50003 -> 1.5.
func (p *Problem) Snap(n *expr.Node, relTol float64) float64 {
	cur := p.NMSE(n)
	for _, c := range n.Consts() {
		orig := c.Val
		for _, cand := range niceCandidates(orig) {
			if cand == orig {
				continue
			}
			c.Val = cand
			if e := p.NMSE(n); e <= cur*(1+relTol)+1e-13 {
				cur = e
				orig = cand
				break
			}
		}
		c.Val = orig
	}
	return p.NMSE(n)
}

func niceCandidates(v float64) []float64 {
	var out []float64
	add := func(c float64) {
		if !math.IsNaN(c) && !math.IsInf(c, 0) {
			out = append(out, c)
		}
	}
	for _, q := range []float64{1, 2, 4, 10, 100} {
		add(math.Round(v*q) / q)
	}
	for _, m := range []float64{math.Pi, 2 * math.Pi, math.Pi / 2, math.E} {
		if r := math.Round(v/m*2) / 2; r != 0 {
			add(r * m)
		}
	}
	// 3 significant digits
	if v != 0 {
		mag := math.Pow(10, math.Floor(math.Log10(math.Abs(v)))-2)
		add(math.Round(v/mag) * mag)
	}
	// order: simplest first = the order added except sig-digit; keep only close ones
	var near []float64
	for _, c := range out {
		if math.Abs(c-v) <= 0.05*math.Abs(v)+1e-9 {
			near = append(near, c)
		}
	}
	return near
}

// Prune greedily replaces subtrees by a child, 0 or 1 whenever that lowers
// complexity without raising error by more than relTol (plus a float-noise
// floor), refitting constants after each accepted change. It removes
// vestigial terms such as "+ 4.6e-07" from a fitted model.
func (p *Problem) Prune(n *expr.Node, relTol float64) *expr.Node {
	cur := p.NMSE(n)
	for pass := 0; pass < 12; pass++ {
		improved := false
		ns := n.Nodes()
		for idx := 1; idx < len(ns) && !improved; idx++ {
			sub := ns[idx]
			cands := []*expr.Node{expr.C(0), expr.C(1)}
			if sub.L != nil {
				cands = append(cands, sub.L.Clone())
			}
			if sub.R != nil {
				cands = append(cands, sub.R.Clone())
			}
			for _, c := range cands {
				t := expr.Simplify(replaceAt(n, idx, c))
				if t.Complexity() >= n.Complexity() {
					continue
				}
				e := p.FitConstants(t, 150, 1)
				if !math.IsInf(e, 0) && e <= cur*(1+relTol)+1e-13 {
					n, cur, improved = t, math.Min(cur, e), true
					break
				}
			}
		}
		if !improved {
			break
		}
	}
	return n
}
