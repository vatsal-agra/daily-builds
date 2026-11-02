// Package filter implements the Kalman filter family behind one interface.
package filter

import (
	"fmt"
	"math"

	"kestrel/mat"
	"kestrel/model"
)

// Pred is what a filter predicts a measurement will look like.
type Pred struct {
	Z   *mat.M // predicted measurement
	S   *mat.M // innovation covariance
	Pxz *mat.M // state/measurement cross covariance
	H   *mat.M // measurement Jacobian (nil for the UKF)
	Sub []Pred // per-mode predictions (IMM only)
}

// Result is the outcome of one measurement update.
type Result struct {
	Innov  *mat.M  // z − ẑ
	S      *mat.M  // innovation covariance
	NIS    float64 // normalised innovation squared yᵀS⁻¹y
	LogLik float64 // log N(y; 0, S)
}

// Filter is a recursive estimator over a Gaussian state.
type Filter interface {
	Name() string
	X() *mat.M
	P() *mat.M
	Predict(dt float64) error
	// Measure predicts the measurement without altering the state (used for gating).
	Measure(mm model.Meas) (Pred, error)
	// Correct performs the update with z using a prediction from Measure.
	Correct(mm model.Meas, p Pred, z *mat.M) (Result, error)
	Clone() Filter
	// SetState overwrites the estimate (used by IMM mixing).
	SetState(x, p *mat.M)
}

// Gaussian log-density of residual y with covariance S, and the Mahalanobis² distance.
func Mahalanobis(y, S *mat.M) (d2, logLik float64, err error) {
	sy, err := S.Solve(y)
	if err != nil {
		return 0, 0, err
	}
	for i := range y.D {
		d2 += y.D[i] * sy.D[i]
	}
	ld, err := S.Sym().LogDetSPD()
	if err != nil {
		return 0, 0, fmt.Errorf("innovation covariance not positive definite: %w", err)
	}
	return d2, -0.5 * (d2 + ld + float64(y.R)*math.Log(2*math.Pi)), nil
}

// base holds the state shared by KF / EKF / UKF.
type base struct {
	x, p *mat.M
	mot  model.Motion
}

func (b *base) X() *mat.M            { return b.x }
func (b *base) P() *mat.M            { return b.p }
func (b *base) SetState(x, p *mat.M) { b.x, b.p = x.Clone(), p.Clone() }

func checkInit(x, p *mat.M, mot model.Motion) {
	if x.R != mot.Dim() || x.C != 1 || p.R != mot.Dim() || p.C != mot.Dim() {
		panic(fmt.Sprintf("filter: state/cov shape does not match %s (dim %d)", mot.Name(), mot.Dim()))
	}
}

// ----------------------------------------------------------------- KF

// KF is the linear Kalman filter: linear motion and linear measurements only.
type KF struct{ base }

func NewKF(mot model.Linear, x0, p0 *mat.M) *KF {
	checkInit(x0, p0, mot)
	return &KF{base{x0.Clone(), p0.Clone(), mot}}
}
func (f *KF) Name() string  { return "KF" }
func (f *KF) Clone() Filter { return &KF{base{f.x.Clone(), f.p.Clone(), f.mot}} }
func (f *KF) Predict(dt float64) error {
	lin := f.mot.(model.Linear)
	F := lin.F(dt)
	f.x = F.Mul(f.x)
	f.p = F.Mul(f.p).Mul(F.T()).Add(f.mot.Q(f.x, dt)).Sym()
	return nil
}
func (f *KF) Measure(mm model.Meas) (Pred, error) {
	lm, ok := mm.(model.LinearMeas)
	if !ok {
		return Pred{}, fmt.Errorf("KF needs a linear measurement model, got %s (use EKF or UKF)", mm.Name())
	}
	return linearPred(f.x, f.p, lm.HMat(f.x.R), mm)
}
func (f *KF) Correct(mm model.Meas, p Pred, z *mat.M) (Result, error) {
	return jacobianCorrect(&f.base, mm, p, z)
}

func linearPred(x, p, H *mat.M, mm model.Meas) (Pred, error) {
	pht := p.Mul(H.T())
	s := H.Mul(pht).Add(mm.R()).Sym()
	return Pred{Z: mm.H(x), S: s, Pxz: pht, H: H}, nil
}

// jacobianCorrect is the shared KF/EKF update (Joseph-form covariance).
func jacobianCorrect(b *base, mm model.Meas, p Pred, z *mat.M) (Result, error) {
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
	b.x = b.x.Add(k.Mul(y))
	ikh := mat.Eye(b.x.R).Sub(k.Mul(p.H))
	b.p = ikh.Mul(b.p).Mul(ikh.T()).Add(k.Mul(mm.R()).Mul(k.T())).Sym()
	return Result{Innov: y, S: p.S, NIS: d2, LogLik: ll}, nil
}

// ----------------------------------------------------------------- EKF

// EKF linearises both the motion and the measurement models at the current estimate.
type EKF struct{ base }

func NewEKF(mot model.Motion, x0, p0 *mat.M) *EKF {
	checkInit(x0, p0, mot)
	return &EKF{base{x0.Clone(), p0.Clone(), mot}}
}
func (f *EKF) Name() string  { return "EKF" }
func (f *EKF) Clone() Filter { return &EKF{base{f.x.Clone(), f.p.Clone(), f.mot}} }
func (f *EKF) Predict(dt float64) error {
	J := f.mot.Jac(f.x, dt)
	f.p = J.Mul(f.p).Mul(J.T()).Add(f.mot.Q(f.x, dt)).Sym()
	f.x = f.mot.Step(f.x, dt)
	return nil
}
func (f *EKF) Measure(mm model.Meas) (Pred, error) {
	return linearPred(f.x, f.p, mm.Jac(f.x), mm)
}
func (f *EKF) Correct(mm model.Meas, p Pred, z *mat.M) (Result, error) {
	return jacobianCorrect(&f.base, mm, p, z)
}
