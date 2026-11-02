// Package mat is a small dense-matrix library: just what a Kalman filter needs.
package mat

import (
	"errors"
	"fmt"
	"math"
)

// M is a row-major dense matrix.
type M struct {
	R, C int
	D    []float64
}

// ErrSingular is returned when a matrix cannot be inverted / factored.
var ErrSingular = errors.New("mat: matrix is singular or not positive definite")

func New(r, c int) *M { return &M{R: r, C: c, D: make([]float64, r*c)} }

func From(r, c int, d ...float64) *M {
	if len(d) != r*c {
		panic(fmt.Sprintf("mat.From: want %d values, got %d", r*c, len(d)))
	}
	m := New(r, c)
	copy(m.D, d)
	return m
}

func Eye(n int) *M {
	m := New(n, n)
	for i := 0; i < n; i++ {
		m.D[i*n+i] = 1
	}
	return m
}

func Diag(v ...float64) *M {
	m := New(len(v), len(v))
	for i, x := range v {
		m.D[i*len(v)+i] = x
	}
	return m
}

// Vec makes a column vector.
func Vec(v ...float64) *M { return From(len(v), 1, v...) }

func (m *M) At(i, j int) float64     { return m.D[i*m.C+j] }
func (m *M) Set(i, j int, v float64) { m.D[i*m.C+j] = v }
func (m *M) Clone() *M               { n := New(m.R, m.C); copy(n.D, m.D); return n }

func same(a, b *M, op string) {
	if a.R != b.R || a.C != b.C {
		panic(fmt.Sprintf("mat.%s: shape mismatch %dx%d vs %dx%d", op, a.R, a.C, b.R, b.C))
	}
}

func (a *M) Add(b *M) *M {
	same(a, b, "Add")
	n := New(a.R, a.C)
	for i := range n.D {
		n.D[i] = a.D[i] + b.D[i]
	}
	return n
}

func (a *M) Sub(b *M) *M {
	same(a, b, "Sub")
	n := New(a.R, a.C)
	for i := range n.D {
		n.D[i] = a.D[i] - b.D[i]
	}
	return n
}

func (a *M) Scale(s float64) *M {
	n := New(a.R, a.C)
	for i := range n.D {
		n.D[i] = a.D[i] * s
	}
	return n
}

func (a *M) Mul(b *M) *M {
	if a.C != b.R {
		panic(fmt.Sprintf("mat.Mul: inner dims %dx%d * %dx%d", a.R, a.C, b.R, b.C))
	}
	n := New(a.R, b.C)
	for i := 0; i < a.R; i++ {
		for k := 0; k < a.C; k++ {
			x := a.D[i*a.C+k]
			if x == 0 {
				continue
			}
			for j := 0; j < b.C; j++ {
				n.D[i*b.C+j] += x * b.D[k*b.C+j]
			}
		}
	}
	return n
}

func (a *M) T() *M {
	n := New(a.C, a.R)
	for i := 0; i < a.R; i++ {
		for j := 0; j < a.C; j++ {
			n.D[j*a.R+i] = a.D[i*a.C+j]
		}
	}
	return n
}

// Sym returns (A + Aᵀ)/2, used to stop covariance drifting asymmetric.
func (a *M) Sym() *M {
	n := New(a.R, a.C)
	for i := 0; i < a.R; i++ {
		for j := 0; j < a.C; j++ {
			n.D[i*a.C+j] = 0.5 * (a.D[i*a.C+j] + a.D[j*a.C+i])
		}
	}
	return n
}

func (a *M) Trace() float64 {
	t := 0.0
	for i := 0; i < a.R && i < a.C; i++ {
		t += a.D[i*a.C+i]
	}
	return t
}

// LU decomposes with partial pivoting; returns packed LU, permutation, and sign.
func (a *M) lu() (*M, []int, float64, error) {
	if a.R != a.C {
		return nil, nil, 0, errors.New("mat: LU of non-square matrix")
	}
	n := a.R
	lu := a.Clone()
	perm := make([]int, n)
	for i := range perm {
		perm[i] = i
	}
	sign := 1.0
	for k := 0; k < n; k++ {
		p, best := k, math.Abs(lu.D[k*n+k])
		for i := k + 1; i < n; i++ {
			if v := math.Abs(lu.D[i*n+k]); v > best {
				p, best = i, v
			}
		}
		if best < 1e-300 || math.IsNaN(best) {
			return nil, nil, 0, ErrSingular
		}
		if p != k {
			for j := 0; j < n; j++ {
				lu.D[k*n+j], lu.D[p*n+j] = lu.D[p*n+j], lu.D[k*n+j]
			}
			perm[k], perm[p] = perm[p], perm[k]
			sign = -sign
		}
		for i := k + 1; i < n; i++ {
			f := lu.D[i*n+k] / lu.D[k*n+k]
			lu.D[i*n+k] = f
			for j := k + 1; j < n; j++ {
				lu.D[i*n+j] -= f * lu.D[k*n+j]
			}
		}
	}
	return lu, perm, sign, nil
}

// Solve returns X with A·X = B.
func (a *M) Solve(b *M) (*M, error) {
	lu, perm, _, err := a.lu()
	if err != nil {
		return nil, err
	}
	n := a.R
	if b.R != n {
		panic("mat.Solve: row mismatch")
	}
	x := New(n, b.C)
	for c := 0; c < b.C; c++ {
		y := make([]float64, n)
		for i := 0; i < n; i++ {
			s := b.D[perm[i]*b.C+c]
			for j := 0; j < i; j++ {
				s -= lu.D[i*n+j] * y[j]
			}
			y[i] = s
		}
		for i := n - 1; i >= 0; i-- {
			s := y[i]
			for j := i + 1; j < n; j++ {
				s -= lu.D[i*n+j] * x.D[j*b.C+c]
			}
			x.D[i*b.C+c] = s / lu.D[i*n+i]
		}
	}
	return x, nil
}

func (a *M) Inv() (*M, error) { return a.Solve(Eye(a.R)) }

func (a *M) Det() (float64, error) {
	lu, _, s, err := a.lu()
	if err != nil {
		return 0, err
	}
	d := s
	for i := 0; i < a.R; i++ {
		d *= lu.D[i*a.R+i]
	}
	return d, nil
}

// Chol returns lower-triangular L with L·Lᵀ = A (A symmetric positive definite).
func (a *M) Chol() (*M, error) {
	if a.R != a.C {
		return nil, errors.New("mat: Cholesky of non-square matrix")
	}
	n := a.R
	l := New(n, n)
	for i := 0; i < n; i++ {
		for j := 0; j <= i; j++ {
			s := a.D[i*n+j]
			for k := 0; k < j; k++ {
				s -= l.D[i*n+k] * l.D[j*n+k]
			}
			if i == j {
				if s <= 0 || math.IsNaN(s) {
					return nil, ErrSingular
				}
				l.D[i*n+i] = math.Sqrt(s)
			} else {
				l.D[i*n+j] = s / l.D[j*n+j]
			}
		}
	}
	return l, nil
}

// LogDet of an SPD matrix via Cholesky (stable for tiny determinants).
func (a *M) LogDetSPD() (float64, error) {
	l, err := a.Chol()
	if err != nil {
		return 0, err
	}
	s := 0.0
	for i := 0; i < a.R; i++ {
		s += 2 * math.Log(l.D[i*a.R+i])
	}
	return s, nil
}

// Col returns column j as a slice copy.
func (a *M) Col(j int) []float64 {
	o := make([]float64, a.R)
	for i := range o {
		o[i] = a.D[i*a.C+j]
	}
	return o
}

func (a *M) HasNaN() bool {
	for _, v := range a.D {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return true
		}
	}
	return false
}

func (a *M) String() string {
	s := ""
	for i := 0; i < a.R; i++ {
		s += "["
		for j := 0; j < a.C; j++ {
			if j > 0 {
				s += " "
			}
			s += fmt.Sprintf("%.4g", a.D[i*a.C+j])
		}
		s += "]\n"
	}
	return s
}
