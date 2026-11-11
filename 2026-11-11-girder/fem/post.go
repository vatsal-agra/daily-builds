package fem

import (
	"fmt"
	"math"
)

// Field is a per-node scalar field name.
type Field string

const (
	FieldVonMises Field = "vonmises"
	FieldSXX      Field = "sxx"
	FieldSYY      Field = "syy"
	FieldSXY      Field = "sxy"
	FieldS1       Field = "s1"
	FieldS3       Field = "s3"
	FieldDispMag  Field = "disp"
	FieldUX       Field = "ux"
	FieldUY       Field = "uy"
)

// Results are the post-processed fields of a static solution.
type Results struct {
	Model   *Model
	Sol     *Solution
	Nodal   []Stress   // recovered, averaged nodal stresses
	Elem    []Stress   // element-centroid stresses
	Energy  float64    // strain energy 0.5 u'Ku
	Equilib [2]float64 // residual of sum of (F + R) in x and y (should be ~0)
}

// Post computes stresses and diagnostics.
func Post(md *Model, sol *Solution) (*Results, error) {
	m := md.Mesh
	res := &Results{Model: md, Sol: sol}
	nn := m.NumNodes()
	acc := make([]Stress, nn)
	wsum := make([]float64, nn)
	res.Elem = make([]Stress, m.NumElems())
	ln := m.Type.LocalNodes()
	for e, c := range m.Conn {
		xs, ys := m.ElemCoords(e)
		ue := make([]float64, 2*len(c))
		for i, n := range c {
			ue[2*i], ue[2*i+1] = sol.U[2*n], sol.U[2*n+1]
		}
		// element-average stress at the stiffness quadrature points (area-weighted)
		var avg Stress
		wa := 0.0
		for _, g := range m.Type.StiffRule() {
			st, _, err := StressAt(m.Type, xs, ys, md.Mat, ue, g.xi, g.eta)
			if err != nil {
				return nil, err
			}
			_, _, det, _ := Jacobian(m.Type, xs, ys, g.xi, g.eta)
			w := g.w * det
			avg.XX += w * st.XX
			avg.YY += w * st.YY
			avg.XY += w * st.XY
			avg.ZZ += w * st.ZZ
			wa += w
		}
		avg = Stress{avg.XX / wa, avg.YY / wa, avg.XY / wa, avg.ZZ / wa}
		res.Elem[e] = avg
		// nodal values: Quad4 bilinearly extrapolates the 2x2 Gauss-point stresses (the
		// superconvergent samples); other types evaluate the field at the element's own nodes.
		var gpS []Stress
		if m.Type == Quad4 {
			for _, g := range gaussQuad2 {
				st, _, err := StressAt(m.Type, xs, ys, md.Mat, ue, g.xi, g.eta)
				if err != nil {
					return nil, err
				}
				gpS = append(gpS, st)
			}
		}
		for i, n := range c {
			var st Stress
			if gpS != nil {
				sh, _ := Quad4.Shape(ln[i][0]*math.Sqrt(3), ln[i][1]*math.Sqrt(3))
				for k := range gpS {
					st.XX += sh[k] * gpS[k].XX
					st.YY += sh[k] * gpS[k].YY
					st.XY += sh[k] * gpS[k].XY
					st.ZZ += sh[k] * gpS[k].ZZ
				}
			} else {
				var err error
				st, _, err = StressAt(m.Type, xs, ys, md.Mat, ue, ln[i][0], ln[i][1])
				if err != nil {
					return nil, err
				}
			}
			acc[n].XX += wa * st.XX
			acc[n].YY += wa * st.YY
			acc[n].XY += wa * st.XY
			acc[n].ZZ += wa * st.ZZ
			wsum[n] += wa
		}
	}
	res.Nodal = make([]Stress, nn)
	for i := range acc {
		w := wsum[i]
		res.Nodal[i] = Stress{acc[i].XX / w, acc[i].YY / w, acc[i].XY / w, acc[i].ZZ / w}
	}
	// strain energy
	K, err := md.AssembleK()
	if err != nil {
		return nil, err
	}
	ku := make([]float64, K.N)
	K.MulVec(sol.U, ku)
	res.Energy = 0.5 * Dot(sol.U, ku)
	for i := 0; i < nn; i++ {
		res.Equilib[0] += md.F[2*i] + sol.R[2*i]
		res.Equilib[1] += md.F[2*i+1] + sol.R[2*i+1]
	}
	return res, nil
}

// NodalField extracts a scalar per node.
func (r *Results) NodalField(f Field) ([]float64, error) {
	nn := r.Model.Mesh.NumNodes()
	out := make([]float64, nn)
	for i := 0; i < nn; i++ {
		s := r.Nodal[i]
		switch f {
		case FieldVonMises:
			out[i] = s.VonMises()
		case FieldSXX:
			out[i] = s.XX
		case FieldSYY:
			out[i] = s.YY
		case FieldSXY:
			out[i] = s.XY
		case FieldS1:
			out[i], _ = s.Principal()
		case FieldS3:
			_, out[i] = s.Principal()
		case FieldDispMag:
			out[i] = math.Hypot(r.Sol.U[2*i], r.Sol.U[2*i+1])
		case FieldUX:
			out[i] = r.Sol.U[2*i]
		case FieldUY:
			out[i] = r.Sol.U[2*i+1]
		default:
			return nil, fmt.Errorf("unknown field %q", f)
		}
	}
	return out, nil
}

// MaxField returns the max and the node index where it occurs.
func MaxField(v []float64) (float64, int) {
	best, at := math.Inf(-1), 0
	for i, x := range v {
		if x > best {
			best, at = x, i
		}
	}
	return best, at
}

// DisplacementError returns the relative L2 norm of (u_h - u_exact) over the mesh (Gauss integrated).
func DisplacementError(md *Model, sol *Solution, exact func(x, y float64) (float64, float64)) float64 {
	m := md.Mesh
	var num, den float64
	for e, c := range m.Conn {
		xs, ys := m.ElemCoords(e)
		for _, g := range m.Type.MassRule() {
			sh, _, det, err := Jacobian(m.Type, xs, ys, g.xi, g.eta)
			if err != nil {
				continue
			}
			var x, y, ux, uy float64
			for i, n := range c {
				x += sh[i] * m.X[n]
				y += sh[i] * m.Y[n]
				ux += sh[i] * sol.U[2*n]
				uy += sh[i] * sol.U[2*n+1]
			}
			ex, ey := exact(x, y)
			w := g.w * det
			num += w * ((ux-ex)*(ux-ex) + (uy-ey)*(uy-ey))
			den += w * (ex*ex + ey*ey)
		}
	}
	return math.Sqrt(num / den)
}
