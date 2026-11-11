package fem

import (
	"fmt"
	"math"
)

// Member is a 2-D Euler–Bernoulli beam-column or pin-ended truss bar.
type Member struct {
	N1, N2  int
	E, A, I float64
	Truss   bool    // axial-only bar (ignores I)
	W       float64 // uniform transverse load, local +y, force per length
	Rho     float64 // mass density (for modal analysis)
}

// Frame is a 2-D frame/truss structure with 3 dofs (u, v, theta) per node.
type Frame struct {
	X, Y    []float64
	Members []Member
	Fixed   map[int]float64
	F       []float64
}

func NewFrame() *Frame { return &Frame{Fixed: map[int]float64{}} }

// AddNode appends a node and returns its index.
func (f *Frame) AddNode(x, y float64) int {
	f.X = append(f.X, x)
	f.Y = append(f.Y, y)
	f.F = append(f.F, 0, 0, 0)
	return len(f.X) - 1
}

func (f *Frame) AddMember(m Member) (int, error) {
	n := len(f.X)
	if m.N1 < 0 || m.N1 >= n || m.N2 < 0 || m.N2 >= n || m.N1 == m.N2 {
		return 0, fmt.Errorf("member references invalid nodes %d,%d", m.N1, m.N2)
	}
	if !(m.E > 0 && m.A > 0) || (!m.Truss && !(m.I > 0)) {
		return 0, fmt.Errorf("member needs E>0, A>0 and (for beams) I>0")
	}
	if f.length(m) == 0 {
		return 0, fmt.Errorf("member has zero length")
	}
	f.Members = append(f.Members, m)
	return len(f.Members) - 1, nil
}

func (f *Frame) length(m Member) float64 {
	return math.Hypot(f.X[m.N2]-f.X[m.N1], f.Y[m.N2]-f.Y[m.N1])
}

// Fix constrains dof d (0=u,1=v,2=theta) of node n.
func (f *Frame) Fix(n, d int) error {
	if n < 0 || n >= len(f.X) || d < 0 || d > 2 {
		return fmt.Errorf("invalid dof (node %d, comp %d)", n, d)
	}
	f.Fixed[3*n+d] = 0
	return nil
}

// Load adds a nodal force/moment.
func (f *Frame) Load(n int, fx, fy, mz float64) error {
	if n < 0 || n >= len(f.X) {
		return fmt.Errorf("invalid node %d", n)
	}
	f.F[3*n] += fx
	f.F[3*n+1] += fy
	f.F[3*n+2] += mz
	return nil
}

// localK returns the 6x6 local stiffness matrix.
func localK(m Member, L float64) [6][6]float64 {
	var k [6][6]float64
	ea := m.E * m.A / L
	k[0][0], k[0][3], k[3][0], k[3][3] = ea, -ea, -ea, ea
	if m.Truss {
		return k
	}
	ei := m.E * m.I
	a, b, c, d := 12*ei/(L*L*L), 6*ei/(L*L), 4*ei/L, 2*ei/L
	k[1][1], k[1][2], k[1][4], k[1][5] = a, b, -a, b
	k[2][1], k[2][2], k[2][4], k[2][5] = b, c, -b, d
	k[4][1], k[4][2], k[4][4], k[4][5] = -a, -b, a, -b
	k[5][1], k[5][2], k[5][4], k[5][5] = b, d, -b, c
	return k
}

func localM(m Member, L float64) [6][6]float64 {
	var M [6][6]float64
	mu := m.Rho * m.A
	a := mu * L / 6
	M[0][0], M[0][3], M[3][0], M[3][3] = 2*a, a, a, 2*a
	if m.Truss {
		M[1][1], M[1][4], M[4][1], M[4][4] = 2*a, a, a, 2*a // transverse inertia of a bar
		return M
	}
	c := mu * L / 420
	M[1][1], M[1][2], M[1][4], M[1][5] = 156*c, 22*L*c, 54*c, -13*L*c
	M[2][1], M[2][2], M[2][4], M[2][5] = 22*L*c, 4*L*L*c, 13*L*c, -3*L*L*c
	M[4][1], M[4][2], M[4][4], M[4][5] = 54*c, 13*L*c, 156*c, -22*L*c
	M[5][1], M[5][2], M[5][4], M[5][5] = -13*L*c, -3*L*L*c, -22*L*c, 4*L*L*c
	return M
}

// transform returns cos, sin of the member axis.
func (f *Frame) axis(m Member) (c, s, L float64) {
	dx, dy := f.X[m.N2]-f.X[m.N1], f.Y[m.N2]-f.Y[m.N1]
	L = math.Hypot(dx, dy)
	return dx / L, dy / L, L
}

// toLocal converts a 6-vector of global member dofs to local.
func toLocal(c, s float64, g [6]float64) [6]float64 {
	return [6]float64{c*g[0] + s*g[1], -s*g[0] + c*g[1], g[2], c*g[3] + s*g[4], -s*g[3] + c*g[4], g[5]}
}
func toGlobal(c, s float64, l [6]float64) [6]float64 {
	return [6]float64{c*l[0] - s*l[1], s*l[0] + c*l[1], l[2], c*l[3] - s*l[4], s*l[3] + c*l[4], l[5]}
}

func (f *Frame) memberDofs(m Member) [6]int {
	return [6]int{3 * m.N1, 3*m.N1 + 1, 3*m.N1 + 2, 3 * m.N2, 3*m.N2 + 1, 3*m.N2 + 2}
}

// elemGlobal returns Tᵀ k T for a 6x6 local matrix.
func elemGlobal(c, s float64, k [6][6]float64) [6][6]float64 {
	var t [6][6]float64
	for blk := 0; blk < 2; blk++ {
		o := 3 * blk
		t[o][o], t[o][o+1] = c, s
		t[o+1][o], t[o+1][o+1] = -s, c
		t[o+2][o+2] = 1
	}
	var kt, out [6][6]float64
	for i := 0; i < 6; i++ {
		for j := 0; j < 6; j++ {
			for l := 0; l < 6; l++ {
				kt[i][j] += k[i][l] * t[l][j]
			}
		}
	}
	for i := 0; i < 6; i++ {
		for j := 0; j < 6; j++ {
			for l := 0; l < 6; l++ {
				out[i][j] += t[l][i] * kt[l][j]
			}
		}
	}
	return out
}

// pinnedRotations returns rotation dofs that belong only to truss bars (and so need fixing).
func (f *Frame) pinnedRotations() map[int]float64 {
	hasBeam := make([]bool, len(f.X))
	for _, m := range f.Members {
		if !m.Truss {
			hasBeam[m.N1], hasBeam[m.N2] = true, true
		}
	}
	out := map[int]float64{}
	for n := range f.X {
		if !hasBeam[n] {
			out[3*n+2] = 0
		}
	}
	return out
}

// Assemble builds the global K (and M when mass is true).
func (f *Frame) Assemble(mass bool) *CSR {
	t := NewTriplets(3 * len(f.X))
	for _, m := range f.Members {
		c, s, L := f.axis(m)
		var k [6][6]float64
		if mass {
			k = localM(m, L)
		} else {
			k = localK(m, L)
		}
		g := elemGlobal(c, s, k)
		d := f.memberDofs(m)
		for i := 0; i < 6; i++ {
			for j := 0; j < 6; j++ {
				t.Add(d[i], d[j], g[i][j])
			}
		}
	}
	return t.ToCSR()
}

// FrameSolution holds displacements, reactions and member end forces.
type FrameSolution struct {
	U         []float64
	R         []float64
	EndForces [][6]float64 // local [N1 V1 M1 N2 V2 M2], forces exerted ON the member by its nodes
}

// Solve performs the static analysis.
func (f *Frame) Solve() (*FrameSolution, error) {
	if len(f.Members) == 0 {
		return nil, fmt.Errorf("frame has no members")
	}
	K := f.Assemble(false)
	rhs := append([]float64(nil), f.F...)
	for _, m := range f.Members { // equivalent nodal loads from member UDL
		if m.W == 0 {
			continue
		}
		c, s, L := f.axis(m)
		fe := [6]float64{0, m.W * L / 2, m.W * L * L / 12, 0, m.W * L / 2, -m.W * L * L / 12}
		g := toGlobal(c, s, fe)
		d := f.memberDofs(m)
		for i := 0; i < 6; i++ {
			rhs[d[i]] += g[i]
		}
	}
	fixed := map[int]float64{}
	for k, v := range f.pinnedRotations() {
		fixed[k] = v
	}
	for k, v := range f.Fixed {
		fixed[k] = v
	}
	sol, err := ReduceAndSolve(K, rhs, fixed, SolverDirect, 0)
	if err != nil {
		return nil, fmt.Errorf("frame solve failed: %w", err)
	}
	fs := &FrameSolution{U: sol.U, R: sol.R}
	// reactions only at user-fixed dofs
	for k := range f.pinnedRotations() {
		if _, user := f.Fixed[k]; !user {
			fs.R[k] = 0
		}
	}
	for _, m := range f.Members {
		c, s, L := f.axis(m)
		d := f.memberDofs(m)
		var ug [6]float64
		for i := 0; i < 6; i++ {
			ug[i] = sol.U[d[i]]
		}
		ul := toLocal(c, s, ug)
		k := localK(m, L)
		var ef [6]float64
		for i := 0; i < 6; i++ {
			for j := 0; j < 6; j++ {
				ef[i] += k[i][j] * ul[j]
			}
		}
		if m.W != 0 {
			fe := [6]float64{0, m.W * L / 2, m.W * L * L / 12, 0, m.W * L / 2, -m.W * L * L / 12}
			for i := range ef {
				ef[i] -= fe[i]
			}
		}
		fs.EndForces = append(fs.EndForces, ef)
	}
	return fs, nil
}

// MomentAt returns the sagging bending moment at local position x along member i.
func (f *Frame) MomentAt(sol *FrameSolution, i int, x float64) float64 {
	ef := sol.EndForces[i]
	return -ef[2] + ef[1]*x + f.Members[i].W*x*x/2
}

// ShearAt returns the internal shear (positive = upward on the left face).
func (f *Frame) ShearAt(sol *FrameSolution, i int, x float64) float64 {
	return sol.EndForces[i][1] + f.Members[i].W*x
}

// AxialForce returns the member axial force (tension positive).
func (f *Frame) AxialForce(sol *FrameSolution, i int) float64 { return -sol.EndForces[i][0] }

// Deflected returns global points along member i with transverse Hermite interpolation scaled by sc.
func (f *Frame) Deflected(sol *FrameSolution, i int, sc float64, n int) [][2]float64 {
	m := f.Members[i]
	c, s, L := f.axis(m)
	d := f.memberDofs(m)
	var ug [6]float64
	for k := 0; k < 6; k++ {
		ug[k] = sol.U[d[k]]
	}
	ul := toLocal(c, s, ug)
	pts := make([][2]float64, n+1)
	for k := 0; k <= n; k++ {
		xi := float64(k) / float64(n)
		h1 := 1 - 3*xi*xi + 2*xi*xi*xi
		h2 := L * (xi - 2*xi*xi + xi*xi*xi)
		h3 := 3*xi*xi - 2*xi*xi*xi
		h4 := L * (-xi*xi + xi*xi*xi)
		ax := ul[0]*(1-xi) + ul[3]*xi
		tr := h1*ul[1] + h2*ul[2] + h3*ul[4] + h4*ul[5]
		if m.Truss {
			tr = ul[1]*(1-xi) + ul[4]*xi
		}
		px := f.X[m.N1] + xi*L*c
		py := f.Y[m.N1] + xi*L*s
		pts[k] = [2]float64{px + sc*(ax*c-tr*s), py + sc*(ax*s+tr*c)}
	}
	return pts
}
