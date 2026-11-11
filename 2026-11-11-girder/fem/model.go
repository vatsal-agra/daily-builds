package fem

import (
	"fmt"
	"math"
	"sort"
)

// Model is a 2-D solid mechanics problem (plane stress or plane strain).
type Model struct {
	Mesh  *Mesh
	Mat   Material
	Fixed map[int]float64 // dof (2*node+{0,1}) -> prescribed displacement
	F     []float64       // external nodal force vector
}

func NewModel(m *Mesh, mat Material) *Model {
	return &Model{Mesh: m, Mat: mat, Fixed: map[int]float64{}, F: make([]float64, 2*m.NumNodes())}
}

func (md *Model) checkNode(n int) error {
	if n < 0 || n >= md.Mesh.NumNodes() {
		return fmt.Errorf("node %d out of range [0,%d)", n, md.Mesh.NumNodes())
	}
	return nil
}

// FixDOF prescribes displacement component d (0=x,1=y) of node n.
func (md *Model) FixDOF(n, d int, v float64) error {
	if err := md.checkNode(n); err != nil {
		return err
	}
	if d < 0 || d > 1 {
		return fmt.Errorf("dof component must be 0 or 1")
	}
	md.Fixed[2*n+d] = v
	return nil
}

// PointLoad adds a concentrated force at a node.
func (md *Model) PointLoad(n int, fx, fy float64) error {
	if err := md.checkNode(n); err != nil {
		return err
	}
	md.F[2*n] += fx
	md.F[2*n+1] += fy
	return nil
}

var gauss3 = [3][2]float64{{-math.Sqrt(0.6), 5.0 / 9}, {0, 8.0 / 9}, {math.Sqrt(0.6), 5.0 / 9}}

func edgeShape(nn int, s float64) (n, dn []float64) {
	if nn == 2 {
		return []float64{(1 - s) / 2, (1 + s) / 2}, []float64{-0.5, 0.5}
	}
	return []float64{s * (s - 1) / 2, s * (s + 1) / 2, 1 - s*s}, []float64{s - 0.5, s + 0.5, -2 * s}
}

// edgeLoad integrates a traction field over an edge; fn returns (tx,ty) given tangent-derived
// outward normal (nx,ny).
func (md *Model) edgeLoad(e Edge, fn func(x, y, nx, ny float64) (float64, float64)) error {
	for _, n := range e {
		if err := md.checkNode(n); err != nil {
			return err
		}
	}
	for _, g := range gauss3 {
		n, dn := edgeShape(len(e), g[0])
		var tx, ty, px, py float64
		for i, nd := range e {
			tx += dn[i] * md.Mesh.X[nd]
			ty += dn[i] * md.Mesh.Y[nd]
			px += n[i] * md.Mesh.X[nd]
			py += n[i] * md.Mesh.Y[nd]
		}
		l := math.Hypot(tx, ty)
		if l == 0 {
			return fmt.Errorf("zero-length edge")
		}
		fx, fy := fn(px, py, ty/l, -tx/l)
		for i, nd := range e {
			md.F[2*nd] += n[i] * fx * l * g[1] * md.Mat.Thickness
			md.F[2*nd+1] += n[i] * fy * l * g[1] * md.Mat.Thickness
		}
	}
	return nil
}

// EdgeTraction applies a uniform traction (force per unit area, global axes) along an edge.
func (md *Model) EdgeTraction(e Edge, tx, ty float64) error {
	return md.edgeLoad(e, func(_, _, _, _ float64) (float64, float64) { return tx, ty })
}

// EdgeTractionFn applies a position-dependent traction (force per area) along an edge.
func (md *Model) EdgeTractionFn(e Edge, fn func(x, y float64) (float64, float64)) error {
	return md.edgeLoad(e, func(x, y, _, _ float64) (float64, float64) { return fn(x, y) })
}

// EdgePressure applies a pressure pushing INTO the body (positive = compressive).
func (md *Model) EdgePressure(e Edge, p float64) error {
	return md.edgeLoad(e, func(_, _, nx, ny float64) (float64, float64) { return -p * nx, -p * ny })
}

// BodyForce applies a force per unit volume (e.g. gravity: 0, -rho*g).
func (md *Model) BodyForce(bx, by float64) error {
	m := md.Mesh
	for e := range m.Conn {
		xs, ys := m.ElemCoords(e)
		for _, g := range m.Type.MassRule() {
			sh, _, det, err := Jacobian(m.Type, xs, ys, g.xi, g.eta)
			if err != nil {
				return fmt.Errorf("element %d: %w", e, err)
			}
			for i, n := range m.Conn[e] {
				w := sh[i] * g.w * det * md.Mat.Thickness
				md.F[2*n] += w * bx
				md.F[2*n+1] += w * by
			}
		}
	}
	return nil
}

func dofsOf(conn []int) []int {
	d := make([]int, 2*len(conn))
	for i, n := range conn {
		d[2*i], d[2*i+1] = 2*n, 2*n+1
	}
	return d
}

// AssembleK assembles the global stiffness matrix.
func (md *Model) AssembleK() (*CSR, error) {
	return AssembleSolid(md.Mesh, md.Mat, nil)
}

// AssembleSolid assembles K; if scale != nil it multiplies element e's stiffness by scale[e].
func AssembleSolid(m *Mesh, mat Material, scale []float64) (*CSR, error) {
	if err := mat.Validate(); err != nil {
		return nil, err
	}
	t := NewTriplets(2 * m.NumNodes())
	for e := range m.Conn {
		xs, ys := m.ElemCoords(e)
		ke, err := Stiffness(m.Type, xs, ys, mat)
		if err != nil {
			return nil, fmt.Errorf("element %d: %w", e, err)
		}
		s := 1.0
		if scale != nil {
			s = scale[e]
		}
		dofs := dofsOf(m.Conn[e])
		nd := len(dofs)
		for i := 0; i < nd; i++ {
			for j := 0; j < nd; j++ {
				t.Add(dofs[i], dofs[j], s*ke[i*nd+j])
			}
		}
	}
	return t.ToCSR(), nil
}

// SolverKind selects the linear solver.
type SolverKind string

const (
	SolverDirect   SolverKind = "direct"
	SolverCGJacobi SolverKind = "cg-jacobi"
	SolverCGIC0    SolverKind = "cg-ic0"
)

// SolveInfo records how the linear system was solved.
type SolveInfo struct {
	Solver     SolverKind
	FreeDOFs   int
	NNZ        int
	Bandwidth0 int // before RCM
	Bandwidth1 int // after RCM
	CG         CGResult
}

// Solution is the result of a static solve.
type Solution struct {
	U     []float64
	R     []float64 // reaction forces (nonzero only at constrained dofs)
	Info  SolveInfo
	Compl float64 // external work 0.5 f.u
}

// ReduceAndSolve solves K u = f with Dirichlet elimination. Used by solid and topology code.
func ReduceAndSolve(K *CSR, f []float64, fixed map[int]float64, kind SolverKind, tol float64) (*Solution, error) {
	n := K.N
	if len(fixed) == 0 {
		return nil, fmt.Errorf("model has no supports: rigid-body motion is unconstrained")
	}
	free := make([]int, 0, n)
	idx := make([]int, n)
	for i := 0; i < n; i++ {
		if _, ok := fixed[i]; ok {
			idx[i] = -1
		} else {
			idx[i] = len(free)
			free = append(free, i)
		}
	}
	u := make([]float64, n)
	for d, v := range fixed {
		if d < 0 || d >= n {
			return nil, fmt.Errorf("constrained dof %d out of range", d)
		}
		u[d] = v
	}
	rhs := make([]float64, len(free))
	t := NewTriplets(len(free))
	for k, i := range free {
		rhs[k] = f[i]
		for p := K.RowPtr[i]; p < K.RowPtr[i+1]; p++ {
			j := K.Col[p]
			if idx[j] >= 0 {
				t.I = append(t.I, k)
				t.J = append(t.J, idx[j])
				t.V = append(t.V, K.Val[p])
			} else {
				rhs[k] -= K.Val[p] * u[j]
			}
		}
	}
	info := SolveInfo{Solver: kind, FreeDOFs: len(free)}
	var xf []float64
	if len(free) > 0 {
		kr := t.ToCSR()
		info.NNZ = kr.NNZ()
		info.Bandwidth0 = kr.Bandwidth()
		switch kind {
		case SolverCGJacobi, SolverCGIC0:
			prec := PrecJacobi
			if kind == SolverCGIC0 {
				prec = PrecIC0
			}
			var res CGResult
			xf, res = PCG(kr, rhs, prec, tol, 20*len(free)+100)
			info.CG = res
			if !res.Converged {
				return nil, fmt.Errorf("CG did not converge in %d iterations (rel. residual %.2e): check supports", res.Iters, res.Residual)
			}
		default:
			perm := kr.RCM()
			info.Bandwidth1 = kr.Permute(perm).Bandwidth()
			var err error
			xf, err = SolveSPD(kr, rhs)
			if err != nil {
				return nil, err
			}
		}
		for k, i := range free {
			u[i] = xf[k]
		}
	}
	// reactions r = K u - f at constrained dofs
	ku := make([]float64, n)
	K.MulVec(u, ku)
	r := make([]float64, n)
	for d := range fixed {
		r[d] = ku[d] - f[d]
	}
	w := 0.0
	for i := range u {
		w += 0.5 * f[i] * u[i]
	}
	for d := range fixed {
		w += 0.5 * r[d] * u[d]
	}
	return &Solution{U: u, R: r, Info: info, Compl: w}, nil
}

// Solve assembles and solves the static problem.
func (md *Model) Solve(kind SolverKind) (*Solution, error) {
	if err := md.Mesh.Validate(); err != nil {
		return nil, err
	}
	K, err := md.AssembleK()
	if err != nil {
		return nil, err
	}
	return ReduceAndSolve(K, md.F, md.Fixed, kind, 1e-11)
}

// SortedFixed lists constrained dofs in order.
func (md *Model) SortedFixed() []int {
	var d []int
	for k := range md.Fixed {
		d = append(d, k)
	}
	sort.Ints(d)
	return d
}
