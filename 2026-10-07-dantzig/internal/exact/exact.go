// Package exact does exact rational linear algebra and verifies certificates.
//
// Every certificate in Dantzig is a vector y of row multipliers. By weak
// duality the Lagrangian bound of ANY y is a valid lower bound, so checking a
// certificate needs no knowledge of how the solver found it.
package exact

import (
	"errors"
	"fmt"
	"math/big"

	"dantzig/internal/model"
)

// Basis statuses of a column of [A | -I].
const (
	Basic   byte = 'B'
	AtLower byte = 'L'
	AtUpper byte = 'U'
	AtFree  byte = 'F' // nonbasic free variable sitting at zero
)

// Box is a (possibly tightened) set of variable bounds; nil = infinite.
type Box struct{ Lo, Hi []*big.Rat }

// BoxOf returns the model's own variable bounds.
func BoxOf(m *Model) Box {
	b := Box{make([]*big.Rat, len(m.Vars)), make([]*big.Rat, len(m.Vars))}
	for j, v := range m.Vars {
		b.Lo[j], b.Hi[j] = v.Lo, v.Hi
	}
	return b
}

// Model is re-exported to keep call sites short.
type Model = model.Model

// Clone returns a copy whose bound slices can be modified independently.
func (b Box) Clone() Box {
	return Box{append([]*big.Rat(nil), b.Lo...), append([]*big.Rat(nil), b.Hi...)}
}

// Empty reports whether some variable has lo > hi.
func (b Box) Empty() bool {
	for j := range b.Lo {
		if b.Lo[j] != nil && b.Hi[j] != nil && b.Lo[j].Cmp(b.Hi[j]) > 0 {
			return true
		}
	}
	return false
}

// RowActivity computes A x exactly.
func RowActivity(m *Model, x []*big.Rat) []*big.Rat {
	r := make([]*big.Rat, len(m.Rows))
	t := new(big.Rat)
	for i, row := range m.Rows {
		s := new(big.Rat)
		for _, e := range row.Entries {
			s.Add(s, t.Mul(e.V, x[e.J]))
		}
		r[i] = s
	}
	return r
}

// Dot returns c.x.
func Dot(c, x []*big.Rat) *big.Rat {
	s := new(big.Rat)
	t := new(big.Rat)
	for j := range c {
		if c[j].Sign() != 0 && x[j].Sign() != 0 {
			s.Add(s, t.Mul(c[j], x[j]))
		}
	}
	return s
}

// CheckPoint verifies x is feasible: inside box, rows within range, and (if
// ints) integral on integer variables. It returns the first violation.
func CheckPoint(m *Model, box Box, x []*big.Rat, ints bool) error {
	if len(x) != len(m.Vars) {
		return fmt.Errorf("solution has %d entries, model has %d variables", len(x), len(m.Vars))
	}
	for j, v := range m.Vars {
		if x[j] == nil {
			return fmt.Errorf("solution entry %d missing", j)
		}
		if box.Lo[j] != nil && x[j].Cmp(box.Lo[j]) < 0 {
			return fmt.Errorf("variable %s = %s below lower bound %s", v.Name, model.RatStr(x[j]), model.RatStr(box.Lo[j]))
		}
		if box.Hi[j] != nil && x[j].Cmp(box.Hi[j]) > 0 {
			return fmt.Errorf("variable %s = %s above upper bound %s", v.Name, model.RatStr(x[j]), model.RatStr(box.Hi[j]))
		}
		if ints && v.Int && !x[j].IsInt() {
			return fmt.Errorf("integer variable %s = %s is fractional", v.Name, model.RatStr(x[j]))
		}
	}
	act := RowActivity(m, x)
	for i, r := range m.Rows {
		if r.Lo != nil && act[i].Cmp(r.Lo) < 0 {
			return fmt.Errorf("row %s activity %s below %s", r.Name, model.RatStr(act[i]), model.RatStr(r.Lo))
		}
		if r.Hi != nil && act[i].Cmp(r.Hi) > 0 {
			return fmt.Errorf("row %s activity %s above %s", r.Name, model.RatStr(act[i]), model.RatStr(r.Hi))
		}
	}
	return nil
}

// ReducedCosts returns d_j = cost_j - (A^T y)_j. cost may be nil (zero).
func ReducedCosts(m *Model, cost []*big.Rat, y []*big.Rat) []*big.Rat {
	d := make([]*big.Rat, len(m.Vars))
	for j := range d {
		if cost != nil {
			d[j] = new(big.Rat).Set(cost[j])
		} else {
			d[j] = new(big.Rat)
		}
	}
	t := new(big.Rat)
	for i, row := range m.Rows {
		if y[i].Sign() == 0 {
			continue
		}
		for _, e := range row.Entries {
			d[e.J].Sub(d[e.J], t.Mul(e.V, y[i]))
		}
	}
	return d
}

// LagrangeBound evaluates
//
//	sum_j min_{x_j in box} d_j x_j + sum_i min_{r_i in range_i} y_i r_i,  d = cost - A^T y
//
// which lower-bounds min cost.x over {x in box, Ax in ranges}. ok=false means
// the bound is -infinity (y needs an infinite bound), i.e. y is useless.
func LagrangeBound(m *Model, box Box, cost, y []*big.Rat) (*big.Rat, bool) {
	if len(y) != len(m.Rows) {
		return nil, false
	}
	d := ReducedCosts(m, cost, y)
	s := new(big.Rat)
	t := new(big.Rat)
	for j := range d {
		switch d[j].Sign() {
		case 1:
			if box.Lo[j] == nil {
				return nil, false
			}
			s.Add(s, t.Mul(d[j], box.Lo[j]))
		case -1:
			if box.Hi[j] == nil {
				return nil, false
			}
			s.Add(s, t.Mul(d[j], box.Hi[j]))
		}
	}
	for i, row := range m.Rows {
		switch y[i].Sign() {
		case 1:
			if row.Lo == nil {
				return nil, false
			}
			s.Add(s, t.Mul(y[i], row.Lo))
		case -1:
			if row.Hi == nil {
				return nil, false
			}
			s.Add(s, t.Mul(y[i], row.Hi))
		}
	}
	return s, true
}

// FarkasValue returns the Lagrangian bound with zero cost; if it is > 0 the
// system is infeasible on box.
func FarkasValue(m *Model, box Box, y []*big.Rat) (*big.Rat, bool) {
	return LagrangeBound(m, box, nil, y)
}

// CheckFarkas verifies that y proves emptiness of {x in box, Ax in ranges}.
func CheckFarkas(m *Model, box Box, y []*big.Rat) error {
	if box.Empty() {
		return nil
	}
	v, ok := FarkasValue(m, box, y)
	if !ok {
		return errors.New("Farkas vector needs an infinite bound")
	}
	if v.Sign() <= 0 {
		return fmt.Errorf("Farkas value %s is not positive", model.RatStr(v))
	}
	return nil
}

// CheckRay verifies that x0 + t*dir is feasible for all t >= 0 and that the
// minimisation cost strictly decreases along dir (so the LP is unbounded).
func CheckRay(m *Model, cost []*big.Rat, x0, dir []*big.Rat) error {
	box := BoxOf(m)
	if err := CheckPoint(m, box, x0, false); err != nil {
		return fmt.Errorf("ray base point: %w", err)
	}
	for j, v := range m.Vars {
		switch dir[j].Sign() {
		case 1:
			if v.Hi != nil {
				return fmt.Errorf("ray increases %s which has an upper bound", v.Name)
			}
		case -1:
			if v.Lo != nil {
				return fmt.Errorf("ray decreases %s which has a lower bound", v.Name)
			}
		}
	}
	act := RowActivity(m, dir)
	for i, r := range m.Rows {
		switch act[i].Sign() {
		case 1:
			if r.Hi != nil {
				return fmt.Errorf("ray pushes row %s above its upper limit", r.Name)
			}
		case -1:
			if r.Lo != nil {
				return fmt.Errorf("ray pushes row %s below its lower limit", r.Name)
			}
		}
	}
	if Dot(cost, dir).Sign() >= 0 {
		return errors.New("ray does not improve the objective")
	}
	return nil
}

// ---------------------------------------------------------------- linear algebra

// ErrSingular is returned for a singular basis matrix.
var ErrSingular = errors.New("singular matrix")

// Solve solves a x = b exactly (a is n x n, nil entries are zero). a and b
// are consumed.
func Solve(a [][]*big.Rat, b []*big.Rat) ([]*big.Rat, error) {
	n := len(a)
	piv := make([]int, n) // column of the pivot of each row
	used := make([]bool, n)
	t := new(big.Rat)
	f := new(big.Rat)
	for c := 0; c < n; c++ {
		// choose the sparsest unused row with a nonzero in column c
		best, bestNnz := -1, 1<<30
		for r := 0; r < n; r++ {
			if used[r] || a[r][c] == nil || a[r][c].Sign() == 0 {
				continue
			}
			nnz := 0
			for _, v := range a[r] {
				if v != nil && v.Sign() != 0 {
					nnz++
				}
			}
			if nnz < bestNnz {
				best, bestNnz = r, nnz
			}
		}
		if best < 0 {
			return nil, ErrSingular
		}
		used[best] = true
		piv[best] = c
		var nz []int
		for j := c; j < n; j++ {
			if a[best][j] != nil && a[best][j].Sign() != 0 {
				nz = append(nz, j)
			}
		}
		pv := a[best][c]
		for r := 0; r < n; r++ {
			if r == best || a[r][c] == nil || a[r][c].Sign() == 0 {
				continue
			}
			f.Quo(a[r][c], pv)
			for _, j := range nz {
				if a[r][j] == nil {
					a[r][j] = new(big.Rat)
				}
				a[r][j].Sub(a[r][j], t.Mul(f, a[best][j]))
			}
			if b[r] == nil {
				b[r] = new(big.Rat)
			}
			if b[best] != nil {
				b[r].Sub(b[r], t.Mul(f, b[best]))
			}
		}
	}
	x := make([]*big.Rat, n)
	for r := 0; r < n; r++ {
		v := new(big.Rat)
		if b[r] != nil {
			v.Quo(b[r], a[r][piv[r]])
		}
		x[piv[r]] = v
	}
	return x, nil
}

// Invert returns the inverse of a exactly (Gauss-Jordan).
func Invert(a [][]*big.Rat) ([][]*big.Rat, error) {
	n := len(a)
	w := make([][]*big.Rat, n)
	for i := range w {
		w[i] = make([]*big.Rat, 2*n)
		for j := 0; j < n; j++ {
			if a[i][j] != nil {
				w[i][j] = new(big.Rat).Set(a[i][j])
			}
		}
		w[i][n+i] = big.NewRat(1, 1)
	}
	t := new(big.Rat)
	f := new(big.Rat)
	for c := 0; c < n; c++ {
		p := -1
		for r := c; r < n; r++ {
			if w[r][c] != nil && w[r][c].Sign() != 0 {
				p = r
				break
			}
		}
		if p < 0 {
			return nil, ErrSingular
		}
		w[c], w[p] = w[p], w[c]
		inv := new(big.Rat).Inv(w[c][c])
		for j := range w[c] {
			if w[c][j] != nil {
				w[c][j].Mul(w[c][j], inv)
			}
		}
		for r := 0; r < n; r++ {
			if r == c || w[r][c] == nil || w[r][c].Sign() == 0 {
				continue
			}
			f.Set(w[r][c])
			for j := range w[r] {
				if w[c][j] == nil || w[c][j].Sign() == 0 {
					continue
				}
				if w[r][j] == nil {
					w[r][j] = new(big.Rat)
				}
				w[r][j].Sub(w[r][j], t.Mul(f, w[c][j]))
			}
		}
	}
	out := make([][]*big.Rat, n)
	for i := range out {
		out[i] = make([]*big.Rat, n)
		for j := 0; j < n; j++ {
			out[i][j] = w[i][n+j]
			if out[i][j] == nil {
				out[i][j] = new(big.Rat)
			}
		}
	}
	return out, nil
}

// BasisColumns lists, for each basic column index k (k < n structural,
// k >= n logical row k-n), its sparse column of M = [A | -I] as row->value.
func columnOf(m *Model, colsByVar [][]model.Entry, k int) []model.Entry {
	n := len(m.Vars)
	if k < n {
		return colsByVar[k]
	}
	return []model.Entry{{J: k - n, V: big.NewRat(-1, 1)}}
}

// ColumnsByVar builds the column-wise view of A (entries are row indices).
func ColumnsByVar(m *Model) [][]model.Entry {
	cols := make([][]model.Entry, len(m.Vars))
	for i, r := range m.Rows {
		for _, e := range r.Entries {
			cols[e.J] = append(cols[e.J], model.Entry{J: i, V: e.V})
		}
	}
	return cols
}

// BasisIndices returns the basic columns of status in increasing order.
func BasisIndices(status []byte) []int {
	var idx []int
	for k, s := range status {
		if s == Basic {
			idx = append(idx, k)
		}
	}
	return idx
}

// DualsFromBasis solves B^T y = c_B exactly for the given statuses (length
// n+m) and cost (structural only; logical costs are zero).
func DualsFromBasis(m *Model, status []byte, cost []*big.Rat) ([]*big.Rat, error) {
	n := len(m.Vars)
	idx := BasisIndices(status)
	cB := make([]*big.Rat, len(idx))
	for r, k := range idx {
		if k < n && cost != nil {
			cB[r] = new(big.Rat).Set(cost[k])
		}
	}
	return dualsFromCosts(m, status, cB)
}

// DualsFromWeights is DualsFromBasis for an arbitrary per-column cost on basic
// columns (used for the phase-1 infeasibility costs). w maps column -> weight.
func DualsFromWeights(m *Model, status []byte, w map[int]*big.Rat) ([]*big.Rat, error) {
	idx := BasisIndices(status)
	cB := make([]*big.Rat, len(idx))
	for r, k := range idx {
		if v, ok := w[k]; ok {
			cB[r] = new(big.Rat).Set(v)
		}
	}
	return dualsFromCosts(m, status, cB)
}

func basisMatrixT(m *Model, status []byte) ([][]*big.Rat, []int, error) {
	mm := len(m.Rows)
	idx := BasisIndices(status)
	if len(idx) != mm {
		return nil, nil, fmt.Errorf("basis has %d columns, need %d", len(idx), mm)
	}
	cols := ColumnsByVar(m)
	a := make([][]*big.Rat, mm)
	for r, k := range idx {
		a[r] = make([]*big.Rat, mm)
		for _, e := range columnOf(m, cols, k) {
			a[r][e.J] = new(big.Rat).Set(e.V)
		}
	}
	return a, idx, nil
}

func dualsFromCosts(m *Model, status []byte, cB []*big.Rat) ([]*big.Rat, error) {
	a, _, err := basisMatrixT(m, status)
	if err != nil {
		return nil, err
	}
	return Solve(a, cB)
}

// RowDualOfColumn returns e_r^T B^{-1} where r is the position of basic
// column k: the multipliers that make row r of the tableau.
func RowDualOfColumn(m *Model, status []byte, k int) ([]*big.Rat, error) {
	a, idx, err := basisMatrixT(m, status)
	if err != nil {
		return nil, err
	}
	b := make([]*big.Rat, len(idx))
	for r, c := range idx {
		if c == k {
			b[r] = big.NewRat(1, 1)
		}
	}
	return Solve(a, b)
}

// RayFromBasis returns the structural part of the edge direction obtained by
// letting nonbasic column q move by dir (+-1): basic columns follow
// z_B = -B^{-1} M_q dir.
func RayFromBasis(m *Model, status []byte, q int, dir int) ([]*big.Rat, error) {
	n, mm := len(m.Vars), len(m.Rows)
	idx := BasisIndices(status)
	if len(idx) != mm {
		return nil, fmt.Errorf("basis has %d columns, need %d", len(idx), mm)
	}
	cols := ColumnsByVar(m)
	a := make([][]*big.Rat, mm)
	for i := range a {
		a[i] = make([]*big.Rat, mm)
	}
	for c, k := range idx {
		for _, e := range columnOf(m, cols, k) {
			a[e.J][c] = new(big.Rat).Set(e.V)
		}
	}
	rhs := make([]*big.Rat, mm)
	for i := range rhs {
		rhs[i] = new(big.Rat)
	}
	for _, e := range columnOf(m, cols, q) {
		rhs[e.J].Set(e.V)
	}
	w, err := Solve(a, rhs)
	if err != nil {
		return nil, err
	}
	sd := big.NewRat(int64(dir), 1)
	out := make([]*big.Rat, n)
	for j := range out {
		out[j] = new(big.Rat)
	}
	if q < n {
		out[q].Set(sd)
	}
	for c, k := range idx {
		if k < n {
			out[k].Neg(w[c])
			out[k].Mul(out[k], sd)
		}
	}
	return out, nil
}

// PrimalFromBasis computes the exact vertex defined by statuses on box:
// nonbasic columns sit at their bound, basic ones solve B z_B = -N z_N.
// It returns structural values x (len n) and logical values r (len m).
func PrimalFromBasis(m *Model, box Box, status []byte) (x, r []*big.Rat, err error) {
	n, mm := len(m.Vars), len(m.Rows)
	z := make([]*big.Rat, n+mm)
	var lo, hi func(k int) *big.Rat
	lo = func(k int) *big.Rat {
		if k < n {
			return box.Lo[k]
		}
		return m.Rows[k-n].Lo
	}
	hi = func(k int) *big.Rat {
		if k < n {
			return box.Hi[k]
		}
		return m.Rows[k-n].Hi
	}
	for k := range z {
		z[k] = new(big.Rat)
		switch status[k] {
		case AtLower:
			if lo(k) == nil {
				return nil, nil, fmt.Errorf("column %d at missing lower bound", k)
			}
			z[k].Set(lo(k))
		case AtUpper:
			if hi(k) == nil {
				return nil, nil, fmt.Errorf("column %d at missing upper bound", k)
			}
			z[k].Set(hi(k))
		}
	}
	idx := BasisIndices(status)
	if len(idx) != mm {
		return nil, nil, fmt.Errorf("basis has %d columns, need %d", len(idx), mm)
	}
	cols := ColumnsByVar(m)
	// rhs = -N z_N : accumulate -M_k z_k for nonbasic k
	rhs := make([]*big.Rat, mm)
	for i := range rhs {
		rhs[i] = new(big.Rat)
	}
	t := new(big.Rat)
	for k := range z {
		if status[k] == Basic || z[k].Sign() == 0 {
			continue
		}
		for _, e := range columnOf(m, cols, k) {
			rhs[e.J].Sub(rhs[e.J], t.Mul(e.V, z[k]))
		}
	}
	a := make([][]*big.Rat, mm)
	for i := range a {
		a[i] = make([]*big.Rat, mm)
	}
	for c, k := range idx {
		for _, e := range columnOf(m, cols, k) {
			a[e.J][c] = new(big.Rat).Set(e.V)
		}
	}
	sol, err := Solve(a, rhs)
	if err != nil {
		return nil, nil, err
	}
	for c, k := range idx {
		z[k] = sol[c]
	}
	return z[:n], z[n:], nil
}

// ---------------------------------------------------------------- integrality (gcd) certificates

// intRowGrid scales an all-integer row to integer coefficients and returns the
// gcd g of the scaled coefficients and the scale factor L, or ok=false when the
// row has a continuous variable (or no entries).
func intRowGrid(m *Model, i int) (g, l *big.Int, ok bool) {
	row := m.Rows[i]
	if len(row.Entries) == 0 {
		return nil, nil, false
	}
	l = big.NewInt(1)
	for _, e := range row.Entries {
		if !m.Vars[e.J].Int {
			return nil, nil, false
		}
		d := e.V.Denom()
		gg := new(big.Int).GCD(nil, nil, l, d)
		l.Mul(l, new(big.Int).Div(d, gg))
	}
	g = new(big.Int)
	for _, e := range row.Entries {
		sc := new(big.Int).Mul(e.V.Num(), new(big.Int).Div(l, e.V.Denom()))
		g.GCD(nil, nil, g, new(big.Int).Abs(sc))
	}
	return g, l, g.Sign() > 0
}

// CheckGCDRow verifies that row i can never be satisfied by integers: all its
// variables are integer, and no multiple of the coefficient gcd lies in its
// (two-sided) range. It holds on every bound box, so it needs no box.
func CheckGCDRow(m *Model, i int) error {
	if i < 0 || i >= len(m.Rows) {
		return fmt.Errorf("gcd leaf references unknown row %d", i)
	}
	g, l, ok := intRowGrid(m, i)
	if !ok {
		return fmt.Errorf("row %s is not an all-integer row", m.Rows[i].Name)
	}
	row := m.Rows[i]
	if row.Lo == nil || row.Hi == nil {
		return fmt.Errorf("row %s has an open side, so it always has an integer solution on the lattice", row.Name)
	}
	lo := new(big.Rat).Mul(row.Lo, new(big.Rat).SetInt(l))
	hi := new(big.Rat).Mul(row.Hi, new(big.Rat).SetInt(l))
	gr := new(big.Rat).SetInt(g)
	// smallest multiple of g that is >= lo: g * ceil(lo/g); infeasible if it exceeds hi
	k := ceilQ(new(big.Rat).Quo(lo, gr))
	first := new(big.Rat).Mul(k, gr)
	if first.Cmp(hi) <= 0 {
		return fmt.Errorf("row %s has the integer-lattice point %s", row.Name, first.RatString())
	}
	return nil
}

func ceilQ(r *big.Rat) *big.Rat {
	q := new(big.Int).Div(r.Num(), r.Denom())
	if !r.IsInt() {
		q.Add(q, big.NewInt(1))
	}
	return new(big.Rat).SetInt(q)
}

// FindGCDInfeasibleRow returns the index of a row proven integer-infeasible
// by CheckGCDRow, or -1.
func FindGCDInfeasibleRow(m *Model) int {
	for i := range m.Rows {
		if CheckGCDRow(m, i) == nil {
			return i
		}
	}
	return -1
}
