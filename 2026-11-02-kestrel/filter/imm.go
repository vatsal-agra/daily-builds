package filter

import (
	"fmt"
	"math"

	"kestrel/mat"
	"kestrel/model"
)

// IMM is the Interacting Multiple Model estimator (Blom & Bar-Shalom): a bank of filters
// for different motion hypotheses, mixed each scan by a Markov model-switching matrix, with
// model probabilities updated from each filter's measurement likelihood.
type IMM struct {
	modes []Filter
	mu    []float64   // current mode probabilities
	pi    [][]float64 // pi[i][j] = P(next mode j | current mode i)
	x, p  *mat.M      // moment-matched output
}

// NewIMM builds an IMM from filters that share a state space. pi rows must sum to 1.
func NewIMM(modes []Filter, mu0 []float64, pi [][]float64) (*IMM, error) {
	n := len(modes)
	if n < 2 || len(mu0) != n || len(pi) != n {
		return nil, fmt.Errorf("IMM: need >=2 modes with matching probability/transition sizes")
	}
	sum := 0.0
	for _, v := range mu0 {
		if v < 0 {
			return nil, fmt.Errorf("IMM: negative mode probability")
		}
		sum += v
	}
	if math.Abs(sum-1) > 1e-9 {
		return nil, fmt.Errorf("IMM: initial mode probabilities sum to %v, want 1", sum)
	}
	for i, row := range pi {
		if len(row) != n {
			return nil, fmt.Errorf("IMM: transition matrix must be %dx%d", n, n)
		}
		s := 0.0
		for _, v := range row {
			if v < 0 {
				return nil, fmt.Errorf("IMM: negative transition probability")
			}
			s += v
		}
		if math.Abs(s-1) > 1e-9 {
			return nil, fmt.Errorf("IMM: transition row %d sums to %v, want 1", i, s)
		}
	}
	for _, m := range modes[1:] {
		if m.X().R != modes[0].X().R {
			return nil, fmt.Errorf("IMM: modes must share one state dimension")
		}
	}
	im := &IMM{modes: modes, mu: append([]float64(nil), mu0...), pi: pi}
	im.combine()
	return im, nil
}

func (m *IMM) Name() string     { return "IMM" }
func (m *IMM) X() *mat.M        { return m.x }
func (m *IMM) P() *mat.M        { return m.p }
func (m *IMM) Probs() []float64 { return append([]float64(nil), m.mu...) }
func (m *IMM) Clone() Filter {
	c := &IMM{mu: append([]float64(nil), m.mu...), pi: m.pi, x: m.x.Clone(), p: m.p.Clone()}
	for _, f := range m.modes {
		c.modes = append(c.modes, f.Clone())
	}
	return c
}
func (m *IMM) SetState(x, p *mat.M) {
	for _, f := range m.modes {
		f.SetState(x, p)
	}
	m.combine()
}

// combine moment-matches the mode estimates into one Gaussian.
func (m *IMM) combine() {
	n := m.modes[0].X().R
	x := mat.New(n, 1)
	for j, f := range m.modes {
		x = x.Add(f.X().Scale(m.mu[j]))
	}
	p := mat.New(n, n)
	for j, f := range m.modes {
		d := f.X().Sub(x)
		p = p.Add(f.P().Add(d.Mul(d.T())).Scale(m.mu[j]))
	}
	m.x, m.p = x, p.Sym()
}

func (m *IMM) Predict(dt float64) error {
	n := len(m.modes)
	dim := m.modes[0].X().R
	c := make([]float64, n)
	for j := 0; j < n; j++ {
		for i := 0; i < n; i++ {
			c[j] += m.pi[i][j] * m.mu[i]
		}
	}
	xs := make([]*mat.M, n)
	ps := make([]*mat.M, n)
	for i, f := range m.modes {
		xs[i], ps[i] = f.X().Clone(), f.P().Clone()
	}
	for j := 0; j < n; j++ {
		x0 := mat.New(dim, 1)
		w := make([]float64, n)
		for i := 0; i < n; i++ {
			if c[j] > 0 {
				w[i] = m.pi[i][j] * m.mu[i] / c[j]
			}
			x0 = x0.Add(xs[i].Scale(w[i]))
		}
		p0 := mat.New(dim, dim)
		for i := 0; i < n; i++ {
			d := xs[i].Sub(x0)
			p0 = p0.Add(ps[i].Add(d.Mul(d.T())).Scale(w[i]))
		}
		m.modes[j].SetState(x0, p0.Sym())
	}
	for j, f := range m.modes {
		if err := f.Predict(dt); err != nil {
			return fmt.Errorf("IMM mode %d: %w", j, err)
		}
		m.mu[j] = c[j]
	}
	m.combine()
	return nil
}

func (m *IMM) Measure(mm model.Meas) (Pred, error) {
	subs := make([]Pred, len(m.modes))
	for j, f := range m.modes {
		p, err := f.Measure(mm)
		if err != nil {
			return Pred{}, err
		}
		subs[j] = p
	}
	z0 := subs[0].Z
	acc := mat.New(z0.R, 1)
	for j, s := range subs {
		acc = acc.Add(mm.Resid(s.Z, z0).Scale(m.mu[j]))
	}
	zbar := z0.Add(acc)
	S := mat.New(z0.R, z0.R)
	Pxz := mat.New(m.x.R, z0.R)
	for j, s := range subs {
		dz := mm.Resid(s.Z, zbar)
		dx := m.modes[j].X().Sub(m.x)
		S = S.Add(s.S.Add(dz.Mul(dz.T())).Scale(m.mu[j]))
		Pxz = Pxz.Add(s.Pxz.Add(dx.Mul(dz.T())).Scale(m.mu[j]))
	}
	return Pred{Z: zbar, S: S.Sym(), Pxz: Pxz, Sub: subs}, nil
}

func (m *IMM) Correct(mm model.Meas, p Pred, z *mat.M) (Result, error) {
	if len(p.Sub) != len(m.modes) {
		return Result{}, fmt.Errorf("IMM: prediction was not produced by this IMM")
	}
	lls := make([]float64, len(m.modes))
	maxLL := math.Inf(-1)
	for j, f := range m.modes {
		r, err := f.Correct(mm, p.Sub[j], z)
		if err != nil {
			return Result{}, fmt.Errorf("IMM mode %d: %w", j, err)
		}
		lls[j] = r.LogLik
		maxLL = math.Max(maxLL, r.LogLik)
	}
	// posterior mode probabilities, computed in the log domain
	norm := 0.0
	for j := range m.mu {
		m.mu[j] *= math.Exp(lls[j] - maxLL)
		norm += m.mu[j]
	}
	if norm <= 0 || math.IsNaN(norm) {
		return Result{}, fmt.Errorf("IMM: all modes have zero likelihood")
	}
	for j := range m.mu {
		m.mu[j] = math.Max(m.mu[j]/norm, 1e-6) // floor keeps a mode from becoming unrecoverable
	}
	s := 0.0
	for _, v := range m.mu {
		s += v
	}
	for j := range m.mu {
		m.mu[j] /= s
	}
	m.combine()
	y := mm.Resid(z, p.Z)
	d2, _, err := Mahalanobis(y, p.S)
	if err != nil {
		return Result{}, err
	}
	return Result{Innov: y, S: p.S, NIS: d2, LogLik: maxLL + math.Log(norm)}, nil
}
