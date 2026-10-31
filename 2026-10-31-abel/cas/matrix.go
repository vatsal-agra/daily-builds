package cas

import (
	"fmt"
	"math/big"
)

// NewMat builds a matrix expression from row-major entries.
func NewMat(r, c int, cells []E) E { return &Expr{K: KMat, A: cells, R: r, C: c} }

func (m E) at(i, j int) E { return m.A[i*m.C+j] }

func Identity(n int) E {
	cells := make([]E, n*n)
	for i := range cells {
		cells[i] = Zero
	}
	for i := 0; i < n; i++ {
		cells[i*n+i] = One
	}
	return NewMat(n, n, cells)
}

func mapMat(m E, f func(E) E) E {
	cells := make([]E, len(m.A))
	for i, a := range m.A {
		cells[i] = f(a)
	}
	return NewMat(m.R, m.C, cells)
}

func matAddAll(ts []E) E {
	var acc E
	for _, t := range ts {
		if t.K != KMat {
			if isNumVal(t, 0) {
				continue
			}
			fail("cannot add a scalar to a matrix")
		}
		if acc == nil {
			acc = t
			continue
		}
		if acc.R != t.R || acc.C != t.C {
			fail("matrix size mismatch: %dx%d + %dx%d", acc.R, acc.C, t.R, t.C)
		}
		cells := make([]E, len(t.A))
		for i := range cells {
			cells[i] = Add(acc.A[i], t.A[i])
		}
		acc = NewMat(t.R, t.C, cells)
	}
	return acc
}

func matMul2(a, b E) E {
	switch {
	case a.K != KMat:
		return mapMat(b, func(x E) E { return Mul(a, x) })
	case b.K != KMat:
		return mapMat(a, func(x E) E { return Mul(x, b) })
	}
	if a.C != b.R {
		fail("matrix size mismatch: %dx%d * %dx%d", a.R, a.C, b.R, b.C)
	}
	cells := make([]E, a.R*b.C)
	for i := 0; i < a.R; i++ {
		for j := 0; j < b.C; j++ {
			terms := make([]E, a.C)
			for k := 0; k < a.C; k++ {
				terms[k] = Mul(a.at(i, k), b.at(k, j))
			}
			cells[i*b.C+j] = Add(terms...)
		}
	}
	return NewMat(a.R, b.C, cells)
}

func matMulAll(fs []E) E {
	acc := fs[0]
	for _, f := range fs[1:] {
		acc = matMul2(acc, f)
	}
	return acc
}

func matPow(b, e E) E {
	if b.K != KMat || e.K != KNum || !e.N.IsInt() {
		fail("matrix powers need a square matrix and an integer exponent")
	}
	if b.R != b.C {
		fail("matrix power needs a square matrix")
	}
	n, ok := ratInt64(e.N)
	if !ok || abs64(n) > 4096 {
		fail("exponent too large")
	}
	base := b
	if n < 0 {
		base = Inverse(b)
		n = -n
	}
	result := Identity(b.R)
	for k := n; k > 0; k >>= 1 {
		if k&1 == 1 {
			result = matMul2(result, base)
		}
		base = matMul2(base, base)
	}
	return result
}

func Transpose(m E) E {
	cells := make([]E, len(m.A))
	for i := 0; i < m.R; i++ {
		for j := 0; j < m.C; j++ {
			cells[j*m.R+i] = m.at(i, j)
		}
	}
	return NewMat(m.C, m.R, cells)
}

// ---------- exact rational linear algebra ----------

type ratMat [][]*big.Rat

func toRat(m E) (ratMat, bool) {
	out := make(ratMat, m.R)
	for i := range out {
		out[i] = make([]*big.Rat, m.C)
		for j := range out[i] {
			if c := m.at(i, j); c.K == KNum {
				out[i][j] = new(big.Rat).Set(c.N)
			} else {
				return nil, false
			}
		}
	}
	return out, true
}

func mustRat(m E, what string) ratMat {
	r, ok := toRat(m)
	if !ok {
		fail("%s needs a matrix of rational numbers", what)
	}
	return r
}

func fromRat(r ratMat) E {
	rows := len(r)
	cols := 0
	if rows > 0 {
		cols = len(r[0])
	}
	cells := make([]E, 0, rows*cols)
	for _, row := range r {
		for _, v := range row {
			cells = append(cells, Num(v))
		}
	}
	return NewMat(rows, cols, cells)
}

func copyRat(r ratMat) ratMat {
	out := make(ratMat, len(r))
	for i := range r {
		out[i] = make([]*big.Rat, len(r[i]))
		for j := range r[i] {
			out[i][j] = new(big.Rat).Set(r[i][j])
		}
	}
	return out
}

// rref reduces in place over the first `cols` columns and returns pivot columns and the determinant sign factor.
func rref(a ratMat, cols int) (pivots []int, det *big.Rat) {
	det = big.NewRat(1, 1)
	row := 0
	for c := 0; c < cols && row < len(a); c++ {
		p := -1
		for r := row; r < len(a); r++ {
			if a[r][c].Sign() != 0 {
				p = r
				break
			}
		}
		if p < 0 {
			det.SetInt64(0)
			continue
		}
		if p != row {
			a[p], a[row] = a[row], a[p]
			det.Neg(det)
		}
		pv := new(big.Rat).Set(a[row][c])
		det.Mul(det, pv)
		inv := new(big.Rat).Inv(pv)
		for j := range a[row] {
			a[row][j].Mul(a[row][j], inv)
		}
		for r := range a {
			if r != row && a[r][c].Sign() != 0 {
				f := new(big.Rat).Set(a[r][c])
				for j := range a[r] {
					a[r][j].Sub(a[r][j], new(big.Rat).Mul(f, a[row][j]))
				}
			}
		}
		pivots = append(pivots, c)
		row++
	}
	return
}

// Det computes the determinant (exact rational elimination, or cofactor expansion for symbolic entries).
func Det(m E) E {
	if m.R != m.C {
		fail("determinant needs a square matrix")
	}
	if r, ok := toRat(m); ok {
		if m.R == 0 {
			return One
		}
		_, d := rref(copyRat(r), m.C)
		return Num(d)
	}
	if m.R > 6 {
		fail("symbolic determinant is limited to 6x6")
	}
	return Expand(cofactorDet(m))
}

func cofactorDet(m E) E {
	n := m.R
	if n == 1 {
		return m.A[0]
	}
	var terms []E
	for j := 0; j < n; j++ {
		var cells []E
		for i := 1; i < n; i++ {
			for k := 0; k < n; k++ {
				if k != j {
					cells = append(cells, m.at(i, k))
				}
			}
		}
		minor := cofactorDet(NewMat(n-1, n-1, cells))
		sign := Int(1)
		if j%2 == 1 {
			sign = Int(-1)
		}
		terms = append(terms, Mul(sign, m.at(0, j), minor))
	}
	return Add(terms...)
}

// Inverse of a rational matrix by Gauss-Jordan.
func Inverse(m E) E {
	if m.R != m.C {
		fail("inverse needs a square matrix")
	}
	r := mustRat(m, "inverse")
	n := m.R
	aug := make(ratMat, n)
	for i := range aug {
		aug[i] = make([]*big.Rat, 2*n)
		for j := 0; j < n; j++ {
			aug[i][j] = new(big.Rat).Set(r[i][j])
			aug[i][n+j] = new(big.Rat)
		}
		aug[i][n+i].SetInt64(1)
	}
	piv, _ := rref(aug, n)
	if len(piv) < n {
		fail("matrix is singular")
	}
	out := make(ratMat, n)
	for i := range out {
		out[i] = aug[i][n:]
	}
	return fromRat(out)
}

// Rref returns the reduced row echelon form.
func Rref(m E) E {
	r := copyRat(mustRat(m, "rref"))
	rref(r, m.C)
	return fromRat(r)
}

func Rank(m E) int {
	r := copyRat(mustRat(m, "rank"))
	p, _ := rref(r, m.C)
	return len(p)
}

// Nullspace returns a basis (as column vectors) of the null space of m.
func Nullspace(m E) []E {
	r := copyRat(mustRat(m, "nullspace"))
	piv, _ := rref(r, m.C)
	isPiv := map[int]int{}
	for i, c := range piv {
		isPiv[c] = i
	}
	var basis []E
	for free := 0; free < m.C; free++ {
		if _, ok := isPiv[free]; ok {
			continue
		}
		cells := make([]E, m.C)
		for j := range cells {
			cells[j] = Zero
		}
		cells[free] = One
		for c, row := range isPiv {
			cells[c] = Num(new(big.Rat).Neg(r[row][free]))
		}
		basis = append(basis, NewMat(m.C, 1, cells))
	}
	return basis
}

// SolveLinear solves A x = b exactly. It returns the unique solution, or an error
// describing inconsistency or the dimension of the solution family.
func SolveLinear(A, b E) E {
	if b.K != KMat || b.C != 1 || b.R != A.R {
		fail("right-hand side must be a column vector with %d entries", A.R)
	}
	ar := mustRat(A, "solve")
	br := mustRat(b, "solve")
	aug := make(ratMat, A.R)
	for i := range aug {
		aug[i] = append(append([]*big.Rat{}, ar[i]...), br[i][0])
	}
	piv, _ := rref(aug, A.C)
	for i := len(piv); i < A.R; i++ {
		if aug[i][A.C].Sign() != 0 {
			fail("the system is inconsistent (no solution)")
		}
	}
	for _, c := range piv {
		if c == A.C {
			fail("the system is inconsistent (no solution)")
		}
	}
	if len(piv) < A.C {
		fail("the system is underdetermined (%d free variable(s)); use nullspace for the solution family", A.C-len(piv))
	}
	cells := make([]E, A.C)
	for i := range cells {
		cells[i] = Num(aug[i][A.C])
	}
	return NewMat(A.C, 1, cells)
}

// CharPoly returns det(lambda*I - A) via the Faddeev–LeVerrier recurrence (ring ops + integer division only).
func CharPoly(m E, lambda string) E {
	if m.R != m.C {
		fail("characteristic polynomial needs a square matrix")
	}
	n := m.R
	if n == 0 {
		return One
	}
	coeffs := make([]E, n+1) // coeffs[n-k] multiplies lambda^(n-k)
	coeffs[0] = One
	M := Identity(n)
	trace := func(x E) E {
		var ts []E
		for i := 0; i < n; i++ {
			ts = append(ts, x.at(i, i))
		}
		return Expand(Add(ts...))
	}
	var Mk E = NewMat(n, n, make([]E, n*n))
	for i := range Mk.A {
		Mk.A[i] = Zero
	}
	for k := 1; k <= n; k++ {
		// M_k = A*M_{k-1} + c_{n-k+1} I
		Mk = matMul2(m, M)
		Mk = mapMat(Mk, Expand)
		ck := Expand(Mul(Frac(-1, int64(k)), trace(Mk)))
		coeffs[k] = ck
		M = matAddAll([]E{Mk, matMul2(ck, Identity(n))})
		M = mapMat(M, Expand)
	}
	lam := Sym(lambda)
	var out []E
	for k := 0; k <= n; k++ {
		out = append(out, Mul(coeffs[k], Pow(lam, Int(int64(n-k)))))
	}
	return Expand(Add(out...))
}

func (m E) dimString() string { return fmt.Sprintf("%dx%d", m.R, m.C) }
