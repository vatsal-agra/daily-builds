package fem

import (
	"errors"
	"math"
)

// Dense is a small row-major dense matrix.
type Dense struct {
	R, C int
	A    []float64
}

func NewDense(r, c int) *Dense           { return &Dense{R: r, C: c, A: make([]float64, r*c)} }
func (m *Dense) At(i, j int) float64     { return m.A[i*m.C+j] }
func (m *Dense) Set(i, j int, v float64) { m.A[i*m.C+j] = v }
func (m *Dense) Add(i, j int, v float64) { m.A[i*m.C+j] += v }

// MulVec returns m*x.
func (m *Dense) MulVec(x []float64) []float64 {
	y := make([]float64, m.R)
	for i := 0; i < m.R; i++ {
		s := 0.0
		for j := 0; j < m.C; j++ {
			s += m.A[i*m.C+j] * x[j]
		}
		y[i] = s
	}
	return y
}

// SolveDense solves A x = b by LU with partial pivoting (A is not modified).
func SolveDense(a *Dense, b []float64) ([]float64, error) {
	n := a.R
	if a.C != n || len(b) != n {
		return nil, errors.New("SolveDense: shape mismatch")
	}
	m := make([]float64, len(a.A))
	copy(m, a.A)
	x := append([]float64(nil), b...)
	for k := 0; k < n; k++ {
		p, pv := k, math.Abs(m[k*n+k])
		for i := k + 1; i < n; i++ {
			if v := math.Abs(m[i*n+k]); v > pv {
				p, pv = i, v
			}
		}
		if pv < 1e-300 {
			return nil, errors.New("SolveDense: singular matrix")
		}
		if p != k {
			for j := 0; j < n; j++ {
				m[k*n+j], m[p*n+j] = m[p*n+j], m[k*n+j]
			}
			x[k], x[p] = x[p], x[k]
		}
		for i := k + 1; i < n; i++ {
			f := m[i*n+k] / m[k*n+k]
			if f == 0 {
				continue
			}
			for j := k; j < n; j++ {
				m[i*n+j] -= f * m[k*n+j]
			}
			x[i] -= f * x[k]
		}
	}
	for i := n - 1; i >= 0; i-- {
		s := x[i]
		for j := i + 1; j < n; j++ {
			s -= m[i*n+j] * x[j]
		}
		x[i] = s / m[i*n+i]
	}
	return x, nil
}

// Inverse2 returns det and inverse of a 2x2 matrix [[a b][c d]] given as 4 values.
func Inverse2(a, b, c, d float64) (det, ia, ib, ic, id float64) {
	det = a*d - b*c
	return det, d / det, -b / det, -c / det, a / det
}

// SymEigen computes all eigenvalues/vectors of a symmetric matrix with the cyclic Jacobi method.
// Returns eigenvalues ascending and eigenvectors as columns of v (v.At(i,k) = component i of vector k).
func SymEigen(a *Dense) ([]float64, *Dense) {
	n := a.R
	m := NewDense(n, n)
	copy(m.A, a.A)
	v := NewDense(n, n)
	for i := 0; i < n; i++ {
		v.Set(i, i, 1)
	}
	for sweep := 0; sweep < 100; sweep++ {
		off := 0.0
		for i := 0; i < n; i++ {
			for j := i + 1; j < n; j++ {
				off += m.At(i, j) * m.At(i, j)
			}
		}
		if off < 1e-28 {
			break
		}
		for p := 0; p < n; p++ {
			for q := p + 1; q < n; q++ {
				apq := m.At(p, q)
				if math.Abs(apq) < 1e-300 {
					continue
				}
				theta := (m.At(q, q) - m.At(p, p)) / (2 * apq)
				t := 1 / (math.Abs(theta) + math.Sqrt(theta*theta+1))
				if theta < 0 {
					t = -t
				}
				c := 1 / math.Sqrt(t*t+1)
				s := t * c
				for k := 0; k < n; k++ {
					akp, akq := m.At(k, p), m.At(k, q)
					m.Set(k, p, c*akp-s*akq)
					m.Set(k, q, s*akp+c*akq)
				}
				for k := 0; k < n; k++ {
					apk, aqk := m.At(p, k), m.At(q, k)
					m.Set(p, k, c*apk-s*aqk)
					m.Set(q, k, s*apk+c*aqk)
				}
				for k := 0; k < n; k++ {
					vkp, vkq := v.At(k, p), v.At(k, q)
					v.Set(k, p, c*vkp-s*vkq)
					v.Set(k, q, s*vkp+c*vkq)
				}
			}
		}
	}
	idx := make([]int, n)
	for i := range idx {
		idx[i] = i
	}
	for i := 1; i < n; i++ { // insertion sort by eigenvalue
		for j := i; j > 0 && m.At(idx[j], idx[j]) < m.At(idx[j-1], idx[j-1]); j-- {
			idx[j], idx[j-1] = idx[j-1], idx[j]
		}
	}
	w := make([]float64, n)
	vs := NewDense(n, n)
	for k, o := range idx {
		w[k] = m.At(o, o)
		for i := 0; i < n; i++ {
			vs.Set(i, k, v.At(i, o))
		}
	}
	return w, vs
}

func Dot(a, b []float64) float64 {
	s := 0.0
	for i := range a {
		s += a[i] * b[i]
	}
	return s
}
func Norm(a []float64) float64 { return math.Sqrt(Dot(a, a)) }
