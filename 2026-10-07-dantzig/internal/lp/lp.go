// Package lp glues the float simplex to the exact certificate machinery.
package lp

import (
	"fmt"
	"math"
	"math/big"

	"dantzig/internal/exact"
	"dantzig/internal/model"
	"dantzig/internal/simplex"
)

// Status of an LP solve.
type Status int

const (
	Optimal Status = iota
	Infeasible
	Unbounded
	Unknown
)

func (s Status) String() string {
	return [...]string{"optimal", "infeasible", "unbounded", "unknown"}[s]
}

func fl(r *big.Rat, ifNil float64) float64 {
	if r == nil {
		return ifNil
	}
	return model.Float(r)
}

// Build converts a model (with variable bounds from box) to the float problem.
func Build(m *model.Model, box exact.Box) *simplex.Problem {
	n, mm := len(m.Vars), len(m.Rows)
	p := &simplex.Problem{M: mm, N: n}
	p.A = make([][]float64, mm)
	for i, r := range m.Rows {
		p.A[i] = make([]float64, n)
		for _, e := range r.Entries {
			p.A[i][e.J] = model.Float(e.V)
		}
	}
	mc := m.MinCost()
	p.C = make([]float64, n)
	for j := range p.C {
		p.C[j] = model.Float(mc[j])
	}
	p.Lo = make([]float64, n+mm)
	p.Hi = make([]float64, n+mm)
	for j := 0; j < n; j++ {
		p.Lo[j], p.Hi[j] = fl(box.Lo[j], math.Inf(-1)), fl(box.Hi[j], math.Inf(1))
	}
	for i, r := range m.Rows {
		p.Lo[n+i], p.Hi[n+i] = fl(r.Lo, math.Inf(-1)), fl(r.Hi, math.Inf(1))
	}
	return p
}

// OptimalCert extracts the exact vertex and duals of a basis claimed optimal
// and verifies primal feasibility and zero duality gap exactly.
func OptimalCert(m *model.Model, box exact.Box, status []byte) (x, y []*big.Rat, obj *big.Rat, err error) {
	x, _, err = exact.PrimalFromBasis(m, box, status)
	if err != nil {
		return nil, nil, nil, err
	}
	if err = exact.CheckPoint(m, box, x, false); err != nil {
		return nil, nil, nil, fmt.Errorf("basic solution infeasible: %w", err)
	}
	cost := m.MinCost()
	y, err = exact.DualsFromBasis(m, status, cost)
	if err != nil {
		return nil, nil, nil, err
	}
	obj = exact.Dot(cost, x)
	b, ok := exact.LagrangeBound(m, box, cost, y)
	if !ok || b.Cmp(obj) != 0 {
		return nil, nil, nil, fmt.Errorf("duality gap: primal %s, dual bound %v", model.RatStr(obj), ok && b != nil)
	}
	return x, y, obj, nil
}

// BoundCert returns the exact Lagrangian bound of the basis' dual vector.
func BoundCert(m *model.Model, box exact.Box, status []byte) (y []*big.Rat, bound *big.Rat, err error) {
	cost := m.MinCost()
	y, err = exact.DualsFromBasis(m, status, cost)
	if err != nil {
		return nil, nil, err
	}
	b, ok := exact.LagrangeBound(m, box, cost, y)
	if !ok {
		return nil, nil, fmt.Errorf("dual vector needs an infinite bound")
	}
	return y, b, nil
}

func neg(y []*big.Rat) []*big.Rat {
	o := make([]*big.Rat, len(y))
	for i := range y {
		o[i] = new(big.Rat).Neg(y[i])
	}
	return o
}

// FarkasCert builds and verifies an infeasibility certificate from a solver
// that just returned simplex.Infeasible. status must be the solver's basis.
func FarkasCert(m *model.Model, box exact.Box, s *simplex.Solver) ([]*big.Rat, error) {
	st := s.Statuses()
	var y []*big.Rat
	var err error
	if s.InfeasW != nil && s.FarkasBasic < 0 {
		w := map[int]*big.Rat{}
		for k, v := range s.InfeasW {
			w[k] = big.NewRat(int64(v), 1)
		}
		y, err = exact.DualsFromWeights(m, st, w)
	} else {
		y, err = exact.RowDualOfColumn(m, st, s.FarkasBasic)
	}
	if err != nil {
		return nil, err
	}
	for _, cand := range [][]*big.Rat{y, neg(y)} {
		if exact.CheckFarkas(m, box, cand) == nil {
			return cand, nil
		}
	}
	return nil, fmt.Errorf("no valid Farkas sign for derived multipliers")
}

// Solution is the certified outcome of an LP solve (minimisation sense; Obj
// excludes the model's objective constant).
type Solution struct {
	Status    Status
	X         []*big.Rat // optimal vertex, or the feasible base point of a ray
	Y         []*big.Rat // optimal duals, or Farkas multipliers
	Ray       []*big.Rat // unbounded direction
	Obj       *big.Rat
	Basis     []byte
	Certified bool
	Note      string
	Iters     int
}

// Solve solves the LP relaxation of m (integrality ignored) on its own bounds.
func Solve(m *model.Model) *Solution {
	box := exact.BoxOf(m)
	sol := &Solution{}
	if box.Empty() {
		sol.Status = Infeasible
		sol.Note = "a variable has lower bound above upper bound"
		sol.Certified = true
		return sol
	}
	s := simplex.New(Build(m, box))
	res := s.Solve(math.Inf(1))
	sol.Iters = s.Iters
	sol.Basis = s.Statuses()
	switch res {
	case simplex.Optimal:
		sol.Status = Optimal
		x, y, obj, err := OptimalCert(m, box, sol.Basis)
		if err != nil {
			sol.Note = "optimal basis failed exact verification: " + err.Error()
			sol.Status = Unknown
			return sol
		}
		sol.X, sol.Y, sol.Obj, sol.Certified = x, y, obj, true
	case simplex.Infeasible:
		sol.Status = Infeasible
		y, err := FarkasCert(m, box, s)
		if err != nil {
			sol.Note = "infeasibility not certified: " + err.Error()
			return sol
		}
		sol.Y, sol.Certified = y, true
	case simplex.Unbounded:
		sol.Status = Unbounded
		dir := 1
		if s.RayDir < 0 {
			dir = -1
		}
		ray, err := exact.RayFromBasis(m, sol.Basis, s.RayCol, dir)
		if err == nil {
			var x0 []*big.Rat
			x0, _, err = exact.PrimalFromBasis(m, box, sol.Basis)
			if err == nil {
				err = exact.CheckRay(m, m.MinCost(), x0, ray)
				if err == nil {
					sol.X, sol.Ray, sol.Certified = x0, ray, true
				}
			}
		}
		if err != nil {
			sol.Note = "unboundedness not certified: " + err.Error()
		}
	default:
		sol.Status = Unknown
		sol.Note = "simplex stopped: " + res.String()
	}
	return sol
}
