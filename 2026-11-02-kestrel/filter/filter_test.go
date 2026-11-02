package filter

import (
	"math"
	"testing"

	"kestrel/mat"
	"kestrel/model"
)

func TestKFMatchesScalarTextbook(t *testing.T) {
	// 1-D-ish check: with identical x/y blocks, after one update the position variance
	// must equal the textbook P·R/(P+R) when velocity is uncorrelated.
	mot := model.NewCV(0.0001, 4)
	p0 := mat.Diag(100, 1, 100, 1)
	f := NewKF(mot, mat.Vec(0, 0, 0, 0), p0)
	mm := model.NewCartesian(0, 2, 5) // R = 25
	pred, err := f.Measure(mm)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.Correct(mm, pred, mat.Vec(10, -10)); err != nil {
		t.Fatal(err)
	}
	if v := f.P().At(0, 0); math.Abs(v-100*25/125.0) > 1e-9 {
		t.Fatalf("posterior variance %v want 20", v)
	}
	if x := f.X().D[0]; math.Abs(x-8) > 1e-9 { // gain 0.8
		t.Fatalf("posterior mean %v want 8", x)
	}
}

func TestKFRejectsRadar(t *testing.T) {
	f := NewKF(model.NewCV(1, 4), mat.Vec(1, 1, 1, 1), mat.Eye(4))
	if _, err := f.Measure(model.NewRadar(0, 2, 0, 0, 1, 0.01)); err == nil {
		t.Fatal("KF must refuse a nonlinear measurement model")
	}
}

func TestCovarianceStaysSymmetricPSD(t *testing.T) {
	mot := model.NewCV(0.5, 4)
	rad := model.NewRadar(0, 2, 0, 0, 25, 0.007)
	for _, f := range []Filter{NewEKF(mot, mat.Vec(5000, 100, 7000, -50), mat.Diag(3600, 1e4, 3600, 1e4)), NewUKF(mot, mat.Vec(5000, 100, 7000, -50), mat.Diag(3600, 1e4, 3600, 1e4))} {
		for k := 0; k < 100; k++ {
			if err := f.Predict(2); err != nil {
				t.Fatal(err)
			}
			p, err := f.Measure(rad)
			if err != nil {
				t.Fatal(err)
			}
			truth := mat.Vec(5000+100*2*float64(k+1), 100, 7000-50*2*float64(k+1), -50)
			if _, err := f.Correct(rad, p, rad.H(truth)); err != nil {
				t.Fatal(err)
			}
			P := f.P()
			for i := 0; i < 4; i++ {
				for j := 0; j < 4; j++ {
					if math.Abs(P.At(i, j)-P.At(j, i)) > 1e-9*math.Max(1, math.Abs(P.At(i, j))) {
						t.Fatalf("%s: P asymmetric at step %d", f.Name(), k)
					}
				}
			}
			if _, err := P.Add(mat.Eye(4).Scale(1e-9)).Chol(); err != nil {
				t.Fatalf("%s: P lost positive-definiteness at step %d", f.Name(), k)
			}
		}
	}
}

func TestEKFandUKFAgreeOnMildNonlinearity(t *testing.T) {
	mot := model.NewCV(0.5, 4)
	rad := model.NewRadar(0, 2, 0, 0, 25, 0.004)
	x0, p0 := mat.Vec(9000, 100, 6000, -50), mat.Diag(2500, 100, 2500, 100)
	e, u := NewEKF(mot, x0, p0), NewUKF(mot, x0, p0)
	z := rad.H(mat.Vec(9020, 0, 6010, 0))
	for _, f := range []Filter{e, u} {
		f.Predict(2)
		p, _ := f.Measure(rad)
		f.Correct(rad, p, z)
	}
	for i := 0; i < 4; i++ {
		if math.Abs(e.X().D[i]-u.X().D[i]) > 0.5 {
			t.Errorf("state %d: EKF %v UKF %v", i, e.X().D[i], u.X().D[i])
		}
	}
}

func TestUKFHandlesBearingWrapMean(t *testing.T) {
	// target just across the ±π cut: predicted bearing must not average to ~0
	rad := model.NewRadar(0, 2, 0, 0, 25, 0.01)
	f := NewUKF(model.NewCV(0.5, 4), mat.Vec(-5000, 0, 0, 0), mat.Diag(10000, 1, 10000, 1))
	p, err := f.Measure(rad)
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(math.Abs(p.Z.D[1])-math.Pi) > 0.05 {
		t.Fatalf("predicted bearing %v should be near ±π", p.Z.D[1])
	}
}

func TestIMMValidationAndProbabilities(t *testing.T) {
	cv, ct := model.NewCV(0.5, 5), model.NewCT(1, 1e-4)
	x0, p0 := mat.Vec(1000, 100, 1000, 0, 0), mat.Diag(100, 25, 100, 25, 0.0025)
	mk := func() []Filter { return []Filter{NewEKF(cv, x0, p0), NewEKF(ct, x0, p0)} }
	good := [][]float64{{0.9, 0.1}, {0.1, 0.9}}
	if _, err := NewIMM(mk(), []float64{0.5, 0.4}, good); err == nil {
		t.Error("probabilities not summing to 1 must be rejected")
	}
	if _, err := NewIMM(mk(), []float64{0.5, 0.5}, [][]float64{{0.9, 0.2}, {0.1, 0.9}}); err == nil {
		t.Error("bad transition row must be rejected")
	}
	if _, err := NewIMM(mk()[:1], []float64{1}, [][]float64{{1}}); err == nil {
		t.Error("single mode must be rejected")
	}
	im, err := NewIMM(mk(), []float64{0.5, 0.5}, good)
	if err != nil {
		t.Fatal(err)
	}
	// feed a target turning at 3°/s: CT probability must rise well above CV
	truth := mat.Vec(1000, 100, 1000, 0, 0.0524)
	rad := model.NewRadar(0, 2, 0, 0, 10, 0.002)
	for k := 0; k < 25; k++ {
		truth = ct.Step(truth, 2)
		im.Predict(2)
		p, _ := im.Measure(rad)
		if _, err := im.Correct(rad, p, rad.H(truth)); err != nil {
			t.Fatal(err)
		}
	}
	pr := im.Probs()
	sum := pr[0] + pr[1]
	if math.Abs(sum-1) > 1e-9 || pr[1] < 0.8 {
		t.Fatalf("mode probs %v: CT should dominate during a turn", pr)
	}
}
