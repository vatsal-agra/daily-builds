package fem

import (
	"math"
	"testing"
)

var steel = Material{E: 200e3, Nu: 0.3, Thickness: 1}

func rel(a, b float64) float64 { return math.Abs(a-b) / math.Max(math.Abs(b), 1e-300) }

// cantilever builds a fixed-left beam with a tip shear load P (downward) as parabolic traction.
func cantilever(t ElemType, L, h float64, nx, ny int, P float64) (*Model, int) {
	m, _ := Rect(0, 0, L, h, nx, ny, t)
	md := NewModel(m, steel)
	for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
		md.FixDOF(n, 0, 0)
		md.FixDOF(n, 1, 0)
	}
	I := steel.Thickness * h * h * h / 12
	for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return x1 > L-1e-12 && x2 > L-1e-12 }) {
		md.EdgeTractionFn(e, func(_, y float64) (float64, float64) { // parabolic shear traction
			yc := y - h/2
			return 0, -P / (2 * I) * (h*h/4 - yc*yc) / steel.Thickness
		})
	}
	return md, m.NearestNode(L, h/2)
}

func TestPatchTestConstantStress(t *testing.T) {
	for _, et := range []ElemType{Tri3, Tri6, Quad4} {
		m, _ := Rect(0, 0, 4, 2, 5, 3, et)
		// distort interior nodes to make the patch test meaningful
		for i := range m.X {
			if m.X[i] > 1e-9 && m.X[i] < 4-1e-9 && m.Y[i] > 1e-9 && m.Y[i] < 2-1e-9 {
				m.X[i] += 0.07 * math.Sin(3.1*float64(i))
				m.Y[i] += 0.06 * math.Cos(1.7*float64(i))
			}
		}
		if et == Tri6 { // keep straight sides: midside nodes at midpoints of their corners
			for _, c := range m.Conn {
				for k := 0; k < 3; k++ {
					a, b := c[k], c[(k+1)%3]
					m.X[c[3+k]], m.Y[c[3+k]] = (m.X[a]+m.X[b])/2, (m.Y[a]+m.Y[b])/2
				}
			}
		}
		md := NewModel(m, steel)
		sx := 100.0
		// exact field: ux = sx/E x, uy = -nu sx/E y
		for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
			md.FixDOF(n, 0, 0)
		}
		md.FixDOF(m.NearestNode(0, 0), 1, 0)
		for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return x1 > 4-1e-9 && x2 > 4-1e-9 }) {
			md.EdgeTraction(e, sx, 0)
		}
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			t.Fatal(err)
		}
		res, _ := Post(md, sol)
		for i := range m.X {
			ex, ey := sx/steel.E*m.X[i], -steel.Nu*sx/steel.E*m.Y[i]
			if math.Abs(sol.U[2*i]-ex) > 1e-10 || math.Abs(sol.U[2*i+1]-ey) > 1e-10 {
				t.Fatalf("%s node %d: u=(%g,%g) want (%g,%g)", et, i, sol.U[2*i], sol.U[2*i+1], ex, ey)
			}
			s := res.Nodal[i]
			if math.Abs(s.XX-sx) > 1e-6 || math.Abs(s.YY) > 1e-6 || math.Abs(s.XY) > 1e-6 {
				t.Fatalf("%s node %d stress (%g,%g,%g)", et, i, s.XX, s.YY, s.XY)
			}
		}
	}
}

func TestRigidBodyModesAreNullSpace(t *testing.T) {
	for _, et := range []ElemType{Tri3, Tri6, Quad4} {
		m, _ := Rect(0, 0, 3, 2, 4, 3, et)
		md := NewModel(m, steel)
		K, _ := md.AssembleK()
		if K.AsymmetryRatio() > 1e-13 {
			t.Fatalf("%s: K not symmetric (%g)", et, K.AsymmetryRatio())
		}
		n := K.N
		tr := make([]float64, n)
		rot := make([]float64, n)
		for i := range m.X {
			tr[2*i] = 1
			rot[2*i], rot[2*i+1] = -m.Y[i], m.X[i]
		}
		for _, v := range [][]float64{tr, rot} {
			out := make([]float64, n)
			K.MulVec(v, out)
			if Norm(out) > 1e-8*steel.E {
				t.Fatalf("%s: K * rigid mode = %g", et, Norm(out))
			}
		}
	}
}

func TestCantileverAgainstBeamTheory(t *testing.T) {
	L, h, P := 100.0, 10.0, 100.0
	I := h * h * h / 12
	exact := P*L*L*L/(3*steel.E*I) + 12*(1+steel.Nu)*P*L/(5*steel.E*h)
	cases := []struct {
		et     ElemType
		nx, ny int
		tol    float64
	}{{Quad4, 80, 8, 0.02}, {Tri6, 30, 3, 0.02}, {Tri3, 120, 12, 0.03}}
	for _, c := range cases {
		md, tip := cantilever(c.et, L, h, c.nx, c.ny, P)
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			t.Fatal(err)
		}
		d := -sol.U[2*tip+1]
		if rel(d, exact) > c.tol {
			t.Errorf("%s: tip deflection %.6g vs beam theory %.6g (%.2f%%)", c.et, d, exact, 100*rel(d, exact))
		}
		// equilibrium: reactions balance applied load
		if math.Abs(sol.R[0]) > 1 && false {
			t.Fatal("unreachable")
		}
		var ry float64
		for i := range md.Mesh.X {
			ry += sol.R[2*i+1]
		}
		if rel(ry, P) > 1e-2 {
			t.Errorf("%s: vertical reaction %g vs P %g", c.et, ry, P)
		}
	}
}

func TestSolversAgree(t *testing.T) {
	md, _ := cantilever(Quad4, 40, 8, 20, 4, 50)
	ref, err := md.Solve(SolverDirect)
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range []SolverKind{SolverCGJacobi, SolverCGIC0} {
		s, err := md.Solve(k)
		if err != nil {
			t.Fatal(err)
		}
		d := make([]float64, len(s.U))
		for i := range d {
			d[i] = s.U[i] - ref.U[i]
		}
		if Norm(d)/Norm(ref.U) > 1e-7 {
			t.Errorf("%s differs from direct by %g", k, Norm(d)/Norm(ref.U))
		}
		if k == SolverCGIC0 {
			sj, _ := md.Solve(SolverCGJacobi)
			if s.Info.CG.Iters >= sj.Info.CG.Iters {
				t.Errorf("IC0 (%d its) should beat Jacobi (%d its)", s.Info.CG.Iters, sj.Info.CG.Iters)
			}
		}
	}
}

func TestRCMReducesBandwidth(t *testing.T) {
	m, _ := Rect(0, 0, 10, 1, 40, 3, Quad4)
	// scramble node numbering
	perm := make([]int, m.NumNodes())
	for i := range perm {
		perm[i] = (i * 37) % m.NumNodes()
	}
	mm := &Mesh{Type: Quad4, X: make([]float64, len(perm)), Y: make([]float64, len(perm))}
	for old, nw := range perm {
		mm.X[nw], mm.Y[nw] = m.X[old], m.Y[old]
	}
	for _, c := range m.Conn {
		nc := make([]int, 4)
		for i, n := range c {
			nc[i] = perm[n]
		}
		mm.Conn = append(mm.Conn, nc)
	}
	K, _ := AssembleSolid(mm, steel, nil)
	b0 := K.Bandwidth()
	b1 := K.Permute(K.RCM()).Bandwidth()
	if b1*5 > b0 {
		t.Errorf("RCM bandwidth %d -> %d, expected big reduction", b0, b1)
	}
}

func TestSingularDetected(t *testing.T) {
	m, _ := Rect(0, 0, 1, 1, 2, 2, Quad4)
	md := NewModel(m, steel)
	md.FixDOF(0, 0, 0)
	md.FixDOF(0, 1, 0) // pins only one node -> rotation mechanism
	md.PointLoad(8, 1, 0)
	if _, err := md.Solve(SolverDirect); err == nil {
		t.Fatal("expected a mechanism error")
	}
	md2 := NewModel(m, steel)
	if _, err := md2.Solve(SolverDirect); err == nil {
		t.Fatal("expected no-supports error")
	}
}

func TestKirschPlateWithHole(t *testing.T) {
	a, L, sig := 1.0, 10.0, 100.0
	run := func(et ElemType, nr, nt int) (float64, *Results) {
		m, err := QuarterHole(L, a, nr, nt, et)
		if err != nil {
			t.Fatal(err)
		}
		md := NewModel(m, steel)
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
			t.Fatal(err)
		}
		res, _ := Post(md, sol)
		return res.Nodal[m.NearestNode(a, 0)].YY / sig, res
	}
	k1, _ := run(Quad4, 14, 16)
	k2, _ := run(Tri6, 14, 24)
	// finite-width (2L = 20a) plate: Kt_gross = 3.03 (Peterson / Howland)
	if math.Abs(k1-3.03) > 0.15 {
		t.Errorf("quad4 SCF %.3f, want ~3.03", k1)
	}
	if math.Abs(k2-3.03) > 0.1 {
		t.Errorf("tri6 SCF %.3f, want ~3.03", k2)
	}
	// stress along x axis should follow Kirsch: sigma_yy(x) = s/2 (2 + a^2/x^2 + 3 a^4/x^4)
	m, _ := QuarterHole(L, a, 10, 12, Tri6)
	_ = m
	_, res := run(Tri6, 14, 24)
	mm := res.Model.Mesh
	for i := range mm.X {
		if math.Abs(mm.Y[i]) < 1e-9 && mm.X[i] >= 1.5 && mm.X[i] <= 3 {
			x := mm.X[i]
			want := sig / 2 * (2 + a*a/(x*x) + 3*math.Pow(a, 4)/math.Pow(x, 4))
			if rel(res.Nodal[i].YY, want) > 0.06 {
				t.Errorf("Kirsch profile at x=%.2f: %.2f vs %.2f", x, res.Nodal[i].YY, want)
			}
		}
	}
}

func TestLameCylinder(t *testing.T) {
	a, b, p := 1.0, 2.0, 50.0
	mat := Material{E: 200e3, Nu: 0.3, Thickness: 1, PlaneStrain: true}
	for _, et := range []ElemType{Quad4, Tri6} {
		m, _ := Annulus(a, b, 8, 8, et)
		md := NewModel(m, mat)
		for _, n := range m.NodesWhere(func(x, y float64) bool { return y < 1e-9 }) {
			md.FixDOF(n, 1, 0)
		}
		for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-9 }) {
			md.FixDOF(n, 0, 0)
		}
		for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool {
			return math.Abs(math.Hypot(x1, y1)-a) < 1e-9 && math.Abs(math.Hypot(x2, y2)-a) < 1e-9
		}) {
			md.EdgePressure(e, p)
		}
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			t.Fatal(err)
		}
		n0 := m.NearestNode(a, 0)
		ur := (1 + mat.Nu) * p * a / (mat.E * (b*b - a*a)) * ((1-2*mat.Nu)*a*a + b*b)
		tol := 0.01
		if et == Quad4 {
			tol = 0.02
		}
		if rel(sol.U[2*n0], ur) > tol {
			t.Errorf("%s: inner radial displacement %.6g vs Lamé %.6g", et, sol.U[2*n0], ur)
		}
		res, _ := Post(md, sol)
		// element-centroid stresses vs Lamé at the centroid radius (polar components)
		worst := 0.0
		for e := range m.Conn {
			xs, ys := m.ElemCoords(e)
			var cx, cy float64
			for i := range xs {
				cx += xs[i] / float64(len(xs))
				cy += ys[i] / float64(len(ys))
			}
			r, th := math.Hypot(cx, cy), math.Atan2(cy, cx)
			s := res.Elem[e]
			sr := s.XX*math.Cos(th)*math.Cos(th) + s.YY*math.Sin(th)*math.Sin(th) + 2*s.XY*math.Sin(th)*math.Cos(th)
			st := s.XX*math.Sin(th)*math.Sin(th) + s.YY*math.Cos(th)*math.Cos(th) - 2*s.XY*math.Sin(th)*math.Cos(th)
			wr := p * a * a / (b*b - a*a) * (1 - b*b/(r*r))
			wt := p * a * a / (b*b - a*a) * (1 + b*b/(r*r))
			worst = math.Max(worst, math.Max(math.Abs(sr-wr), math.Abs(st-wt))/p)
		}
		if worst > 0.06 {
			t.Errorf("%s: worst centroid stress error %.1f%% of p", et, 100*worst)
		}
	}
}

func TestConvergenceRates(t *testing.T) {
	// manufactured smooth field: cantilever under end moment has exact quadratic displacement
	// (pure bending): ux = -M/(EI) x y,  uy = M/(2EI)(x^2 + nu(y^2 - ... )) -- here we use the
	// uniform-tension-with-body-force-free exact solution of a quadratic field via a hand-built case:
	// pure bending of a beam, applying the exact end traction and exact displacement BCs.
	Lb, h, M := 10.0, 2.0, 100.0
	I := h * h * h / 12
	exact := func(x, y float64) (float64, float64) {
		ux := -M / (steel.E * I) * x * y
		uy := M / (2 * steel.E * I) * (x*x + steel.Nu*y*y)
		return ux, uy
	}
	errs := func(et ElemType, n int) float64 {
		m, _ := Rect(0, 0, Lb, h, 5*n, n, et)
		md := NewModel(m, steel)
		for _, nd := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 || x > Lb-1e-12 }) {
			ux, uy := exact(m.X[nd], m.Y[nd])
			md.FixDOF(nd, 0, ux)
			md.FixDOF(nd, 1, uy)
		}
		sol, err := md.Solve(SolverDirect)
		if err != nil {
			t.Fatal(err)
		}
		return DisplacementError(md, sol, exact)
	}
	rate := func(et ElemType) float64 {
		e1, e2 := errs(et, 4), errs(et, 8)
		return math.Log2(e1 / e2)
	}
	if r := rate(Tri3); r < 1.7 {
		t.Errorf("tri3 L2 rate %.2f, want ~2", r)
	}
	if r := rate(Quad4); r < 1.7 {
		t.Errorf("quad4 L2 rate %.2f, want ~2", r)
	}
	// tri6 reproduces a quadratic field exactly (displacement field is quadratic)
	if e := errs(Tri6, 2); e > 1e-9 {
		t.Errorf("tri6 should be exact for quadratic fields, err=%g", e)
	}
}

func TestEdgeLoadsAndBodyForce(t *testing.T) {
	m, _ := Rect(0, 0, 3, 2, 3, 2, Tri6)
	md := NewModel(m, Material{E: 1, Nu: 0.3, Thickness: 0.5})
	for _, e := range m.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return y1 > 2-1e-9 && y2 > 2-1e-9 }) {
		md.EdgePressure(e, 10) // pushes down onto the top face
	}
	var fx, fy float64
	for i := range m.X {
		fx += md.F[2*i]
		fy += md.F[2*i+1]
	}
	if math.Abs(fx) > 1e-12 || math.Abs(fy-(-10*3*0.5)) > 1e-12 {
		t.Errorf("pressure resultant (%g,%g), want (0,-15)", fx, fy)
	}
	md2 := NewModel(m, Material{E: 1, Nu: 0.3, Thickness: 0.5})
	md2.BodyForce(0, -2)
	fy = 0
	for i := range m.X {
		fy += md2.F[2*i+1]
	}
	if math.Abs(fy-(-2*3*2*0.5)) > 1e-12 {
		t.Errorf("body force resultant %g want -6", fy)
	}
}

func TestMeshValidationRejectsBadInput(t *testing.T) {
	m, _ := Rect(0, 0, 1, 1, 1, 1, Quad4)
	m.Conn[0][1], m.Conn[0][3] = m.Conn[0][3], m.Conn[0][1] // inverted
	if err := m.Validate(); err == nil {
		t.Error("inverted element should be rejected")
	}
	if _, err := Rect(0, 0, -1, 1, 1, 1, Tri3); err == nil {
		t.Error("negative size rejected")
	}
	if err := (Material{E: 1, Nu: 0.5, Thickness: 1, PlaneStrain: true}).Validate(); err == nil {
		t.Error("nu=0.5 plane strain incompressible should be rejected")
	}
}

func TestFrameCantileverAndPortal(t *testing.T) {
	// cantilever beam with tip load: delta = PL^3/3EI, theta = PL^2/2EI
	f := NewFrame()
	a, b := f.AddNode(0, 0), f.AddNode(5, 0)
	f.AddMember(Member{N1: a, N2: b, E: 200e3, A: 100, I: 8333})
	for d := 0; d < 3; d++ {
		f.Fix(a, d)
	}
	f.Load(b, 0, -10, 0)
	s, err := f.Solve()
	if err != nil {
		t.Fatal(err)
	}
	if rel(-s.U[3*b+1], 10*125/(3*200e3*8333.0)) > 1e-12 || rel(-s.U[3*b+2], 10*25/(2*200e3*8333.0)) > 1e-12 {
		t.Errorf("frame cantilever mismatch: %v", s.U)
	}
	if rel(f.MomentAt(s, 0, 0), -50) > 1e-9 || math.Abs(f.MomentAt(s, 0, 5)) > 1e-9 {
		t.Errorf("moment diagram wrong: %g %g", f.MomentAt(s, 0, 0), f.MomentAt(s, 0, 5))
	}
	// simply supported beam with UDL: mid deflection 5wL^4/384EI, M_mid = wL^2/8
	g := NewFrame()
	n0, n1, n2 := g.AddNode(0, 0), g.AddNode(3, 0), g.AddNode(6, 0)
	g.AddMember(Member{N1: n0, N2: n1, E: 1e5, A: 10, I: 100, W: -2})
	g.AddMember(Member{N1: n1, N2: n2, E: 1e5, A: 10, I: 100, W: -2})
	g.Fix(n0, 0)
	g.Fix(n0, 1)
	g.Fix(n2, 1)
	s2, err := g.Solve()
	if err != nil {
		t.Fatal(err)
	}
	if rel(-s2.U[3*n1+1], 5*2*math.Pow(6, 4)/(384*1e5*100)) > 1e-9 {
		t.Errorf("SS beam midspan %g", s2.U[3*n1+1])
	}
	if rel(g.MomentAt(s2, 0, 3), 2*36/8.0) > 1e-9 {
		t.Errorf("midspan moment %g", g.MomentAt(s2, 0, 3))
	}
	// truss: 2-bar symmetric A-frame: apex load P -> axial force P/(2 sin a)
	tr := NewFrame()
	l, r, apex := tr.AddNode(0, 0), tr.AddNode(4, 0), tr.AddNode(2, 3)
	tr.AddMember(Member{N1: l, N2: apex, E: 2e5, A: 10, Truss: true})
	tr.AddMember(Member{N1: r, N2: apex, E: 2e5, A: 10, Truss: true})
	tr.Fix(l, 0)
	tr.Fix(l, 1)
	tr.Fix(r, 0)
	tr.Fix(r, 1)
	tr.Load(apex, 0, -30, 0)
	s3, err := tr.Solve()
	if err != nil {
		t.Fatal(err)
	}
	sinA := 3 / math.Hypot(2, 3)
	want := -30 / (2 * sinA)
	for i := 0; i < 2; i++ {
		if rel(tr.AxialForce(s3, i), want) > 1e-9 {
			t.Errorf("truss bar %d axial %g want %g", i, tr.AxialForce(s3, i), want)
		}
	}
}
