package fem

import (
	"fmt"
	"math"
)

// HeatModel is a steady-state conduction problem on the same meshes as the solid solver.
type HeatModel struct {
	Mesh  *Mesh
	Mat   Material
	Fixed map[int]float64 // node -> prescribed temperature
	Q     []float64       // nodal heat input vector
}

func NewHeatModel(m *Mesh, mat Material) *HeatModel {
	return &HeatModel{Mesh: m, Mat: mat, Fixed: map[int]float64{}, Q: make([]float64, m.NumNodes())}
}

// EdgeFlux adds a uniform heat flux q (power per area, positive INTO the body) over an edge.
func (h *HeatModel) EdgeFlux(e Edge, q float64) error {
	for _, n := range e {
		if n < 0 || n >= h.Mesh.NumNodes() {
			return fmt.Errorf("node %d out of range", n)
		}
	}
	for _, g := range gauss3 {
		n, dn := edgeShape(len(e), g[0])
		var tx, ty float64
		for i, nd := range e {
			tx += dn[i] * h.Mesh.X[nd]
			ty += dn[i] * h.Mesh.Y[nd]
		}
		l := math.Hypot(tx, ty)
		for i, nd := range e {
			h.Q[nd] += n[i] * q * l * g[1] * h.Mat.Thickness
		}
	}
	return nil
}

// Source adds a volumetric heat source s (power per volume).
func (h *HeatModel) Source(s float64) error {
	m := h.Mesh
	for e := range m.Conn {
		xs, ys := m.ElemCoords(e)
		for _, g := range m.Type.MassRule() {
			sh, _, det, err := Jacobian(m.Type, xs, ys, g.xi, g.eta)
			if err != nil {
				return fmt.Errorf("element %d: %w", e, err)
			}
			for i, n := range m.Conn[e] {
				h.Q[n] += sh[i] * g.w * det * h.Mat.Thickness * s
			}
		}
	}
	return nil
}

// Solve returns nodal temperatures.
func (h *HeatModel) Solve(kind SolverKind) ([]float64, error) {
	if !(h.Mat.Cond > 0) {
		return nil, fmt.Errorf("conductivity must be > 0: add k= to `material`")
	}
	if err := h.Mesh.Validate(); err != nil {
		return nil, err
	}
	if len(h.Fixed) == 0 {
		return nil, fmt.Errorf("no `temp` boundary condition: steady conduction is undetermined")
	}
	m := h.Mesh
	t := NewTriplets(m.NumNodes())
	for e, c := range m.Conn {
		xs, ys := m.ElemCoords(e)
		ke, err := ConductK(m.Type, xs, ys, h.Mat)
		if err != nil {
			return nil, err
		}
		for i := range c {
			for j := range c {
				t.Add(c[i], c[j], ke[i*len(c)+j])
			}
		}
	}
	sol, err := ReduceAndSolve(t.ToCSR(), h.Q, h.Fixed, kind, 1e-12)
	if err != nil {
		return nil, err
	}
	return sol.U, nil
}

// HeatReport renders a temperature contour page.
func HeatReport(title string, h *HeatModel, T []float64) string {
	lo, hi := math.Inf(1), math.Inf(-1)
	for _, v := range T {
		lo, hi = math.Min(lo, v), math.Max(hi, v)
	}
	var b stringsBuilder
	b.w(`<div class="grid">` + stat("min T", fmtNum(lo)) + stat("max T", fmtNum(hi)) + stat("nodes", fmt.Sprint(h.Mesh.NumNodes())) + `</div>`)
	b.w(`<div class="panels"><figure><figcaption>Temperature</figcaption>` + ContourSVG(h.Mesh, nil, T, ContourOpts{Title: "Temperature", Unit: "T"}) + `</figure></div>`)
	return Page(title, "Girder steady-state heat conduction", b.String())
}
