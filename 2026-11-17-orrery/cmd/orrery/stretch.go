package main

import (
	"fmt"
	"io"
	"math"

	"orrery/orrery"
)

func cmdOrder(o *opts, w io.Writer) error {
	var s *orrery.System
	var err error
	if len(o.args) == 0 {
		// default: a Sun-planet pair, mass ratio 1e-3, e = 0.3 (WH-friendly)
		s = &orrery.System{Title: "Kepler problem (m/M = 1e-3, e = 0.3)", G: 1,
			Bodies: []orrery.Body{{Name: "star", M: 1}, {Name: "planet", M: 1e-3}}}
		r, v, _ := orrery.StateFromElements(orrery.Elements{A: 1, E: 0.3}, 1.001)
		s.Bodies[1].Pos, s.Bodies[1].Vel = r, v
		s.ToBarycentric()
	} else if s, err = load(o); err != nil {
		return err
	}
	steps := []int{100, 200, 400, 800, 1600}
	fmt.Fprintf(w, "%s — 1.37 periods, error = |(r,v)_numeric - (r,v)_Kepler|\n", titleOf(s))
	fmt.Fprintf(w, "%-9s %5s %8s   %s\n", "method", "nom.", "observed", "error at "+fmt.Sprint(steps)+" steps/period")
	methods := orrery.Methods()
	if o.methodSet {
		m, err := orrery.ParseMethod(o.method)
		if err != nil {
			return err
		}
		methods = []orrery.Method{m}
	}
	for _, m := range methods {
		if m == orrery.DOPRI5 {
			continue
		}
		st, err := orrery.MeasureOrder(s, m, steps)
		if err != nil {
			fmt.Fprintf(w, "%-9s %v\n", m, err)
			continue
		}
		fmt.Fprintf(w, "%-9s %5d %8.2f  ", m, m.Order(), st.Observed)
		for _, p := range st.Points {
			fmt.Fprintf(w, " %9.2e", p.Err)
		}
		if d := st.Observed - float64(m.Order()); d < -0.3 || d > 0.3 {
			fmt.Fprint(w, "  (pre-asymptotic: errors still O(1); finer steps approach nominal)")
		}
		fmt.Fprintln(w)
	}
	return nil
}

func cmdReverse(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s — forward T=%g then backward T=%g, dt=%g\n", titleOf(s), o.T, o.T, o.dt)
	fmt.Fprintf(w, "%-9s %14s %14s   verdict\n", "method", "max |dx|", "max |dv|")
	for _, m := range orrery.Methods() {
		if m == orrery.DOPRI5 {
			continue // adaptive step choice is path dependent; not a fixed map
		}
		r, err := orrery.ReverseTest(s, m, o.dt, o.T)
		if err != nil {
			fmt.Fprintf(w, "%-9s %v\n", m, err)
			continue
		}
		verdict := "irreversible"
		switch {
		case math.IsNaN(r.RelPosErr):
			verdict = "diverged"
		case r.RelPosErr < 1e-8:
			verdict = "reversible (round-off only)"
		case r.RelPosErr < 1e-3:
			verdict = "nearly reversible"
		}
		fmt.Fprintf(w, "%-9s %14.3e %14.3e   %s\n", m, r.PosErr, r.VelErr, verdict)
	}
	return nil
}

func cmdLyap(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	m, err := orrery.ParseMethod(o.method)
	if err != nil {
		return err
	}
	r, err := orrery.Lyapunov(s, m, o.dt, o.T, o.seed)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s — Benettin shadow-orbit estimate with %s, dt=%g, T=%g\n", titleOf(s), m, o.dt, o.T)
	fmt.Fprintf(w, "%10s %12s\n", "t", "lambda(t)")
	step := len(r.Series) / o.samples
	if step < 1 {
		step = 1
	}
	for i := step - 1; i < len(r.Series); i += step {
		fmt.Fprintf(w, "%10.3f %12.5f\n", r.Series[i].T, r.Series[i].Lambda)
	}
	fmt.Fprintf(w, "mean growth rate %.5g (whole run), %.5g (second half = %.1f e-folds), trend %.2f, %d renormalisations\n", r.Lambda, r.LambdaLate, r.EFolds, r.Trend, r.Renorms)
	switch r.Verdict {
	case "chaotic":
		fmt.Fprintf(w, "CHAOTIC: separation grows exponentially. λ ≈ %.4g, Lyapunov time ≈ %.4g (orbits diverge by e every %.4g time units).\n", r.LambdaLate, 1/r.LambdaLate, 1/r.LambdaLate)
	case "transient":
		fmt.Fprintf(w, "TRANSIENT CHAOS: exponential divergence early on (mean rate %.3g over the run) that stops once the system settles (e.g. a binary plus an escaper).\n", r.Lambda)
	case "regular":
		fmt.Fprintln(w, "REGULAR: only a few e-folds of growth, slowing like ln(t) — no exponential divergence in this window.")
	default:
		fmt.Fprintln(w, "INCONCLUSIVE: too few e-folds to call it exponential, too many for pure shear; integrate longer (-T).")
	}
	return nil
}
