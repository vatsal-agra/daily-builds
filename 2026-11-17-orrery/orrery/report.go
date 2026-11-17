package orrery

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"math"
	"strings"
)

type reportSeries struct {
	Method     string    `json:"method"`
	Symplectic bool      `json:"symplectic"`
	T          []float64 `json:"t"`
	E          []float64 `json:"e"`
	L          []float64 `json:"l"`
	MaxE       float64   `json:"maxE"`
	MaxL       float64   `json:"maxL"`
	Evals      int64     `json:"evals"`
	Steps      int64     `json:"steps"`
	Ms         float64   `json:"ms"`
	Err        string    `json:"err,omitempty"`
}

type reportData struct {
	Title   string         `json:"title"`
	Params  string         `json:"params"`
	Names   []string       `json:"names"`
	Mass    []float64      `json:"mass"`
	View    string         `json:"view"`
	Times   []float64      `json:"times"`
	Frames  [][]float64    `json:"frames"` // frames[k] = [x0,y0,z0,x1,...]
	Series  []reportSeries `json:"series"`
	Omitted int            `json:"omitted"`
}

func round6(x float64) float64 {
	if x == 0 || math.IsNaN(x) || math.IsInf(x, 0) {
		return 0
	}
	p := math.Pow(10, 5-math.Floor(math.Log10(math.Abs(x))))
	return math.Round(x*p) / p
}

// BuildReport integrates sys with each method and returns a self-contained
// HTML page: animated orbits (from the `view` method) and a log-scale
// comparison of energy and angular-momentum error.
func BuildReport(sys *System, methods []Method, view Method, dt, T float64, tol float64) (string, error) {
	if len(methods) == 0 {
		return "", errors.New("no methods to compare")
	}
	if err := sys.Validate(); err != nil {
		return "", err
	}
	d := reportData{Title: sys.Title, View: string(view)}
	if d.Title == "" {
		d.Title = "N-body system"
	}
	d.Params = fmt.Sprintf("N=%d · G=%g · ε=%g · θ=%g · T=%g · dt=%g", len(sys.Bodies), sys.G, sys.Eps, sys.Theta, T, dt)
	maxView := 400
	nb := len(sys.Bodies)
	idx := make([]int, 0, nb)
	if nb <= maxView {
		for i := 0; i < nb; i++ {
			idx = append(idx, i)
		}
	} else {
		stride := float64(nb) / float64(maxView)
		for k := 0; k < maxView; k++ {
			idx = append(idx, int(float64(k)*stride))
		}
		d.Omitted = nb - maxView
	}
	for _, i := range idx {
		d.Names = append(d.Names, sys.Bodies[i].Name)
		d.Mass = append(d.Mass, round6(sys.Bodies[i].M))
	}
	viewSeen := false
	for _, m := range methods {
		r, err := Run(sys, m, dt, T, 300, tol)
		if err != nil {
			return "", fmt.Errorf("%s: %w", m, err)
		}
		rs := reportSeries{Method: string(m), Symplectic: m.Symplectic(), MaxE: r.MaxAbsEnergyErr(), MaxL: r.MaxLErr(),
			Evals: r.Evals, Steps: r.Steps, Ms: float64(r.Elapsed.Microseconds()) / 1000}
		if r.Err != nil {
			rs.Err = r.Err.Error()
		}
		for k := range r.Times {
			rs.T = append(rs.T, round6(r.Times[k]))
			rs.E = append(rs.E, math.Abs(r.EnergyErr[k]))
			rs.L = append(rs.L, math.Abs(r.LErr[k]))
		}
		if m == view {
			viewSeen = true
			for k := range r.Times {
				d.Times = append(d.Times, round6(r.Times[k]))
				fr := make([]float64, 0, 3*len(idx))
				for _, i := range idx {
					p := r.Traj[k][i]
					fr = append(fr, round6(p.X), round6(p.Y), round6(p.Z))
				}
				d.Frames = append(d.Frames, fr)
			}
		}
		d.Series = append(d.Series, rs)
	}
	if !viewSeen {
		return "", fmt.Errorf("view method %q is not among the compared methods", view)
	}
	// sanitize NaN/Inf which JSON cannot encode
	for i := range d.Series {
		s := &d.Series[i]
		for _, a := range [][]float64{s.E, s.L} {
			for k, v := range a {
				if math.IsNaN(v) || math.IsInf(v, 0) {
					a[k] = 1e30
				}
			}
		}
		if math.IsNaN(s.MaxE) || math.IsInf(s.MaxE, 0) {
			s.MaxE = 1e30
		}
		if math.IsNaN(s.MaxL) || math.IsInf(s.MaxL, 0) {
			s.MaxL = 1e30
		}
	}
	for _, fr := range d.Frames {
		for k, v := range fr {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				fr[k] = 0
			}
		}
	}
	buf, err := json.Marshal(d)
	if err != nil {
		return "", err
	}
	page := strings.Replace(reportTemplate, "%%TITLE%%", html.EscapeString(d.Title), 1)
	page = strings.Replace(page, "%%DATA%%", string(buf), 1)
	return page, nil
}
