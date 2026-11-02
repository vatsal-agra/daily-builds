package filter

import (
	"fmt"
	"math"

	"kestrel/mat"
	"kestrel/model"
)

// UKF is the scaled unscented Kalman filter (Wan & van der Merwe): no Jacobians,
// 2n+1 sigma points pushed through the true nonlinear functions.
type UKF struct {
	base
	alpha, beta, kappa float64
}

func NewUKF(mot model.Motion, x0, p0 *mat.M) *UKF {
	checkInit(x0, p0, mot)
	return &UKF{base{x0.Clone(), p0.Clone(), mot}, 0.5, 2, 0}
}
func (f *UKF) Name() string { return "UKF" }
func (f *UKF) Clone() Filter {
	c := *f
	c.x, c.p = f.x.Clone(), f.p.Clone()
	return &c
}

func (f *UKF) weights(n int) (lambda float64, wm, wc []float64) {
	nf := float64(n)
	lambda = f.alpha*f.alpha*(nf+f.kappa) - nf
	wm = make([]float64, 2*n+1)
	wc = make([]float64, 2*n+1)
	wm[0] = lambda / (nf + lambda)
	wc[0] = wm[0] + (1 - f.alpha*f.alpha + f.beta)
	for i := 1; i <= 2*n; i++ {
		wm[i] = 1 / (2 * (nf + lambda))
		wc[i] = wm[i]
	}
	return
}

// sigma returns the 2n+1 sigma points of N(x, p). If p is only positive
// semi-definite (pinned states), a tiny jitter lets Cholesky succeed.
func sigma(x, p *mat.M, lambda float64) ([]*mat.M, error) {
	n := x.R
	scaled := p.Scale(float64(n) + lambda).Sym()
	l, err := scaled.Chol()
	if err != nil {
		jit := scaled.Clone()
		for i := 0; i < n; i++ {
			jit.D[i*n+i] += 1e-12 + 1e-9*math.Abs(scaled.D[i*n+i])
		}
		if l, err = jit.Chol(); err != nil {
			return nil, fmt.Errorf("UKF sigma points: %w", err)
		}
	}
	pts := make([]*mat.M, 2*n+1)
	pts[0] = x.Clone()
	for i := 0; i < n; i++ {
		col := mat.Vec(l.Col(i)...)
		pts[1+i] = x.Add(col)
		pts[1+n+i] = x.Sub(col)
	}
	return pts, nil
}

func (f *UKF) Predict(dt float64) error {
	n := f.x.R
	lambda, wm, wc := f.weights(n)
	pts, err := sigma(f.x, f.p, lambda)
	if err != nil {
		return err
	}
	for i := range pts {
		pts[i] = f.mot.Step(pts[i], dt)
	}
	mean := mat.New(n, 1)
	for i, p := range pts {
		mean = mean.Add(p.Scale(wm[i]))
	}
	cov := f.mot.Q(f.x, dt)
	for i, p := range pts {
		d := p.Sub(mean)
		cov = cov.Add(d.Mul(d.T()).Scale(wc[i]))
	}
	f.x, f.p = mean, cov.Sym()
	return nil
}

func (f *UKF) Measure(mm model.Meas) (Pred, error) {
	n := f.x.R
	lambda, wm, wc := f.weights(n)
	pts, err := sigma(f.x, f.p, lambda)
	if err != nil {
		return Pred{}, err
	}
	zs := make([]*mat.M, len(pts))
	for i, p := range pts {
		zs[i] = mm.H(p)
	}
	// Mean in a way that is safe for circular components: offset from zs[0] by wrapped residuals.
	zbar := zs[0].Clone()
	acc := mat.New(zbar.R, 1)
	for i, z := range zs {
		acc = acc.Add(mm.Resid(z, zs[0]).Scale(wm[i]))
	}
	zbar = zbar.Add(acc)
	s := mm.R()
	pxz := mat.New(n, zbar.R)
	for i := range zs {
		dz := mm.Resid(zs[i], zbar)
		dx := pts[i].Sub(f.x)
		s = s.Add(dz.Mul(dz.T()).Scale(wc[i]))
		pxz = pxz.Add(dx.Mul(dz.T()).Scale(wc[i]))
	}
	return Pred{Z: zbar, S: s.Sym(), Pxz: pxz}, nil
}

func (f *UKF) Correct(mm model.Meas, p Pred, z *mat.M) (Result, error) {
	y := mm.Resid(z, p.Z)
	sinv, err := p.S.Inv()
	if err != nil {
		return Result{}, err
	}
	d2, ll, err := Mahalanobis(y, p.S)
	if err != nil {
		return Result{}, err
	}
	k := p.Pxz.Mul(sinv)
	f.x = f.x.Add(k.Mul(y))
	f.p = f.p.Sub(k.Mul(p.S).Mul(k.T())).Sym()
	return Result{Innov: y, S: p.S, NIS: d2, LogLik: ll}, nil
}
