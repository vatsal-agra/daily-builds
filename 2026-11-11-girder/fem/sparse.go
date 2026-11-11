package fem

import (
	"errors"
	"fmt"
	"math"
	"sort"
)

// Triplets accumulates (i,j,v) entries; duplicates are summed on conversion.
type Triplets struct {
	N    int
	I, J []int
	V    []float64
}

func NewTriplets(n int) *Triplets { return &Triplets{N: n} }
func (t *Triplets) Add(i, j int, v float64) {
	if v == 0 {
		return
	}
	t.I = append(t.I, i)
	t.J = append(t.J, j)
	t.V = append(t.V, v)
}

// CSR is a compressed-sparse-row square matrix.
type CSR struct {
	N      int
	RowPtr []int
	Col    []int
	Val    []float64
}

// ToCSR converts triplets to CSR, summing duplicates and sorting columns.
func (t *Triplets) ToCSR() *CSR {
	n := t.N
	cnt := make([]int, n+1)
	for _, i := range t.I {
		cnt[i+1]++
	}
	for i := 0; i < n; i++ {
		cnt[i+1] += cnt[i]
	}
	col := make([]int, len(t.I))
	val := make([]float64, len(t.I))
	next := append([]int(nil), cnt[:n]...)
	for k := range t.I {
		p := next[t.I[k]]
		next[t.I[k]]++
		col[p], val[p] = t.J[k], t.V[k]
	}
	m := &CSR{N: n, RowPtr: make([]int, n+1)}
	for i := 0; i < n; i++ {
		lo, hi := cnt[i], cnt[i+1]
		seg := make([]int, hi-lo)
		for k := range seg {
			seg[k] = lo + k
		}
		sort.Slice(seg, func(a, b int) bool { return col[seg[a]] < col[seg[b]] })
		last := -1
		for _, p := range seg {
			if col[p] == last {
				m.Val[len(m.Val)-1] += val[p]
			} else {
				m.Col = append(m.Col, col[p])
				m.Val = append(m.Val, val[p])
				last = col[p]
			}
		}
		m.RowPtr[i+1] = len(m.Col)
	}
	return m
}

func (m *CSR) NNZ() int { return len(m.Val) }

func (m *CSR) MulVec(x, y []float64) {
	for i := 0; i < m.N; i++ {
		s := 0.0
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			s += m.Val[p] * x[m.Col[p]]
		}
		y[i] = s
	}
}

func (m *CSR) Diag() []float64 {
	d := make([]float64, m.N)
	for i := 0; i < m.N; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if m.Col[p] == i {
				d[i] = m.Val[p]
			}
		}
	}
	return d
}

// IsSymmetric reports max |a_ij - a_ji| relative to max |a_ij|.
func (m *CSR) AsymmetryRatio() float64 {
	get := func(i, j int) float64 {
		lo, hi := m.RowPtr[i], m.RowPtr[i+1]
		k := lo + sort.SearchInts(m.Col[lo:hi], j)
		if k < hi && m.Col[k] == j {
			return m.Val[k]
		}
		return 0
	}
	mx, as := 0.0, 0.0
	for i := 0; i < m.N; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			mx = math.Max(mx, math.Abs(m.Val[p]))
			as = math.Max(as, math.Abs(m.Val[p]-get(m.Col[p], i)))
		}
	}
	if mx == 0 {
		return 0
	}
	return as / mx
}

// Permute returns P A P^T where new index of old i is inv[i] (perm[new]=old).
func (m *CSR) Permute(perm []int) *CSR {
	inv := make([]int, m.N)
	for newi, old := range perm {
		inv[old] = newi
	}
	t := NewTriplets(m.N)
	for i := 0; i < m.N; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			t.I = append(t.I, inv[i])
			t.J = append(t.J, inv[m.Col[p]])
			t.V = append(t.V, m.Val[p])
		}
	}
	return t.ToCSR()
}

// RCM computes a reverse Cuthill–McKee ordering (perm[new]=old) handling disconnected graphs.
func (m *CSR) RCM() []int {
	n := m.N
	deg := make([]int, n)
	for i := 0; i < n; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if m.Col[p] != i {
				deg[i]++
			}
		}
	}
	visited := make([]bool, n)
	order := make([]int, 0, n)
	// start vertices sorted by degree for determinism
	starts := make([]int, n)
	for i := range starts {
		starts[i] = i
	}
	sort.SliceStable(starts, func(a, b int) bool { return deg[starts[a]] < deg[starts[b]] })
	for _, s := range starts {
		if visited[s] {
			continue
		}
		visited[s] = true
		queue := []int{s}
		for len(queue) > 0 {
			v := queue[0]
			queue = queue[1:]
			order = append(order, v)
			var nb []int
			for p := m.RowPtr[v]; p < m.RowPtr[v+1]; p++ {
				w := m.Col[p]
				if !visited[w] {
					visited[w] = true
					nb = append(nb, w)
				}
			}
			sort.SliceStable(nb, func(a, b int) bool { return deg[nb[a]] < deg[nb[b]] })
			queue = append(queue, nb...)
		}
	}
	for i, j := 0, n-1; i < j; i, j = i+1, j-1 {
		order[i], order[j] = order[j], order[i]
	}
	return order
}

// Bandwidth returns the half-bandwidth of the matrix.
func (m *CSR) Bandwidth() int {
	b := 0
	for i := 0; i < m.N; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if d := i - m.Col[p]; d > b {
				b = d
			}
		}
	}
	return b
}

// Skyline is a variable-band (envelope) Cholesky factorisation A = L L^T.
type Skyline struct {
	N     int
	First []int     // first nonzero column of row i (lower triangle)
	Ptr   []int     // start of row i in Val
	Val   []float64 // L entries row-wise from First[i]..i
}

var ErrNotSPD = errors.New("matrix is not symmetric positive definite (mechanism or missing supports?)")

// MaxSkylineEntries bounds the direct solver's factor storage (entries, 8 bytes each).
var MaxSkylineEntries = 150_000_000

// SingularError reports the (reduced-system) row at which factorisation lost positive definiteness.
type SingularError struct {
	Row   int
	Pivot float64
}

func (e *SingularError) Error() string {
	return fmt.Sprintf("%s (pivot %d = %.3e)", ErrNotSPD.Error(), e.Row, e.Pivot)
}
func (e *SingularError) Unwrap() error { return ErrNotSPD }

// ErrTooLarge means the direct factorisation would not fit in memory.
var ErrTooLarge = errors.New("direct factorisation would need too much memory; use the cg-ic0 solver")

// FactorSkyline factorises the SPD matrix m (should be RCM-ordered for speed).
func FactorSkyline(m *CSR) (*Skyline, error) {
	n := m.N
	s := &Skyline{N: n, First: make([]int, n), Ptr: make([]int, n+1)}
	for i := 0; i < n; i++ {
		f := i
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if m.Col[p] < f {
				f = m.Col[p]
			}
		}
		s.First[i] = f
		s.Ptr[i+1] = s.Ptr[i] + (i - f + 1)
	}
	if s.Ptr[n] > MaxSkylineEntries {
		return nil, fmt.Errorf("%w (%d factor entries)", ErrTooLarge, s.Ptr[n])
	}
	s.Val = make([]float64, s.Ptr[n])
	for i := 0; i < n; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if j := m.Col[p]; j <= i {
				s.Val[s.Ptr[i]+j-s.First[i]] = m.Val[p]
			}
		}
	}
	diag := m.Diag() // pivots are judged against each row's own diagonal (scale-invariant)
	for i := 0; i < n; i++ {
		fi := s.First[i]
		for j := fi; j <= i; j++ {
			fj := s.First[j]
			lo := fi
			if fj > lo {
				lo = fj
			}
			sum := s.Val[s.Ptr[i]+j-fi]
			ri, rj := s.Ptr[i]-fi, s.Ptr[j]-fj
			for k := lo; k < j; k++ {
				sum -= s.Val[ri+k] * s.Val[rj+k]
			}
			if j == i {
				if sum <= 1e-12*diag[i] {
					return nil, &SingularError{Row: i, Pivot: sum}
				}
				s.Val[s.Ptr[i]+i-fi] = math.Sqrt(sum)
			} else {
				s.Val[s.Ptr[i]+j-fi] = sum / s.Val[s.Ptr[j]+j-fj]
			}
		}
	}
	return s, nil
}

// Solve solves L L^T x = b.
func (s *Skyline) Solve(b []float64) []float64 {
	n := s.N
	x := append([]float64(nil), b...)
	for i := 0; i < n; i++ {
		fi := s.First[i]
		sum := x[i]
		r := s.Ptr[i] - fi
		for k := fi; k < i; k++ {
			sum -= s.Val[r+k] * x[k]
		}
		x[i] = sum / s.Val[r+i]
	}
	for j := n - 1; j >= 0; j-- {
		fj := s.First[j]
		r := s.Ptr[j] - fj
		x[j] /= s.Val[r+j]
		for k := fj; k < j; k++ {
			x[k] -= s.Val[r+k] * x[j]
		}
	}
	return x
}

// Storage is the number of stored factor entries.
func (s *Skyline) Storage() int { return len(s.Val) }

// IC0 is an incomplete Cholesky factor with the sparsity pattern of the lower triangle of A.
type IC0 struct {
	n      int
	rowPtr []int
	col    []int
	val    []float64 // lower triangle incl. diagonal (diag is last in each row)
}

// NewIC0 builds IC(0), adding a diagonal shift if breakdown occurs.
func NewIC0(m *CSR) *IC0 {
	shift := 0.0
	for attempt := 0; attempt < 30; attempt++ {
		if f, ok := tryIC0(m, shift); ok {
			return f
		}
		if shift == 0 {
			shift = 1e-4
		} else {
			shift *= 2
		}
	}
	return nil
}

func tryIC0(m *CSR, shift float64) (*IC0, bool) {
	n := m.N
	f := &IC0{n: n, rowPtr: make([]int, n+1)}
	for i := 0; i < n; i++ {
		for p := m.RowPtr[i]; p < m.RowPtr[i+1]; p++ {
			if m.Col[p] <= i {
				f.col = append(f.col, m.Col[p])
				v := m.Val[p]
				if m.Col[p] == i {
					v *= 1 + shift
				}
				f.val = append(f.val, v)
			}
		}
		f.rowPtr[i+1] = len(f.col)
	}
	diagPos := make([]int, n)
	for i := 0; i < n; i++ {
		diagPos[i] = f.rowPtr[i+1] - 1
		if f.col[diagPos[i]] != i {
			return nil, false
		}
	}
	for i := 0; i < n; i++ {
		for p := f.rowPtr[i]; p < f.rowPtr[i+1]; p++ {
			j := f.col[p]
			sum := f.val[p]
			// sparse dot of row i and row j over k<j
			a, b := f.rowPtr[i], f.rowPtr[j]
			for a < p && b < diagPos[j] {
				ca, cb := f.col[a], f.col[b]
				switch {
				case ca == cb:
					sum -= f.val[a] * f.val[b]
					a++
					b++
				case ca < cb:
					a++
				default:
					b++
				}
			}
			if j == i {
				if sum <= 0 {
					return nil, false
				}
				f.val[p] = math.Sqrt(sum)
			} else {
				f.val[p] = sum / f.val[diagPos[j]]
			}
		}
	}
	return f, true
}

// Apply computes z = (L L^T)^{-1} r.
func (f *IC0) Apply(r, z []float64) {
	n := f.n
	for i := 0; i < n; i++ {
		s := r[i]
		d := f.rowPtr[i+1] - 1
		for p := f.rowPtr[i]; p < d; p++ {
			s -= f.val[p] * z[f.col[p]]
		}
		z[i] = s / f.val[d]
	}
	for j := n - 1; j >= 0; j-- {
		d := f.rowPtr[j+1] - 1
		z[j] /= f.val[d]
		// column j of L^T == row j of L: update earlier entries
		for p := f.rowPtr[j]; p < d; p++ {
			z[f.col[p]] -= f.val[p] * z[j]
		}
	}
}

// Preconditioner kinds for PCG.
type Precond int

const (
	PrecNone Precond = iota
	PrecJacobi
	PrecIC0
)

func (p Precond) String() string { return [...]string{"none", "jacobi", "ic0"}[p] }

// CGResult reports iterative-solver statistics.
type CGResult struct {
	Iters     int
	Residual  float64 // final relative residual
	Converged bool
}

// PCG solves A x = b for SPD A.
func PCG(a *CSR, b []float64, prec Precond, tol float64, maxIter int) ([]float64, CGResult) {
	n := a.N
	x := make([]float64, n)
	r := append([]float64(nil), b...)
	bn := Norm(b)
	if bn == 0 {
		return x, CGResult{Converged: true}
	}
	var ic *IC0
	var dinv []float64
	switch prec {
	case PrecJacobi:
		dinv = a.Diag()
		for i := range dinv {
			dinv[i] = 1 / dinv[i]
		}
	case PrecIC0:
		ic = NewIC0(a)
	}
	z := make([]float64, n)
	apply := func() {
		switch {
		case ic != nil:
			ic.Apply(r, z)
		case dinv != nil:
			for i := range z {
				z[i] = dinv[i] * r[i]
			}
		default:
			copy(z, r)
		}
	}
	apply()
	p := append([]float64(nil), z...)
	rz := Dot(r, z)
	ap := make([]float64, n)
	for it := 1; it <= maxIter; it++ {
		a.MulVec(p, ap)
		alpha := rz / Dot(p, ap)
		for i := 0; i < n; i++ {
			x[i] += alpha * p[i]
			r[i] -= alpha * ap[i]
		}
		rel := Norm(r) / bn
		if rel < tol {
			return x, CGResult{Iters: it, Residual: rel, Converged: true}
		}
		apply()
		rzNew := Dot(r, z)
		beta := rzNew / rz
		rz = rzNew
		for i := 0; i < n; i++ {
			p[i] = z[i] + beta*p[i]
		}
	}
	return x, CGResult{Iters: maxIter, Residual: Norm(r) / bn}
}

// SolveSPD solves with RCM + skyline Cholesky.
func SolveSPD(a *CSR, b []float64) ([]float64, error) {
	perm := a.RCM()
	ap := a.Permute(perm)
	f, err := FactorSkyline(ap)
	if err != nil {
		var se *SingularError
		if errors.As(err, &se) {
			se.Row = perm[se.Row] // report in the caller's numbering
		}
		return nil, err
	}
	pb := make([]float64, a.N)
	for newi, old := range perm {
		pb[newi] = b[old]
	}
	px := f.Solve(pb)
	x := make([]float64, a.N)
	for newi, old := range perm {
		x[old] = px[newi]
	}
	return x, nil
}
