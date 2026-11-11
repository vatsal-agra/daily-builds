package fem

import (
	"fmt"
	"math"
)

// ElemType identifies an isoparametric 2-D element family.
type ElemType int

const (
	Tri3 ElemType = iota
	Tri6
	Quad4
)

func (t ElemType) String() string { return [...]string{"tri3", "tri6", "quad4"}[t] }

func ParseElemType(s string) (ElemType, error) {
	switch s {
	case "tri3":
		return Tri3, nil
	case "tri6":
		return Tri6, nil
	case "quad4":
		return Quad4, nil
	}
	return 0, fmt.Errorf("unknown element type %q (want tri3, tri6 or quad4)", s)
}

// NodesPer returns the node count of an element type.
func (t ElemType) NodesPer() int { return [...]int{3, 6, 4}[t] }

// Material holds isotropic elastic / thermal / inertial properties.
type Material struct {
	E, Nu, Thickness float64
	PlaneStrain      bool
	Rho              float64 // mass density
	Cond             float64 // thermal conductivity
}

// D returns the 3x3 constitutive matrix (sxx, syy, txy) vs (exx, eyy, gxy).
func (m Material) D() [3][3]float64 {
	E, v := m.E, m.Nu
	var d [3][3]float64
	if m.PlaneStrain {
		c := E / ((1 + v) * (1 - 2*v))
		d[0][0], d[0][1] = c*(1-v), c*v
		d[1][0], d[1][1] = c*v, c*(1-v)
		d[2][2] = c * (1 - 2*v) / 2
	} else {
		c := E / (1 - v*v)
		d[0][0], d[0][1] = c, c*v
		d[1][0], d[1][1] = c*v, c
		d[2][2] = c * (1 - v) / 2
	}
	return d
}

// Validate checks material sanity.
func (m Material) Validate() error {
	if !(m.E > 0) {
		return fmt.Errorf("Young's modulus must be > 0 (got %g)", m.E)
	}
	if m.PlaneStrain {
		if !(m.Nu > -1 && m.Nu < 0.5) {
			return fmt.Errorf("Poisson ratio must be in (-1, 0.5) for plane strain (got %g)", m.Nu)
		}
	} else if !(m.Nu > -1 && m.Nu < 1) {
		return fmt.Errorf("Poisson ratio must be in (-1, 1) (got %g)", m.Nu)
	}
	if !(m.Thickness > 0) {
		return fmt.Errorf("thickness must be > 0 (got %g)", m.Thickness)
	}
	return nil
}

type gp struct{ xi, eta, w float64 }

var (
	gaussTri1 = []gp{{1.0 / 3, 1.0 / 3, 0.5}}
	gaussTri3 = []gp{{1.0 / 6, 1.0 / 6, 1.0 / 6}, {2.0 / 3, 1.0 / 6, 1.0 / 6}, {1.0 / 6, 2.0 / 3, 1.0 / 6}}
	// Dunavant degree-4, 6 points (weights scaled to reference area 1/2)
	gaussTri6 = []gp{
		{0.445948490915965, 0.445948490915965, 0.223381589678011 / 2},
		{0.108103018168070, 0.445948490915965, 0.223381589678011 / 2},
		{0.445948490915965, 0.108103018168070, 0.223381589678011 / 2},
		{0.091576213509771, 0.091576213509771, 0.109951743655322 / 2},
		{0.816847572980459, 0.091576213509771, 0.109951743655322 / 2},
		{0.091576213509771, 0.816847572980459, 0.109951743655322 / 2},
	}
	g2         = 1 / math.Sqrt(3)
	gaussQuad2 = []gp{{-g2, -g2, 1}, {g2, -g2, 1}, {g2, g2, 1}, {-g2, g2, 1}}
	gaussQuad3 = func() []gp {
		a := math.Sqrt(0.6)
		x := []float64{-a, 0, a}
		w := []float64{5.0 / 9, 8.0 / 9, 5.0 / 9}
		var r []gp
		for i := range x {
			for j := range x {
				r = append(r, gp{x[i], x[j], w[i] * w[j]})
			}
		}
		return r
	}()
)

// StiffRule returns the quadrature used for stiffness integration.
func (t ElemType) StiffRule() []gp {
	switch t {
	case Tri3:
		return gaussTri1
	case Tri6:
		return gaussTri3
	}
	return gaussQuad2
}

// MassRule returns a quadrature rule exact for consistent mass.
func (t ElemType) MassRule() []gp {
	switch t {
	case Tri3, Tri6:
		return gaussTri6
	}
	return gaussQuad3
}

// Shape returns shape functions and derivatives wrt (xi, eta).
func (t ElemType) Shape(xi, eta float64) (n []float64, dn [][2]float64) {
	switch t {
	case Tri3:
		return []float64{1 - xi - eta, xi, eta}, [][2]float64{{-1, -1}, {1, 0}, {0, 1}}
	case Tri6:
		l1, l2, l3 := 1-xi-eta, xi, eta
		n = []float64{l1 * (2*l1 - 1), l2 * (2*l2 - 1), l3 * (2*l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1}
		// d/dxi, d/deta with l1 = 1-xi-eta
		dn = [][2]float64{
			{-(4*l1 - 1), -(4*l1 - 1)},
			{4*l2 - 1, 0},
			{0, 4*l3 - 1},
			{4 * (l1 - l2), -4 * l2},
			{4 * l3, 4 * l2},
			{-4 * l3, 4 * (l1 - l3)},
		}
		return
	default:
		n = []float64{(1 - xi) * (1 - eta) / 4, (1 + xi) * (1 - eta) / 4, (1 + xi) * (1 + eta) / 4, (1 - xi) * (1 + eta) / 4}
		dn = [][2]float64{
			{-(1 - eta) / 4, -(1 - xi) / 4},
			{(1 - eta) / 4, -(1 + xi) / 4},
			{(1 + eta) / 4, (1 + xi) / 4},
			{-(1 + eta) / 4, (1 - xi) / 4},
		}
		return
	}
}

// LocalNodes gives reference coordinates of the element's nodes.
func (t ElemType) LocalNodes() [][2]float64 {
	switch t {
	case Tri3:
		return [][2]float64{{0, 0}, {1, 0}, {0, 1}}
	case Tri6:
		return [][2]float64{{0, 0}, {1, 0}, {0, 1}, {.5, 0}, {.5, .5}, {0, .5}}
	}
	return [][2]float64{{-1, -1}, {1, -1}, {1, 1}, {-1, 1}}
}

// Jacobian computes dN/dx, dN/dy and detJ at a reference point.
func Jacobian(t ElemType, xs, ys []float64, xi, eta float64) (n []float64, dxy [][2]float64, det float64, err error) {
	n, dn := t.Shape(xi, eta)
	var j11, j12, j21, j22 float64
	for i := range n {
		j11 += dn[i][0] * xs[i]
		j12 += dn[i][0] * ys[i]
		j21 += dn[i][1] * xs[i]
		j22 += dn[i][1] * ys[i]
	}
	det = j11*j22 - j12*j21
	if !(det > 0) {
		return nil, nil, det, fmt.Errorf("element has non-positive Jacobian (%.3e): inverted or degenerate", det)
	}
	dxy = make([][2]float64, len(n))
	for i := range n {
		dxy[i][0] = (j22*dn[i][0] - j12*dn[i][1]) / det
		dxy[i][1] = (-j21*dn[i][0] + j11*dn[i][1]) / det
	}
	return
}

// bMatrix builds the 3 x 2n strain-displacement matrix (row-major).
func bMatrix(dxy [][2]float64) []float64 {
	n := len(dxy)
	b := make([]float64, 3*2*n)
	for i := 0; i < n; i++ {
		b[0*2*n+2*i] = dxy[i][0]
		b[1*2*n+2*i+1] = dxy[i][1]
		b[2*n*2+2*i] = dxy[i][1]
		b[2*n*2+2*i+1] = dxy[i][0]
	}
	return b
}

// Stiffness returns the element stiffness matrix Ke (2n x 2n, row-major flat).
func Stiffness(t ElemType, xs, ys []float64, mat Material) ([]float64, error) {
	n := t.NodesPer()
	nd := 2 * n
	ke := make([]float64, nd*nd)
	d := mat.D()
	for _, g := range t.StiffRule() {
		_, dxy, det, err := Jacobian(t, xs, ys, g.xi, g.eta)
		if err != nil {
			return nil, err
		}
		b := bMatrix(dxy)
		f := g.w * det * mat.Thickness
		// DB = D*B
		var db [3][]float64
		for r := 0; r < 3; r++ {
			db[r] = make([]float64, nd)
			for c := 0; c < nd; c++ {
				s := 0.0
				for k := 0; k < 3; k++ {
					s += d[r][k] * b[k*nd+c]
				}
				db[r][c] = s
			}
		}
		for i := 0; i < nd; i++ {
			for j := 0; j < nd; j++ {
				s := 0.0
				for k := 0; k < 3; k++ {
					s += b[k*nd+i] * db[k][j]
				}
				ke[i*nd+j] += f * s
			}
		}
	}
	return ke, nil
}

// Mass returns the consistent mass matrix (2n x 2n).
func Mass(t ElemType, xs, ys []float64, mat Material) ([]float64, error) {
	n := t.NodesPer()
	nd := 2 * n
	me := make([]float64, nd*nd)
	for _, g := range t.MassRule() {
		sh, _, det, err := Jacobian(t, xs, ys, g.xi, g.eta)
		if err != nil {
			return nil, err
		}
		f := g.w * det * mat.Thickness * mat.Rho
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				v := f * sh[i] * sh[j]
				me[(2*i)*nd+2*j] += v
				me[(2*i+1)*nd+2*j+1] += v
			}
		}
	}
	return me, nil
}

// ConductK returns the element conduction matrix (n x n) for steady heat flow.
func ConductK(t ElemType, xs, ys []float64, mat Material) ([]float64, error) {
	n := t.NodesPer()
	ke := make([]float64, n*n)
	for _, g := range t.StiffRule() {
		_, dxy, det, err := Jacobian(t, xs, ys, g.xi, g.eta)
		if err != nil {
			return nil, err
		}
		f := g.w * det * mat.Thickness * mat.Cond
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				ke[i*n+j] += f * (dxy[i][0]*dxy[j][0] + dxy[i][1]*dxy[j][1])
			}
		}
	}
	return ke, nil
}

// Stress is a plane stress/strain state.
type Stress struct{ XX, YY, XY, ZZ float64 }

// VonMises returns the equivalent stress.
func (s Stress) VonMises() float64 {
	return math.Sqrt(0.5*((s.XX-s.YY)*(s.XX-s.YY)+(s.YY-s.ZZ)*(s.YY-s.ZZ)+(s.ZZ-s.XX)*(s.ZZ-s.XX)) + 3*s.XY*s.XY)
}

// Principal returns the in-plane principal stresses (max, min).
func (s Stress) Principal() (float64, float64) {
	m := (s.XX + s.YY) / 2
	r := math.Hypot((s.XX-s.YY)/2, s.XY)
	return m + r, m - r
}

// StressAt evaluates the stress at a reference point given element displacements ue (2n).
func StressAt(t ElemType, xs, ys []float64, mat Material, ue []float64, xi, eta float64) (Stress, [3]float64, error) {
	_, dxy, _, err := Jacobian(t, xs, ys, xi, eta)
	if err != nil {
		return Stress{}, [3]float64{}, err
	}
	var eps [3]float64
	for i := range dxy {
		eps[0] += dxy[i][0] * ue[2*i]
		eps[1] += dxy[i][1] * ue[2*i+1]
		eps[2] += dxy[i][1]*ue[2*i] + dxy[i][0]*ue[2*i+1]
	}
	d := mat.D()
	var s [3]float64
	for r := 0; r < 3; r++ {
		for c := 0; c < 3; c++ {
			s[r] += d[r][c] * eps[c]
		}
	}
	st := Stress{XX: s[0], YY: s[1], XY: s[2]}
	if mat.PlaneStrain {
		st.ZZ = mat.Nu * (s[0] + s[1])
	}
	return st, eps, nil
}
