// Package simplex is a dense-tableau bounded-variable simplex in float64.
//
// Computational form: M z = 0 with M = [A | -I], z = (x, r); every column k has
// bounds Lo[k] <= z_k <= Hi[k]. The solver keeps T = B^{-1} M for the current
// basis, supports a composite primal phase 1/2 and a dual simplex for warm
// starts after bound changes (branch & bound). The answers are *candidates*:
// the exact package verifies them in rational arithmetic.
package simplex

import (
	"errors"
	"math"
	"time"
)

// Column statuses (same byte values as package exact).
const (
	Basic   byte = 'B'
	AtLower byte = 'L'
	AtUpper byte = 'U'
	AtFree  byte = 'F'
)

// Result of a solve.
type Result int

const (
	Optimal Result = iota
	Infeasible
	Unbounded
	IterLimit
	Cutoff
	NumFail
	Stalled // internal: dual simplex made no progress
)

func (r Result) String() string {
	return [...]string{"optimal", "infeasible", "unbounded", "iteration-limit", "cutoff", "numerical-failure", "stalled"}[r]
}

const (
	tolFeas       = 1e-9
	tolOpt        = 1e-9
	tolPivot      = 1e-9
	tolSmall      = 1e-7 // pivots smaller than this trigger a refactor first
	refactorEvery = 64
)

var inf = math.Inf(1)

type spEntry struct {
	j int
	v float64
}

// Problem is the float image of a model: A is m x n dense.
type Problem struct {
	M, N int
	A    [][]float64
	sp   [][]spEntry // sparse row view of A (shared, read-only)
	C    []float64   // minimisation cost, length N
	Lo   []float64   // length N+M
	Hi   []float64
}

// Solver holds the mutable simplex state.
type Solver struct {
	M, N      int
	A         [][]float64
	sp        [][]spEntry // sparse row view of A (shared, read-only)
	C         []float64
	Lo        []float64
	Hi        []float64
	Cost      []float64 // working cost over N+M columns (true cost, or perturbed)
	perturbed bool
	T         [][]float64 // M x (N+M)
	Basis     []int       // row -> column
	St        []byte      // N+M
	X         []float64   // N+M

	Iters       int
	iterBase    int       // Iters at the start of the current Solve
	Deadline    time.Time // zero = none
	sinceRefac  int
	MaxIters    int
	stall       int
	RayCol      int // unbounded: entering column and direction
	RayDir      float64
	InfeasW     map[int]float64 // infeasible (phase 1): basic column -> +-1 weight
	FarkasPos   int             // dual-infeasible proof: basis row index
	FarkasBasic int             // basic column of that row
	FarkasUp    bool            // true if the basic variable was above its upper bound
}

// New builds a solver at the slack basis.
func New(p *Problem) *Solver {
	s := &Solver{M: p.M, N: p.N, A: p.A, C: p.C}
	s.Lo = append([]float64(nil), p.Lo...)
	s.Hi = append([]float64(nil), p.Hi...)
	s.MaxIters = 50000 + 100*(p.M+p.N)
	s.sp = make([][]spEntry, p.M)
	for i := range p.A {
		for j, v := range p.A[i] {
			if v != 0 {
				s.sp[i] = append(s.sp[i], spEntry{j, v})
			}
		}
	}
	s.setTrueCost()
	s.ResetSlack()
	return s
}

func (s *Solver) setTrueCost() {
	s.Cost = make([]float64, s.N+s.M)
	copy(s.Cost, s.C)
	s.perturbed = false
}

// perturbCost shifts the cost of nonbasic columns by tiny amounts in the
// direction that keeps the basis dual feasible, breaking dual degeneracy.
func (s *Solver) perturbCost(seed uint64) {
	s.Cost = make([]float64, s.N+s.M)
	copy(s.Cost, s.C)
	x := seed*6364136223846793005 + 1442695040888963407
	for k := range s.Cost {
		x = x*6364136223846793005 + 1442695040888963407
		u := float64(x>>11) / float64(1<<53) // [0,1)
		mag := (1e-6 + 1e-6*u) * (1 + math.Abs(s.Cost[k]))
		switch s.St[k] {
		case AtLower:
			if s.Lo[k] != s.Hi[k] {
				s.Cost[k] += mag
			}
		case AtUpper:
			if s.Lo[k] != s.Hi[k] {
				s.Cost[k] -= mag
			}
		}
	}
	s.perturbed = true
}

// limitHit reports whether this Solve exceeded its iteration budget or deadline.
func (s *Solver) limitHit() bool {
	if s.Iters-s.iterBase > s.MaxIters {
		return true
	}
	return !s.Deadline.IsZero() && s.Iters%16 == 0 && time.Now().After(s.Deadline)
}

// TimedOut reports whether the deadline has passed.
func (s *Solver) TimedOut() bool { return !s.Deadline.IsZero() && time.Now().After(s.Deadline) }

// Clone copies the mutable state (A and C are shared, read-only).
func (s *Solver) Clone() *Solver {
	c := *s
	c.Lo = append([]float64(nil), s.Lo...)
	c.Hi = append([]float64(nil), s.Hi...)
	c.Cost = append([]float64(nil), s.Cost...)
	c.Basis = append([]int(nil), s.Basis...)
	c.St = append([]byte(nil), s.St...)
	c.X = append([]float64(nil), s.X...)
	c.T = make([][]float64, len(s.T))
	for i := range s.T {
		c.T[i] = append([]float64(nil), s.T[i]...)
	}
	return &c
}

// ResetSlack installs the all-logical basis.
func (s *Solver) ResetSlack() {
	m, n := s.M, s.N
	tot := n + m
	s.T = make([][]float64, m)
	for i := 0; i < m; i++ {
		row := make([]float64, tot)
		for j := 0; j < n; j++ {
			row[j] = -s.A[i][j]
		}
		row[n+i] = 1
		s.T[i] = row
	}
	s.Basis = make([]int, m)
	s.St = make([]byte, tot)
	s.X = make([]float64, tot)
	for j := 0; j < n; j++ {
		s.St[j] = AtLower
	}
	for i := 0; i < m; i++ {
		s.Basis[i] = n + i
		s.St[n+i] = Basic
	}
	s.sinceRefac = 0
	s.refreshNonbasic()
	s.computeXB()
}

func (s *Solver) tolF(b float64) float64 {
	if math.IsInf(b, 0) {
		return tolFeas
	}
	return tolFeas * math.Max(1, math.Abs(b))
}

// refreshNonbasic re-seats nonbasic values on their (possibly changed) bounds.
func (s *Solver) refreshNonbasic() {
	for k := range s.St {
		if s.St[k] == Basic {
			continue
		}
		lo, hi := s.Lo[k], s.Hi[k]
		switch s.St[k] {
		case AtLower:
			if math.IsInf(lo, -1) {
				if !math.IsInf(hi, 1) {
					s.St[k] = AtUpper
				} else {
					s.St[k] = AtFree
				}
			}
		case AtUpper:
			if math.IsInf(hi, 1) {
				if !math.IsInf(lo, -1) {
					s.St[k] = AtLower
				} else {
					s.St[k] = AtFree
				}
			}
		case AtFree:
			if !math.IsInf(lo, -1) {
				s.St[k] = AtLower
			} else if !math.IsInf(hi, 1) {
				s.St[k] = AtUpper
			}
		}
		switch s.St[k] {
		case AtLower:
			s.X[k] = lo
		case AtUpper:
			s.X[k] = hi
		default:
			s.X[k] = 0
		}
	}
}

// computeXB recomputes basic values: x_B = -T_N z_N.
func (s *Solver) computeXB() {
	for i := 0; i < s.M; i++ {
		sum := 0.0
		row := s.T[i]
		for j, st := range s.St {
			if st != Basic && s.X[j] != 0 {
				sum += row[j] * s.X[j]
			}
		}
		s.X[s.Basis[i]] = -sum
	}
}

// ErrSingular is returned when a basis cannot be inverted.
var ErrSingular = errors.New("singular basis")

// Refactor rebuilds T = B^{-1} M from scratch and recomputes x_B.
func (s *Solver) Refactor() error {
	m, n := s.M, s.N
	tot := n + m
	// dense B (m x m), column i = M column of Basis[i]
	b := make([][]float64, m)
	for r := 0; r < m; r++ {
		b[r] = make([]float64, 2*m)
	}
	for c, k := range s.Basis {
		if k < n {
			for r := 0; r < m; r++ {
				b[r][c] = s.A[r][k]
			}
		} else {
			b[k-n][c] = -1
		}
	}
	for r := 0; r < m; r++ {
		b[r][m+r] = 1
	}
	for c := 0; c < m; c++ {
		p, best := -1, 1e-12
		for r := c; r < m; r++ {
			if v := math.Abs(b[r][c]); v > best {
				p, best = r, v
			}
		}
		if p < 0 {
			return ErrSingular
		}
		b[c], b[p] = b[p], b[c]
		inv := 1 / b[c][c]
		for j := range b[c] {
			b[c][j] *= inv
		}
		for r := 0; r < m; r++ {
			if r == c || b[r][c] == 0 {
				continue
			}
			f := b[r][c]
			for j := range b[r] {
				b[r][j] -= f * b[c][j]
			}
		}
	}
	// T = Binv * M
	for i := 0; i < m; i++ {
		row := s.T[i]
		for j := range row {
			row[j] = 0
		}
		for r := 0; r < m; r++ {
			f := b[i][m+r]
			if f == 0 {
				continue
			}
			for _, e := range s.sp[r] {
				row[e.j] += f * e.v
			}
			row[n+r] -= f
		}
	}
	_ = tot
	s.sinceRefac = 0
	s.computeXB()
	return nil
}

// LoadBasis installs a basis given by statuses (length N+M, exactly M basic).
func (s *Solver) LoadBasis(st []byte) error {
	var basis []int
	for k, v := range st {
		if v == Basic {
			basis = append(basis, k)
		}
	}
	if len(basis) != s.M {
		return errors.New("basis has wrong size")
	}
	s.Basis = basis
	s.St = append([]byte(nil), st...)
	s.refreshNonbasic()
	if err := s.Refactor(); err != nil {
		return err
	}
	return nil
}

// Statuses returns a copy of the column statuses.
func (s *Solver) Statuses() []byte { return append([]byte(nil), s.St...) }

// SetBounds changes the bounds of column k (used by branch & bound). The
// caller should call Solve afterwards.
func (s *Solver) SetBounds(k int, lo, hi float64) {
	s.Lo[k], s.Hi[k] = lo, hi
}

// Objective returns c.x for the current point.
func (s *Solver) Objective() float64 {
	o := 0.0
	for j := 0; j < s.N; j++ {
		o += s.C[j] * s.X[j]
	}
	return o
}

// Point returns the structural values.
func (s *Solver) Point() []float64 { return append([]float64(nil), s.X[:s.N]...) }

func (s *Solver) pivot(r, q int) {
	row := s.T[r]
	inv := 1 / row[q]
	for j := range row {
		row[j] *= inv
	}
	row[q] = 1
	for i := 0; i < s.M; i++ {
		if i == r {
			continue
		}
		f := s.T[i][q]
		if f == 0 {
			continue
		}
		ti := s.T[i]
		for j, v := range row {
			if v != 0 {
				ti[j] -= f * v
			}
		}
		ti[q] = 0
	}
	s.Basis[r] = q
	s.sinceRefac++
	s.Iters++
}

// reducedCosts computes d_j = cost_j - sum_i cc_i T[i][j] for nonbasic j.
func (s *Solver) reducedCosts(cc []float64, phase1 bool, d []float64) {
	for j := range d {
		d[j] = 0
		if !phase1 {
			d[j] = s.Cost[j]
		}
	}
	for i, c := range cc {
		if c == 0 {
			continue
		}
		row := s.T[i]
		for j := range d {
			d[j] -= c * row[j]
		}
	}
}

// DualFeasible reports whether the basis is dual feasible within tol.
func (s *Solver) DualFeasible(tol float64) bool {
	cc := make([]float64, s.M)
	for i, k := range s.Basis {
		cc[i] = s.Cost[k]
	}
	d := make([]float64, s.N+s.M)
	s.reducedCosts(cc, false, d)
	for j, st := range s.St {
		if st == Basic || s.Lo[j] == s.Hi[j] {
			continue
		}
		switch st {
		case AtLower:
			if d[j] < -tol {
				return false
			}
		case AtUpper:
			if d[j] > tol {
				return false
			}
		case AtFree:
			if math.Abs(d[j]) > tol {
				return false
			}
		}
	}
	return true
}

// Solve optimises from the current basis. cutoff (if finite) lets the dual
// simplex stop once the objective provably exceeds it.
func (s *Solver) Solve(cutoff float64) Result {
	s.iterBase = s.Iters
	s.setTrueCost()
	s.refreshNonbasic()
	s.computeXB()
	if s.DualFeasible(1e-7) {
		r := s.dual(cutoff)
		if r == Stalled { // dual degenerate: perturb the costs and retry
			s.perturbCost(uint64(s.Iters) + 1)
			r = s.dual(math.Inf(1))
			s.setTrueCost()
			if r == Stalled {
				r = IterLimit
			}
		}
		switch r {
		case Infeasible, Cutoff, IterLimit, NumFail:
			return r
		}
	}
	return s.primal()
}

// primal runs composite phase 1 / phase 2 from the current basis.
func (s *Solver) primal() Result {
	m, tot := s.M, s.N+s.M
	cc := make([]float64, m)
	d := make([]float64, tot)
	alpha := make([]float64, m)
	s.stall = 0
	s.FarkasBasic = -1
	confirmed := false
	for {
		if s.limitHit() {
			return IterLimit
		}
		if s.sinceRefac >= refactorEvery {
			if err := s.Refactor(); err != nil {
				return NumFail
			}
		}
		// classify infeasibilities
		phase1 := false
		for i, k := range s.Basis {
			x := s.X[k]
			switch {
			case x < s.Lo[k]-s.tolF(s.Lo[k]):
				cc[i] = -1
				phase1 = true
			case x > s.Hi[k]+s.tolF(s.Hi[k]):
				cc[i] = 1
				phase1 = true
			default:
				cc[i] = 0
			}
		}
		if !phase1 {
			for i, k := range s.Basis {
				cc[i] = s.Cost[k]
			}
		}
		s.reducedCosts(cc, phase1, d)
		// entering variable
		q, dir := -1, 0.0
		bestScore := 0.0
		for j := 0; j < tot; j++ {
			st := s.St[j]
			if st == Basic || s.Lo[j] == s.Hi[j] {
				continue
			}
			var dj float64
			switch {
			case st == AtLower && d[j] < -tolOpt:
				dj = 1
			case st == AtUpper && d[j] > tolOpt:
				dj = -1
			case st == AtFree && math.Abs(d[j]) > tolOpt:
				dj = -math.Copysign(1, d[j])
			default:
				continue
			}
			if s.stall > 30 { // Bland: first eligible index
				q, dir = j, dj
				break
			}
			if sc := math.Abs(d[j]); sc > bestScore {
				q, dir, bestScore = j, dj, sc
			}
		}
		if q < 0 {
			if s.sinceRefac > 0 && !confirmed {
				confirmed = true
				if err := s.Refactor(); err != nil {
					return NumFail
				}
				continue
			}
			if phase1 {
				s.InfeasW = map[int]float64{}
				for i, k := range s.Basis {
					if cc[i] != 0 {
						s.InfeasW[k] = cc[i]
					}
				}
				return Infeasible
			}
			return Optimal
		}
		confirmed = false
		// ratio test, rate of change of x_B[i] per unit step is alpha[i]
		for i := 0; i < m; i++ {
			alpha[i] = -s.T[i][q] * dir
		}
		type blk struct {
			bound float64
			dist  float64
		}
		blocking := func(i int) (blk, bool) {
			a := alpha[i]
			if math.Abs(a) <= tolPivot {
				return blk{}, false
			}
			k := s.Basis[i]
			x, lo, hi := s.X[k], s.Lo[k], s.Hi[k]
			if a < 0 { // decreasing
				switch {
				case x > hi+s.tolF(hi):
					return blk{hi, x - hi}, true
				case x < lo-s.tolF(lo):
					return blk{}, false
				case !math.IsInf(lo, -1):
					return blk{lo, x - lo}, true
				}
			} else {
				switch {
				case x < lo-s.tolF(lo):
					return blk{lo, lo - x}, true
				case x > hi+s.tolF(hi):
					return blk{}, false
				case !math.IsInf(hi, 1):
					return blk{hi, hi - x}, true
				}
			}
			return blk{}, false
		}
		// Harris pass 1: largest step with bounds relaxed by tolerance
		tmax := inf
		for i := 0; i < m; i++ {
			if b, ok := blocking(i); ok {
				r := (b.dist + s.tolF(b.bound)) / math.Abs(alpha[i])
				if r < tmax {
					tmax = r
				}
			}
		}
		r, bestA := -1, 0.0
		bestBound := 0.0
		tstep := inf
		bland := s.stall > 30
		for i := 0; i < m; i++ {
			b, ok := blocking(i)
			if !ok {
				continue
			}
			ratio := b.dist / math.Abs(alpha[i])
			if ratio <= tmax {
				better := math.Abs(alpha[i]) > bestA
				if bland {
					better = r < 0 || s.Basis[i] < s.Basis[r]
				}
				if better {
					r, bestA, tstep, bestBound = i, math.Abs(alpha[i]), math.Max(ratio, 0), b.bound
				}
			}
		}
		flip := s.Hi[q] - s.Lo[q]
		if r < 0 && math.IsInf(flip, 1) {
			if phase1 {
				return NumFail
			}
			s.RayCol, s.RayDir = q, dir
			return Unbounded
		}
		if r >= 0 && bestA < tolSmall && s.sinceRefac > 0 {
			if err := s.Refactor(); err != nil {
				return NumFail
			}
			continue
		}
		if r < 0 || flip <= tstep {
			// bound flip of the entering variable
			t := flip
			for i := 0; i < m; i++ {
				s.X[s.Basis[i]] += alpha[i] * t
			}
			s.X[q] += dir * t
			if dir > 0 {
				s.X[q], s.St[q] = s.Hi[q], AtUpper
			} else {
				s.X[q], s.St[q] = s.Lo[q], AtLower
			}
			s.Iters++
			s.stall = 0
			continue
		}
		if tstep < 1e-12 {
			s.stall++
		} else {
			s.stall = 0
		}
		for i := 0; i < m; i++ {
			s.X[s.Basis[i]] += alpha[i] * tstep
		}
		s.X[q] += dir * tstep
		leave := s.Basis[r]
		bnd := bestBound
		s.pivot(r, q)
		s.St[q] = Basic
		s.X[leave] = bnd
		if bnd == s.Hi[leave] && s.Lo[leave] != s.Hi[leave] {
			s.St[leave] = AtUpper
		} else {
			s.St[leave] = AtLower
		}
	}
}

// SolvePrimal runs only the primal simplex (phase 1 + 2) from the current
// basis; exported so tests can cross-check it against the dual path.
func (s *Solver) SolvePrimal() Result {
	s.iterBase = s.Iters
	s.setTrueCost()
	s.refreshNonbasic()
	s.computeXB()
	return s.primal()
}
