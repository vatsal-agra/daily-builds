package smooth

import (
	"testing"

	"kestrel/mat"
)

func TestRTSErrorsAndSingleStep(t *testing.T) {
	if _, err := RTS(nil); err == nil {
		t.Error("empty must error")
	}
	if _, err := RTS([]Step{{XF: mat.Vec(1), PF: mat.Eye(1)}, {XF: mat.Vec(1), PF: mat.Eye(1)}}); err == nil {
		t.Error("missing prediction must error")
	}
	r, err := RTS([]Step{{XF: mat.Vec(3), PF: mat.Diag(2)}})
	if err != nil || r.X[0].D[0] != 3 || r.P[0].D[0] != 2 {
		t.Errorf("single step should pass through: %v %v", r, err)
	}
}

func TestRTSScalarRandomWalk(t *testing.T) {
	// x_k = x_{k-1} + w (q=1), measured with r=1. Known two-step result computed by hand:
	// filter step0: x=0,P=1.  predict: P=2.  update z=2: K=2/3, x=4/3, P=2/3.
	// smoother: C = P0·1/2 = 1/2; xs0 = 0 + C(4/3 − 0) = 2/3; Ps0 = 1 + C²(2/3 − 2) = 1 − 1/3 = 2/3.
	steps := []Step{
		{XF: mat.Vec(0), PF: mat.Diag(1)},
		{F: mat.Diag(1), XP: mat.Vec(0), PP: mat.Diag(2), XF: mat.Vec(4.0 / 3), PF: mat.Diag(2.0 / 3)},
	}
	r, err := RTS(steps)
	if err != nil {
		t.Fatal(err)
	}
	if d := r.X[0].D[0] - 2.0/3; d > 1e-12 || d < -1e-12 {
		t.Errorf("smoothed mean %v want 2/3", r.X[0].D[0])
	}
	if d := r.P[0].D[0] - 2.0/3; d > 1e-12 || d < -1e-12 {
		t.Errorf("smoothed var %v want 2/3", r.P[0].D[0])
	}
	if r.P[0].D[0] > steps[0].PF.D[0] {
		t.Error("smoothing must not increase uncertainty")
	}
}
