package codec

import "math"

// rateCtl chooses a QP per frame. With Bitrate == 0 it is a constant-QP
// controller (I: QP-2, P: QP, B: QP+2). With a bitrate target it keeps a
// per-type model "bits * qstep = complexity" and spends the *remaining* bit
// budget in proportion to the remaining frame weights, so overshoot early
// automatically tightens later frames.
type rateCtl struct {
	p         EncParams
	total     float64 // total bit budget
	spent     float64
	remW      float64 // remaining weight
	cx        [3]float64
	lastQP    [3]int
	seen      [3]bool
	wt        [3]float64
	targetCur float64
}

func newRateCtl(p EncParams, v *Video, jobs []job) *rateCtl {
	r := &rateCtl{p: p, wt: [3]float64{4, 1, 0.55}}
	if p.Bitrate > 0 {
		r.total = float64(p.Bitrate) * 1000 * float64(len(v.Frames)) / v.FPS()
		for _, j := range jobs {
			r.remW += r.wt[j.typ]
		}
	}
	return r
}

func (r *rateCtl) fixedQP(typ int) int {
	d := [3]int{-2, 0, 2}[typ]
	return clampi(r.p.QP+d, MinQP, MaxQP)
}

func (r *rateCtl) target(typ int) float64 {
	t := (r.total - r.spent) * r.wt[typ] / r.remW
	if t < 200 {
		t = 200
	}
	r.targetCur = t
	return t
}

func (r *rateCtl) qpFor(typ int) int {
	if r.p.Bitrate == 0 {
		return r.fixedQP(typ)
	}
	t := r.target(typ)
	var x float64
	switch {
	case r.seen[typ]:
		x = r.cx[typ]
	case r.seen[FrameI]:
		x = r.cx[FrameI] * r.wt[typ] / r.wt[FrameI]
	case r.seen[FrameP]:
		x = r.cx[FrameP] * r.wt[typ] / r.wt[FrameP]
	default:
		return clampi(int(30-8*math.Log2(t/60000+1e-9)/1), 10, 45)
	}
	qs := x / t
	qp := int(math.Round(4 + 6*math.Log2(qs)))
	if r.seen[typ] { // limit swings between same-type frames
		qp = clampi(qp, r.lastQP[typ]-4, r.lastQP[typ]+4)
	}
	return clampi(qp, MinQP, MaxQP)
}

// retry lets the first frame of a type be re-encoded when the guess was far off.
func (r *rateCtl) retry(typ, qp, bits, attempt int) (int, bool) {
	if r.p.Bitrate == 0 || attempt >= 2 || r.seen[typ] || typ == FrameB {
		return 0, false
	}
	ratio := float64(bits) / r.targetCur
	if ratio > 0.7 && ratio < 1.4 {
		return 0, false
	}
	nq := clampi(qp+int(math.Round(6*math.Log2(ratio))), MinQP, MaxQP)
	if nq == qp {
		return 0, false
	}
	return nq, true
}

func (r *rateCtl) update(typ, qp, bits int) {
	if r.p.Bitrate == 0 {
		return
	}
	obs := float64(bits) * Qstep(qp)
	if r.seen[typ] {
		r.cx[typ] = 0.5*r.cx[typ] + 0.5*obs
	} else {
		r.cx[typ] = obs
	}
	r.seen[typ] = true
	r.lastQP[typ] = qp
	r.spent += float64(bits)
	r.remW -= r.wt[typ]
}
