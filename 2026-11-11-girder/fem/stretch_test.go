package fem

import (
	"math"
	"testing"
)

func TestFrameModesVsEulerBernoulli(t *testing.T) {
	E, I, A, rho, L := 200e9, 8.0e-6, 4e-3, 7850.0, 2.0
	mu := rho * A
	build := func(support func(f *Frame, a, b int)) *Frame {
		f := NewFrame()
		prev := f.AddNode(0, 0)
		first := prev
		for i := 1; i <= 20; i++ {
			n := f.AddNode(L*float64(i)/20, 0)
			f.AddMember(Member{N1: prev, N2: n, E: E, A: A, I: I, Rho: rho})
			prev = n
		}
		support(f, first, prev)
		return f
	}
	cant := build(func(f *Frame, a, b int) { f.Fix(a, 0); f.Fix(a, 1); f.Fix(a, 2) })
	ms, _, err := cant.FrameModes(3)
	if err != nil {
		t.Fatal(err)
	}
	for i, bl := range []float64{1.875104069, 4.694091133, 7.854757438} {
		want := bl * bl * math.Sqrt(E*I/(mu*math.Pow(L, 4))) / (2 * math.Pi)
		if rel(ms.Freq(i), want) > 2e-3 {
			t.Errorf("cantilever mode %d: %g Hz vs %g", i+1, ms.Freq(i), want)
		}
	}
	ss := build(func(f *Frame, a, b int) { f.Fix(a, 0); f.Fix(a, 1); f.Fix(b, 1) })
	ms, _, err = ss.FrameModes(4)
	if err != nil {
		t.Fatal(err)
	}
	// the pin-roller beam also has a fixed-free axial rod mode (f = sqrt(E/rho)/4L) between bending modes 2 and 3
	if ax := math.Sqrt(E/rho) / (4 * L); rel(ms.Freq(2), ax) > 2e-3 {
		t.Errorf("axial mode %g Hz vs %g", ms.Freq(2), ax)
	}
	for _, i := range []int{0, 1, 3} {
		n := float64(i + 1)
		if i == 3 {
			n = 3
		}
		want := n * n * math.Pi * math.Pi * math.Sqrt(E*I/(mu*math.Pow(L, 4))) / (2 * math.Pi)
		if rel(ms.Freq(i), want) > 2e-3 {
			t.Errorf("pinned-pinned mode %d: %g vs %g", i+1, ms.Freq(i), want)
		}
	}
	nodensity := NewFrame()
	nodensity.AddNode(0, 0)
	nodensity.AddNode(1, 0)
	nodensity.AddMember(Member{N1: 0, N2: 1, E: 1, A: 1, I: 1})
	nodensity.Fix(0, 0)
	if _, _, err := nodensity.FrameModes(1); err == nil {
		t.Error("missing density must be reported")
	}
}

func TestSolidModesMatchBeamTheory(t *testing.T) {
	E, rho, L, h := 200e9, 7850.0, 1.0, 0.1
	mat := Material{E: E, Nu: 0.3, Thickness: 0.05, Rho: rho}
	m, _ := Rect(0, 0, L, h, 30, 3, Tri6)
	md := NewModel(m, mat)
	for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
		md.FixDOF(n, 0, 0)
		md.FixDOF(n, 1, 0)
	}
	ms, free, err := md.SolidModes(2)
	if err != nil {
		t.Fatal(err)
	}
	I := mat.Thickness * h * h * h / 12
	mu := rho * mat.Thickness * h
	want := 1.875104069 * 1.875104069 * math.Sqrt(E*I/(mu*math.Pow(L, 4))) / (2 * math.Pi)
	if rel(ms.Freq(0), want) > 0.015 { // Timoshenko effects lower the 2-D value ~0.5%
		t.Errorf("plate fundamental %g Hz vs EB beam %g Hz", ms.Freq(0), want)
	}
	if len(free) != len(ms.Shapes[0]) {
		t.Error("free-dof map mismatch")
	}
	// mass-orthonormality of the returned shapes
	K, _ := md.AssembleK()
	M, _ := AssembleMass(m, mat)
	mr, _ := ReduceMatrix(M, md.Fixed)
	_ = K
	y := make([]float64, mr.N)
	mr.MulVec(ms.Shapes[1], y)
	if math.Abs(Dot(ms.Shapes[0], y)) > 1e-9 || math.Abs(Dot(ms.Shapes[1], y)-1) > 1e-9 {
		t.Errorf("modes not M-orthonormal: %g %g", Dot(ms.Shapes[0], y), Dot(ms.Shapes[1], y))
	}
	md0 := NewModel(m, Material{E: E, Nu: 0.3, Thickness: 1})
	md0.FixDOF(0, 0, 0)
	if _, _, err := md0.SolidModes(1); err == nil {
		t.Error("zero density must error")
	}
}

func TestHeatSlabAndAnnulus(t *testing.T) {
	m, _ := Rect(0, 0, 4, 1, 8, 2, Quad4)
	h := NewHeatModel(m, Material{E: 1, Nu: 0, Thickness: 1, Cond: 2})
	for _, n := range m.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
		h.Fixed[n] = 100
	}
	for _, n := range m.NodesWhere(func(x, y float64) bool { return x > 4-1e-12 }) {
		h.Fixed[n] = 20
	}
	T, err := h.Solve(SolverDirect)
	if err != nil {
		t.Fatal(err)
	}
	for i := range T {
		if math.Abs(T[i]-(100-20*m.X[i])) > 1e-9 {
			t.Fatalf("slab T[%d]=%g want %g", i, T[i], 100-20*m.X[i])
		}
	}
	// radial conduction: T(r) = Ti + (To-Ti) ln(r/a)/ln(b/a)
	a, b := 1.0, 3.0
	am, _ := Annulus(a, b, 12, 8, Tri6)
	ha := NewHeatModel(am, Material{E: 1, Nu: 0, Thickness: 1, Cond: 5})
	for _, n := range am.NodesWhere(func(x, y float64) bool { return math.Hypot(x, y) < a+1e-9 }) {
		ha.Fixed[n] = 200
	}
	for _, n := range am.NodesWhere(func(x, y float64) bool { return math.Hypot(x, y) > b-1e-9 }) {
		ha.Fixed[n] = 50
	}
	Ta, err := ha.Solve(SolverCGIC0)
	if err != nil {
		t.Fatal(err)
	}
	worst := 0.0
	for i := range Ta {
		r := math.Hypot(am.X[i], am.Y[i])
		want := 200 + (50-200)*math.Log(r/a)/math.Log(b/a)
		worst = math.Max(worst, math.Abs(Ta[i]-want))
	}
	if worst > 0.15 {
		t.Errorf("annulus worst temperature error %g K", worst)
	}
	// energy balance: uniform flux in, fixed temp out; a 1-D bar with source s, T(0)=0 fixed,
	// flux q at the far end: T(x) = (q x + s(Lx - x²/2))/k
	bar, _ := Rect(0, 0, 2, 0.5, 8, 2, Tri6)
	hb := NewHeatModel(bar, Material{E: 1, Nu: 0, Thickness: 1, Cond: 4})
	for _, n := range bar.NodesWhere(func(x, y float64) bool { return x < 1e-12 }) {
		hb.Fixed[n] = 0
	}
	for _, e := range bar.EdgesWhere(func(x1, y1, x2, y2 float64) bool { return x1 > 2-1e-12 && x2 > 2-1e-12 }) {
		hb.EdgeFlux(e, 3)
	}
	hb.Source(1.5)
	Tb, err := hb.Solve(SolverDirect)
	if err != nil {
		t.Fatal(err)
	}
	for i := range Tb {
		x := bar.X[i]
		want := (3*x + 1.5*(2*x-x*x/2)) / 4
		if math.Abs(Tb[i]-want) > 1e-9 {
			t.Fatalf("source/flux bar T(%g)=%g want %g", x, Tb[i], want)
		}
	}
	if _, err := NewHeatModel(m, Material{Cond: 1, Thickness: 1}).Solve(SolverDirect); err == nil {
		t.Error("no BC must error")
	}
}

func TestTopologyOptimisation(t *testing.T) {
	var changes int
	r, err := OptimizeTopology(TopOptParams{Case: CaseMBB, NX: 30, NY: 10, VolFrac: 0.5, Penal: 3, RMin: 1.5, MaxIter: 60, Tol: 0.01, SnapEvery: 20},
		func(it int, c, v, ch float64) { changes++ })
	if err != nil {
		t.Fatal(err)
	}
	last := r.Compl[len(r.Compl)-1]
	if last > r.Initial/3 {
		t.Errorf("optimised compliance %g vs uniform %g: expected >3x improvement", last, r.Initial)
	}
	if math.Abs(r.Vol[len(r.Vol)-1]-0.5) > 2e-3 {
		t.Errorf("volume constraint violated: %g", r.Vol[len(r.Vol)-1])
	}
	for _, v := range r.Rho {
		if v < -1e-9 || v > 1+1e-9 || math.IsNaN(v) {
			t.Fatalf("density out of bounds: %g", v)
		}
	}
	if changes != r.Iters || len(r.Snaps) < 2 {
		t.Errorf("progress/snapshot bookkeeping off: %d callbacks, %d iters, %d snaps", changes, r.Iters, len(r.Snaps))
	}
	// the final design must be better than a uniform-density plate of equal volume under the true (penalised) model
	for _, c := range []TopOptCase{CaseCantilever, CaseBridge} {
		r2, err := OptimizeTopology(TopOptParams{Case: c, NX: 24, NY: 12, VolFrac: 0.4, Penal: 3, RMin: 1.5, MaxIter: 25}, nil)
		if err != nil || r2.Compl[len(r2.Compl)-1] >= r2.Initial {
			t.Errorf("%s: no improvement (%v)", c, err)
		}
	}
	bad := []TopOptParams{{Case: CaseMBB, NX: 2, NY: 2, VolFrac: .5, Penal: 3, RMin: 1.5, MaxIter: 5},
		{Case: CaseMBB, NX: 20, NY: 10, VolFrac: 1.5, Penal: 3, RMin: 1.5, MaxIter: 5},
		{Case: CaseMBB, NX: 20, NY: 10, VolFrac: .5, Penal: 3, RMin: 0.4, MaxIter: 5},
		{Case: "zzz", NX: 20, NY: 10, VolFrac: .5, Penal: 3, RMin: 1.5, MaxIter: 5}}
	for _, p := range bad {
		if _, err := OptimizeTopology(p, nil); err == nil {
			t.Errorf("params %+v should be rejected", p)
		}
	}
}
