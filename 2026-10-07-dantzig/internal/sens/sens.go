// Package sens performs exact sensitivity analysis of an LP optimum:
// shadow prices, reduced costs, cost ranging and right-hand-side ranging, all in
// rational arithmetic from the final basis.
package sens

import (
	"fmt"
	"math/big"

	"dantzig/internal/exact"
	"dantzig/internal/lp"
	"dantzig/internal/model"
)

// Range is an interval with optional (nil) infinite ends.
type Range struct{ Lo, Hi *big.Rat }

// VarInfo is the analysis of one variable.
type VarInfo struct {
	Name        string
	Value       *big.Rat
	Status      string // basic | at lower | at upper | free
	Cost        *big.Rat
	ReducedCost *big.Rat // d_j in the model's own objective sense
	CostRange   Range    // cost interval over which this basis stays optimal
}

// RowInfo is the analysis of one constraint.
type RowInfo struct {
	Name       string
	Activity   *big.Rat
	Slack      *big.Rat // distance to the nearest limit (0 when binding)
	Binding    string   // "", "lower" or "upper"
	Dual       *big.Rat // shadow price: d(objective)/d(binding limit), model's sense
	LimitRange Range    // range of the binding limit over which Dual is valid (basic rows: the limit's free movement)
}

// Report is the complete analysis.
type Report struct {
	Objective *big.Rat // model's sense, includes constant
	Vars      []VarInfo
	Rows      []RowInfo
}

func neg(r *big.Rat) *big.Rat { return new(big.Rat).Neg(r) }

func negRange(r Range) Range {
	var o Range
	if r.Hi != nil {
		o.Lo = neg(r.Hi)
	}
	if r.Lo != nil {
		o.Hi = neg(r.Lo)
	}
	return o
}

func tighten(r *Range, lo, hi *big.Rat) {
	if lo != nil && (r.Lo == nil || lo.Cmp(r.Lo) > 0) {
		r.Lo = lo
	}
	if hi != nil && (r.Hi == nil || hi.Cmp(r.Hi) < 0) {
		r.Hi = hi
	}
}

// Analyze solves the LP relaxation of m and analyses the optimal basis. For a
// model with integer variables the caller should fix them first (see FixInts).
func Analyze(m *model.Model) (*Report, error) {
	sol := lp.Solve(m)
	if sol.Status != lp.Optimal || !sol.Certified {
		return nil, fmt.Errorf("LP is %s; sensitivity analysis needs a certified optimum", sol.Status)
	}
	return AnalyzeBasis(m, sol)
}

// FixInts returns a copy of m with every integer variable fixed at x's value.
func FixInts(m *model.Model, x []*big.Rat) *model.Model {
	c := m.Clone()
	for j := range c.Vars {
		if c.Vars[j].Int {
			c.Vars[j].Lo, c.Vars[j].Hi = new(big.Rat).Set(x[j]), new(big.Rat).Set(x[j])
			c.Vars[j].Int = false
		}
	}
	return c
}

// AnalyzeBasis analyses a certified optimal LP solution.
func AnalyzeBasis(m *model.Model, sol *lp.Solution) (*Report, error) {
	n, mm := len(m.Vars), len(m.Rows)
	st := sol.Basis
	box := exact.BoxOf(m)
	idx := exact.BasisIndices(st)
	if len(idx) != mm {
		return nil, fmt.Errorf("basis size mismatch")
	}
	x, r, err := exact.PrimalFromBasis(m, box, st)
	if err != nil {
		return nil, err
	}
	cost := m.MinCost()
	y, err := exact.DualsFromBasis(m, st, cost)
	if err != nil {
		return nil, err
	}
	d := exact.ReducedCosts(m, cost, y) // structural; logical reduced cost = y_i

	// tableau T = B^{-1} M, rows indexed by position in idx
	cols := exact.ColumnsByVar(m)
	bmat := make([][]*big.Rat, mm)
	for i := range bmat {
		bmat[i] = make([]*big.Rat, mm)
	}
	colEntries := func(k int) []model.Entry {
		if k < n {
			return cols[k]
		}
		return []model.Entry{{J: k - n, V: big.NewRat(-1, 1)}}
	}
	for c, k := range idx {
		for _, e := range colEntries(k) {
			bmat[e.J][c] = new(big.Rat).Set(e.V)
		}
	}
	binv, err := exact.Invert(bmat)
	if err != nil {
		return nil, err
	}
	tab := func(p, k int) *big.Rat { // (B^{-1} M)[p][k]
		s := new(big.Rat)
		t := new(big.Rat)
		for _, e := range colEntries(k) {
			s.Add(s, t.Mul(binv[p][e.J], e.V))
		}
		return s
	}
	posOf := make(map[int]int)
	for p, k := range idx {
		posOf[k] = p
	}
	dOf := func(k int) *big.Rat {
		if k < n {
			return d[k]
		}
		return y[k-n]
	}
	lo := func(k int) *big.Rat {
		if k < n {
			return box.Lo[k]
		}
		return m.Rows[k-n].Lo
	}
	hi := func(k int) *big.Rat {
		if k < n {
			return box.Hi[k]
		}
		return m.Rows[k-n].Hi
	}
	fixed := func(k int) bool { return lo(k) != nil && hi(k) != nil && lo(k).Cmp(hi(k)) == 0 }

	rep := &Report{}
	obj := exact.Dot(cost, x)
	if m.Maximize {
		obj = neg(obj)
	}
	rep.Objective = new(big.Rat).Add(obj, m.ObjConst)

	sign := big.NewRat(1, 1)
	if m.Maximize {
		sign = big.NewRat(-1, 1)
	}
	sgn := func(v *big.Rat) *big.Rat { return new(big.Rat).Mul(v, sign) }

	for j := 0; j < n; j++ {
		vi := VarInfo{Name: m.Vars[j].Name, Value: x[j], Cost: new(big.Rat).Set(m.Vars[j].Obj), ReducedCost: sgn(d[j])}
		var rng Range
		switch st[j] {
		case exact.Basic:
			vi.Status = "basic"
			p := posOf[j]
			for k := 0; k < n+mm; k++ {
				if st[k] == exact.Basic || fixed(k) {
					continue
				}
				t := tab(p, k)
				if t.Sign() == 0 {
					continue
				}
				bound := new(big.Rat).Quo(dOf(k), t) // d_k / T
				switch st[k] {
				case exact.AtLower: // need d_k - Δ T >= 0
					if t.Sign() > 0 {
						tighten(&rng, nil, bound)
					} else {
						tighten(&rng, bound, nil)
					}
				case exact.AtUpper: // need d_k - Δ T <= 0
					if t.Sign() > 0 {
						tighten(&rng, bound, nil)
					} else {
						tighten(&rng, nil, bound)
					}
				default: // free nonbasic: d_k must stay 0
					tighten(&rng, new(big.Rat), new(big.Rat))
				}
			}
		case exact.AtLower:
			vi.Status = "at lower"
			if !fixed(j) {
				rng.Lo = new(big.Rat).Neg(d[j])
			}
		case exact.AtUpper:
			vi.Status = "at upper"
			if !fixed(j) {
				rng.Hi = new(big.Rat).Neg(d[j])
			}
		default:
			vi.Status = "free"
			rng.Lo, rng.Hi = new(big.Rat), new(big.Rat)
		}
		// rng is the allowed change Δ of the min-sense cost; make it an interval of costs
		abs := Range{}
		if rng.Lo != nil {
			abs.Lo = new(big.Rat).Add(cost[j], rng.Lo)
		}
		if rng.Hi != nil {
			abs.Hi = new(big.Rat).Add(cost[j], rng.Hi)
		}
		if m.Maximize {
			abs = negRange(abs)
		}
		vi.CostRange = abs
		rep.Vars = append(rep.Vars, vi)
	}

	for i, row := range m.Rows {
		k := n + i
		ri := RowInfo{Name: row.Name, Activity: r[i], Dual: sgn(y[i])}
		slackLo, slackHi := (*big.Rat)(nil), (*big.Rat)(nil)
		if row.Lo != nil {
			slackLo = new(big.Rat).Sub(r[i], row.Lo)
		}
		if row.Hi != nil {
			slackHi = new(big.Rat).Sub(row.Hi, r[i])
		}
		switch {
		case slackLo == nil:
			ri.Slack = slackHi
		case slackHi == nil:
			ri.Slack = slackLo
		case slackLo.Cmp(slackHi) < 0:
			ri.Slack = slackLo
		default:
			ri.Slack = slackHi
		}
		switch st[k] {
		case exact.Basic:
			// non-binding: its limits may move until the activity is touched
			if row.Lo != nil {
				ri.LimitRange.Hi = new(big.Rat).Set(r[i])
			}
			if row.Hi != nil {
				ri.LimitRange.Lo = new(big.Rat).Set(r[i])
			}
			if row.Lo != nil && row.Hi != nil {
				ri.Binding = ""
			}
		default:
			if st[k] == exact.AtLower {
				ri.Binding = "lower"
			} else {
				ri.Binding = "upper"
			}
			if fixed(k) {
				ri.Binding = "equality"
			}
			// moving the binding limit by δ moves basic p by -T[p][k] δ
			var dr Range
			for p, bk := range idx {
				t := tab(p, k)
				if t.Sign() == 0 {
					continue
				}
				// lo_bk <= x_bk - t δ <= hi_bk
				var xv *big.Rat
				if bk < n {
					xv = x[bk]
				} else {
					xv = r[bk-n]
				}
				var dLo, dHi *big.Rat        // δ bounds from this basic variable
				if lb := lo(bk); lb != nil { // x - tδ >= lb  -> tδ <= x-lb
					q := new(big.Rat).Quo(new(big.Rat).Sub(xv, lb), t)
					if t.Sign() > 0 {
						dHi = q
					} else {
						dLo = q
					}
				}
				if ub := hi(bk); ub != nil { // x - tδ <= ub  -> tδ >= x-ub
					q := new(big.Rat).Quo(new(big.Rat).Sub(xv, ub), t)
					if t.Sign() > 0 {
						dLo = maxRat(dLo, q)
					} else {
						dHi = minRat(dHi, q)
					}
				}
				tighten(&dr, dLo, dHi)
			}
			var cur *big.Rat
			if st[k] == exact.AtLower {
				cur = row.Lo
			} else {
				cur = row.Hi
			}
			if row.Lo != nil && row.Hi != nil { // a limit may not cross its opposite limit
				span := new(big.Rat).Sub(row.Hi, row.Lo)
				if st[k] == exact.AtLower {
					tighten(&dr, nil, span)
				} else {
					tighten(&dr, neg(span), nil)
				}
			}
			if dr.Lo != nil {
				ri.LimitRange.Lo = new(big.Rat).Add(cur, dr.Lo)
			}
			if dr.Hi != nil {
				ri.LimitRange.Hi = new(big.Rat).Add(cur, dr.Hi)
			}
		}
		rep.Rows = append(rep.Rows, ri)
	}
	return rep, nil
}

func maxRat(a, b *big.Rat) *big.Rat {
	if a == nil || b.Cmp(a) > 0 {
		return b
	}
	return a
}
func minRat(a, b *big.Rat) *big.Rat {
	if a == nil || b.Cmp(a) < 0 {
		return b
	}
	return a
}
