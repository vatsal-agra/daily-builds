package fem

import (
	"fmt"
	"html"
	"math"
	"strings"
)

// Check is one verification result against a closed-form or reference value.
type Check struct {
	Name      string
	Got, Want float64
	Tol       float64 // relative tolerance
	Note      string
}

func (c Check) Err() float64 { return math.Abs(c.Got-c.Want) / math.Max(math.Abs(c.Want), 1e-300) }
func (c Check) Pass() bool   { return c.Err() <= c.Tol }

// ConvRow is one row of a convergence study.
type ConvRow struct {
	Type ElemType
	H    float64
	DOFs int
	Err  float64
	Rate float64 // observed order vs previous row (NaN for first)
}

var valSteel = Material{E: 200e3, Nu: 0.3, Thickness: 1}

// ConvergenceStudy solves pure bending of a beam, whose exact solution is quadratic, on
// successively refined meshes and reports L2 displacement errors and observed orders.
// For a *non-polynomial* check the cantilever with parabolic end shear is used elsewhere.
func ConvergenceStudy() ([]ConvRow, error) {
	// Smooth non-polynomial manufactured solution is not needed: the cantilever with end load below
	// has a cubic displacement field, which linear elements cannot represent exactly (so rates show up)
	// while tri6 (quadratic) converge one order faster.
	L, h, P := 8.0, 2.0, 100.0
	I := h * h * h / 12
	E, nu := valSteel.E, valSteel.Nu
	// Timoshenko–Goodier exact cantilever solution (plane stress), origin at the clamped section centroid
	exact := func(x, y float64) (float64, float64) {
		// (Timoshenko & Goodier use y downward; signs flipped here for y up and P acting downward)
		ux := P * y / (6 * E * I) * ((6*L-3*x)*x + (2+nu)*(y*y-h*h/4))
		uy := -P / (6 * E * I) * (3*nu*y*y*(L-x) + (4+5*nu)*h*h*x/4 + (3*L-x)*x*x)
		return ux, uy
	}
	var rows []ConvRow
	for _, et := range []ElemType{Tri3, Quad4, Tri6} {
		prev := math.NaN()
		for _, n := range []int{2, 4, 8, 16} {
			m, err := Rect(0, -h/2, L, h, 4*n, n, et)
			if err != nil {
				return nil, err
			}
			md := NewModel(m, valSteel)
			// exact displacements on the clamped end, exact tractions on the loaded end & free faces
			for _, nd := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
				ux, uy := exact(m.X[nd], m.Y[nd])
				md.FixDOF(nd, 0, ux)
				md.FixDOF(nd, 1, uy)
			}
			for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return x1 > L-1e-12 && x2 > L-1e-12 }) {
				md.EdgeTractionFn(e, func(_, y float64) (float64, float64) {
					return 0, -P / (2 * I) * (h*h/4 - y*y) / valSteel.Thickness
				})
			}
			sol, err := md.Solve(SolverDirect)
			if err != nil {
				return nil, err
			}
			e := DisplacementError(md, sol, exact)
			rate := math.NaN()
			if !math.IsNaN(prev) {
				rate = math.Log2(prev / e)
			}
			rows = append(rows, ConvRow{Type: et, H: h / float64(n), DOFs: 2 * m.NumNodes(), Err: e, Rate: rate})
			prev = e
		}
	}
	return rows, nil
}

// RunValidation executes the closed-form verification suite.
func RunValidation() ([]Check, []ConvRow, error) {
	var cs []Check
	// 1. Kirsch plate with hole
	a, L, sig := 1.0, 10.0, 100.0
	for _, c := range []struct {
		et     ElemType
		nr, nt int
	}{{Quad4, 24, 32}, {Tri6, 14, 24}} {
		m, err := QuarterHole(L, a, c.nr, c.nt, c.et)
		if err != nil {
			return nil, nil, err
		}
		md := NewModel(m, valSteel)
		for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-9 }) {
			md.FixDOF(n, 0, 0)
		}
		for _, n := range m.NodesWhere(func(x, y float64) bool { return y < 1e-9 }) {
			md.FixDOF(n, 1, 0)
		}
		for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return y1 > L-1e-9 && y2 > L-1e-9 }) {
			md.EdgeTraction(e, 0, sig)
		}
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			return nil, nil, err
		}
		res, _ := Post(md, sol)
		cs = append(cs, Check{Name: fmt.Sprintf("Kirsch hole SCF (%s, %d el.)", c.et, m.NumElems()), Got: res.Nodal[m.NearestNode(a, 0)].YY / sig, Want: 3.03, Tol: 0.04,
			Note: "σyy at hole edge / remote σ; infinite plate = 3, finite width 2L=20a → 3.03 (Peterson)"})
	}
	// 2. Lamé thick cylinder displacement
	{
		b, p := 2.0, 50.0
		mat := Material{E: 200e3, Nu: 0.3, Thickness: 1, PlaneStrain: true}
		for _, et := range []ElemType{Quad4, Tri6} {
			m, _ := Annulus(1, b, 10, 10, et)
			md := NewModel(m, mat)
			for _, n := range m.NodesWhere(func(x, y float64) bool { return y < 1e-9 }) {
				md.FixDOF(n, 1, 0)
			}
			for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-9 }) {
				md.FixDOF(n, 0, 0)
			}
			for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool {
				return math.Abs(math.Hypot(x1, y1)-1) < 1e-9 && math.Abs(math.Hypot(x2, y2)-1) < 1e-9
			}) {
				md.EdgePressure(e, p)
			}
			sol, err := md.Solve(SolverDirect)
			if err != nil {
				return nil, nil, err
			}
			ur := (1 + mat.Nu) * p / (mat.E * (b*b - 1)) * ((1 - 2*mat.Nu) + b*b)
			cs = append(cs, Check{Name: fmt.Sprintf("Lamé cylinder u_r(a) (%s)", et), Got: sol.U[2*m.NearestNode(1, 0)], Want: ur, Tol: 0.005,
				Note: "plane-strain thick cylinder under internal pressure"})
		}
	}
	// 3. Cantilever vs Euler–Bernoulli + shear
	{
		Lc, h, P := 100.0, 10.0, 100.0
		I := h * h * h / 12
		want := P*Lc*Lc*Lc/(3*valSteel.E*I) + 12*(1+valSteel.Nu)*P*Lc/(5*valSteel.E*h)
		m, _ := Rect(0, 0, Lc, h, 60, 6, Tri6)
		md := NewModel(m, valSteel)
		for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
			md.FixDOF(n, 0, 0)
			md.FixDOF(n, 1, 0)
		}
		for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return x1 > Lc-1e-12 && x2 > Lc-1e-12 }) {
			md.EdgeTractionFn(e, func(_, y float64) (float64, float64) {
				yc := y - h/2
				return 0, -P / (2 * I) * (h*h/4 - yc*yc)
			})
		}
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			return nil, nil, err
		}
		cs = append(cs, Check{Name: "Cantilever tip deflection (tri6 60×6)", Got: -sol.U[2*m.NearestNode(Lc, h/2)+1], Want: want, Tol: 0.015,
			Note: "PL³/3EI + 12(1+ν)PL/5EAh shear correction"})
	}
	// 4. Frames
	{
		f := NewFrame()
		n0, n1, n2 := f.AddNode(0, 0), f.AddNode(3, 0), f.AddNode(6, 0)
		f.AddMember(Member{N1: n0, N2: n1, E: 1e5, A: 10, I: 100, W: -2})
		f.AddMember(Member{N1: n1, N2: n2, E: 1e5, A: 10, I: 100, W: -2})
		f.Fix(n0, 0)
		f.Fix(n0, 1)
		f.Fix(n2, 1)
		s, err := f.Solve()
		if err != nil {
			return nil, nil, err
		}
		cs = append(cs, Check{Name: "Simply-supported beam midspan deflection", Got: -s.U[3*n1+1], Want: 5 * 2 * math.Pow(6, 4) / (384 * 1e5 * 100), Tol: 1e-9, Note: "5wL⁴/384EI (Hermite beam elements are exact for UDL at nodes)"})
		cs = append(cs, Check{Name: "Simply-supported beam midspan moment", Got: f.MomentAt(s, 0, 3), Want: 2 * 36 / 8.0, Tol: 1e-9, Note: "wL²/8"})
	}
	// 5. Solver agreement
	{
		m, _ := Rect(0, 0, 40, 8, 40, 8, Quad4)
		md := NewModel(m, valSteel)
		for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
			md.FixDOF(n, 0, 0)
			md.FixDOF(n, 1, 0)
		}
		md.PointLoad(m.NearestNode(40, 4), 0, -50)
		ref, err := md.Solve(SolverDirect)
		if err != nil {
			return nil, nil, err
		}
		for _, k := range []SolverKind{SolverCGJacobi, SolverCGIC0} {
			s, err := md.Solve(k)
			if err != nil {
				return nil, nil, err
			}
			d := make([]float64, len(s.U))
			for i := range d {
				d[i] = s.U[i] - ref.U[i]
			}
			cs = append(cs, Check{Name: fmt.Sprintf("Solver %s vs skyline Cholesky", k), Got: 1 + Norm(d)/Norm(ref.U), Want: 1, Tol: 1e-7,
				Note: fmt.Sprintf("%d CG iterations on %d dofs", s.Info.CG.Iters, s.Info.FreeDOFs)})
		}
	}
	conv, err := ConvergenceStudy()
	return cs, conv, err
}

// ValidationReport renders the verification suite as HTML.
func ValidationReport(cs []Check, conv []ConvRow) string {
	var b strings.Builder
	pass := 0
	for _, c := range cs {
		if c.Pass() {
			pass++
		}
	}
	fmt.Fprintf(&b, `<div class="grid">%s%s</div>`, stat("checks passed", fmt.Sprintf("%d / %d", pass, len(cs))), stat("convergence runs", fmt.Sprint(len(conv))))
	b.WriteString(`<h2>Closed-form checks</h2><div class="tablewrap"><table><tr><th>Check</th><th>Got</th><th>Reference</th><th>Error</th><th>Tol.</th><th></th></tr>`)
	for _, c := range cs {
		cls, mark := "pass", "PASS"
		if !c.Pass() {
			cls, mark = "fail", "FAIL"
		}
		fmt.Fprintf(&b, `<tr><td>%s<br><small style="color:var(--mute)">%s</small></td><td>%.6g</td><td>%.6g</td><td>%.2e</td><td>%.1e</td><td class="%s">%s</td></tr>`,
			html.EscapeString(c.Name), html.EscapeString(c.Note), c.Got, c.Want, c.Err(), c.Tol, cls, mark)
	}
	b.WriteString(`</table></div><h2>Convergence (Timoshenko–Goodier cantilever, L2 displacement error)</h2><div class="tablewrap"><table><tr><th>Element</th><th>h</th><th>DOFs</th><th>Error</th><th>Observed order</th></tr>`)
	for _, r := range conv {
		rate := "—"
		if !math.IsNaN(r.Rate) {
			rate = fmt.Sprintf("%.2f", r.Rate)
		}
		fmt.Fprintf(&b, `<tr><td>%s</td><td>%.4g</td><td>%d</td><td>%.3e</td><td>%s</td></tr>`, r.Type, r.H, r.DOFs, r.Err, rate)
	}
	b.WriteString(`</table></div>`)
	return Page("Girder verification suite", "Every number below is compared to a closed-form solution from elasticity or beam theory", b.String())
}
