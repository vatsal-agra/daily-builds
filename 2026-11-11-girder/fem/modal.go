package fem

import (
	"fmt"
	"math"
	"sort"
)

// ReduceMatrix removes constrained rows/columns, returning the reduced matrix and the free-dof list.
func ReduceMatrix(a *CSR, fixed map[int]float64) (*CSR, []int) {
	idx := make([]int, a.N)
	var free []int
	for i := 0; i < a.N; i++ {
		if _, ok := fixed[i]; ok {
			idx[i] = -1
		} else {
			idx[i] = len(free)
			free = append(free, i)
		}
	}
	t := NewTriplets(len(free))
	for k, i := range free {
		for p := a.RowPtr[i]; p < a.RowPtr[i+1]; p++ {
			if j := idx[a.Col[p]]; j >= 0 {
				t.I = append(t.I, k)
				t.J = append(t.J, j)
				t.V = append(t.V, a.Val[p])
			}
		}
	}
	return t.ToCSR(), free
}

// denseCholesky returns lower L with A = L L^T.
func denseCholesky(a *Dense) (*Dense, error) {
	n := a.R
	l := NewDense(n, n)
	for i := 0; i < n; i++ {
		for j := 0; j <= i; j++ {
			s := a.At(i, j)
			for k := 0; k < j; k++ {
				s -= l.At(i, k) * l.At(j, k)
			}
			if i == j {
				if s <= 0 {
					return nil, fmt.Errorf("reduced mass matrix is not positive definite (is density set?)")
				}
				l.Set(i, i, math.Sqrt(s))
			} else {
				l.Set(i, j, s/l.At(j, j))
			}
		}
	}
	return l, nil
}

// ModeSet holds eigenvalues λ=ω² and mass-normalised mode shapes on the reduced dofs.
type ModeSet struct {
	Omega2 []float64
	Shapes [][]float64
	Iters  int
}

// Freq returns the frequency in Hz of mode i.
func (m *ModeSet) Freq(i int) float64 { return math.Sqrt(math.Max(m.Omega2[i], 0)) / (2 * math.Pi) }

// SolveModes finds the lowest nModes eigenpairs of K φ = λ M φ (K SPD, M SPD) by shift-invert
// subspace iteration with Rayleigh–Ritz.
func SolveModes(K, M *CSR, nModes int) (*ModeSet, error) {
	n := K.N
	if nModes < 1 {
		return nil, fmt.Errorf("need at least one mode")
	}
	if n == 0 {
		return nil, fmt.Errorf("no free degrees of freedom")
	}
	if nModes > n {
		nModes = n
	}
	q := min(n, max(2*nModes, nModes+8))
	perm := K.RCM()
	fac, err := FactorSkyline(K.Permute(perm))
	if err != nil {
		return nil, err
	}
	solveK := func(b []float64) []float64 {
		pb := make([]float64, n)
		for ni, old := range perm {
			pb[ni] = b[old]
		}
		px := fac.Solve(pb)
		x := make([]float64, n)
		for ni, old := range perm {
			x[old] = px[ni]
		}
		return x
	}
	// deterministic start vectors
	X := make([][]float64, q)
	for k := range X {
		X[k] = make([]float64, n)
		for i := range X[k] {
			X[k][i] = math.Sin(float64((i+1)*(k+1))*0.7311) + 0.1*math.Cos(float64(i*(k+3))*1.17)
		}
	}
	mv := func(v []float64) []float64 { o := make([]float64, n); M.MulVec(v, o); return o }
	kv := func(v []float64) []float64 { o := make([]float64, n); K.MulVec(v, o); return o }
	var lam []float64
	var shapes [][]float64
	prev := make([]float64, nModes)
	const maxIter = 200
	for it := 1; it <= maxIter; it++ {
		// inverse iteration step: X <- K^-1 M X
		for k := range X {
			X[k] = solveK(mv(X[k]))
		}
		// Rayleigh–Ritz: Kr = XᵀKX, Mr = XᵀMX
		kr, mr := NewDense(q, q), NewDense(q, q)
		KX := make([][]float64, q)
		MX := make([][]float64, q)
		for k := range X {
			KX[k], MX[k] = kv(X[k]), mv(X[k])
		}
		for a := 0; a < q; a++ {
			for b := a; b < q; b++ {
				kr.Set(a, b, Dot(X[a], KX[b]))
				kr.Set(b, a, kr.At(a, b))
				mr.Set(a, b, Dot(X[a], MX[b]))
				mr.Set(b, a, mr.At(a, b))
			}
		}
		L, err := denseCholesky(mr)
		if err != nil {
			return nil, err
		}
		// C = L^-1 Kr L^-T
		C := NewDense(q, q)
		tmp := NewDense(q, q)
		for c := 0; c < q; c++ { // tmp = L^-1 Kr (forward solve per column)
			for r := 0; r < q; r++ {
				s := kr.At(r, c)
				for k := 0; k < r; k++ {
					s -= L.At(r, k) * tmp.At(k, c)
				}
				tmp.Set(r, c, s/L.At(r, r))
			}
		}
		for r := 0; r < q; r++ { // C = tmp L^-T  => solve C L^T = tmp row-wise
			for c := 0; c < q; c++ {
				s := tmp.At(r, c)
				for k := 0; k < c; k++ {
					s -= C.At(r, k) * L.At(c, k)
				}
				C.Set(r, c, s/L.At(c, c))
			}
		}
		for i := 0; i < q; i++ { // symmetrise round-off
			for j := i + 1; j < q; j++ {
				v := (C.At(i, j) + C.At(j, i)) / 2
				C.Set(i, j, v)
				C.Set(j, i, v)
			}
		}
		w, V := SymEigen(C)
		// Ritz vectors: y = L^-T V ; X_new = X y
		newX := make([][]float64, q)
		for k := 0; k < q; k++ {
			y := make([]float64, q)
			for r := q - 1; r >= 0; r-- {
				s := V.At(r, k)
				for j := r + 1; j < q; j++ {
					s -= L.At(j, r) * y[j]
				}
				y[r] = s / L.At(r, r)
			}
			v := make([]float64, n)
			for a := 0; a < q; a++ {
				for i := range v {
					v[i] += y[a] * X[a][i]
				}
			}
			newX[k] = v
		}
		X = newX
		lam, shapes = w[:nModes], X[:nModes]
		maxd := 0.0
		for k := 0; k < nModes; k++ {
			maxd = math.Max(maxd, math.Abs(lam[k]-prev[k])/math.Max(lam[k], 1e-300))
		}
		copy(prev, lam)
		if it > 2 && maxd < 1e-12 {
			return &ModeSet{Omega2: append([]float64(nil), lam...), Shapes: shapes, Iters: it}, nil
		}
	}
	return nil, fmt.Errorf("subspace iteration did not converge in %d iterations", maxIter)
}

// AssembleMass assembles the consistent mass matrix for a solid mesh.
func AssembleMass(m *Mesh, mat Material) (*CSR, error) {
	if !(mat.Rho > 0) {
		return nil, fmt.Errorf("density must be > 0 for dynamic analysis: add rho= to `material`")
	}
	t := NewTriplets(2 * m.NumNodes())
	for e := range m.Conn {
		xs, ys := m.ElemCoords(e)
		me, err := Mass(m.Type, xs, ys, mat)
		if err != nil {
			return nil, fmt.Errorf("element %d: %w", e, err)
		}
		d := dofsOf(m.Conn[e])
		for i := range d {
			for j := range d {
				t.Add(d[i], d[j], me[i*len(d)+j])
			}
		}
	}
	return t.ToCSR(), nil
}

// SolidModes computes the lowest natural frequencies of a constrained solid model.
func (md *Model) SolidModes(n int) (*ModeSet, []int, error) {
	if len(md.Fixed) == 0 {
		return nil, nil, fmt.Errorf("model has no supports: free-free modes are not supported (rigid-body modes have zero frequency)")
	}
	K, err := md.AssembleK()
	if err != nil {
		return nil, nil, err
	}
	M, err := AssembleMass(md.Mesh, md.Mat)
	if err != nil {
		return nil, nil, err
	}
	kr, free := ReduceMatrix(K, md.Fixed)
	mr, _ := ReduceMatrix(M, md.Fixed)
	ms, err := SolveModes(kr, mr, n)
	return ms, free, err
}

// FrameModes computes the lowest natural frequencies of a frame (members need rho=).
func (f *Frame) FrameModes(n int) (*ModeSet, []int, error) {
	for i, m := range f.Members {
		if !(m.Rho > 0) {
			return nil, nil, fmt.Errorf("member %d has no density: add rho= to every beam/bar for modal analysis", i)
		}
	}
	fixed := f.pinnedRotations()
	for k, v := range f.Fixed {
		fixed[k] = v
	}
	if len(f.Fixed) == 0 {
		return nil, nil, fmt.Errorf("frame has no supports")
	}
	kr, free := ReduceMatrix(f.Assemble(false), fixed)
	mr, _ := ReduceMatrix(f.Assemble(true), fixed)
	ms, err := SolveModes(kr, mr, n)
	return ms, free, err
}

// ExpandMode scatters a reduced mode shape back to all dofs.
func ExpandMode(shape []float64, free []int, n int) []float64 {
	u := make([]float64, n)
	for k, d := range free {
		u[d] = shape[k]
	}
	return u
}

// ModalReport renders frequencies and mode shapes. Exactly one of md/fr must be set.
func ModalReport(title string, md *Model, fr *Frame, ms *ModeSet, free []int) string {
	var b stringsBuilder
	b.w(`<div class="grid">` + stat("modes", fmt.Sprint(len(ms.Omega2))) + stat("fundamental", fmt.Sprintf("%.4g Hz", ms.Freq(0))) + stat("subspace iterations", fmt.Sprint(ms.Iters)) + `</div><div class="panels">`)
	idx := make([]int, len(ms.Omega2))
	for i := range idx {
		idx[i] = i
	}
	sort.Ints(idx)
	for _, k := range idx {
		cap := fmt.Sprintf("Mode %d — %.5g Hz<small>ω² = %.6g</small>", k+1, ms.Freq(k), ms.Omega2[k])
		if md != nil {
			u := ExpandMode(ms.Shapes[k], free, 2*md.Mesh.NumNodes())
			mag := make([]float64, md.Mesh.NumNodes())
			mx := 0.0
			for i := range mag {
				mag[i] = math.Hypot(u[2*i], u[2*i+1])
				mx = math.Max(mx, mag[i])
			}
			x0, y0, x1, y1 := md.Mesh.Bounds()
			sc := 0.15 * math.Max(x1-x0, y1-y0) / mx
			b.w(`<figure><figcaption>` + cap + `</figcaption>` + ContourSVG(md.Mesh, u, mag, ContourOpts{Width: 560, DeformScale: sc, Title: cap, Unit: "|φ| (normalised)"}) + `</figure>`)
		} else {
			u := ExpandMode(ms.Shapes[k], free, 3*len(fr.X))
			mx := 0.0
			for n := range fr.X {
				mx = math.Max(mx, math.Hypot(u[3*n], u[3*n+1]))
			}
			x0, x1, y0, y1 := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
			for i := range fr.X {
				x0, x1, y0, y1 = math.Min(x0, fr.X[i]), math.Max(x1, fr.X[i]), math.Min(y0, fr.Y[i]), math.Max(y1, fr.Y[i])
			}
			sc := 0.15 * math.Max(x1-x0, y1-y0) / mx
			sol := &FrameSolution{U: u, EndForces: make([][6]float64, len(fr.Members))}
			b.w(`<figure><figcaption>` + cap + `</figcaption>` + FrameSVG(fr, sol, sc, 560, false) + `</figure>`)
		}
	}
	b.w(`</div>`)
	return Page(title, "Girder modal analysis — consistent mass, shift-invert subspace iteration", b.String())
}
