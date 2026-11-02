// Package assoc solves the data-association problem: which detection came from which track.
package assoc

import (
	"errors"
	"math"
)

// ErrInfeasible means no assignment avoiding forbidden (+Inf) cells exists.
var ErrInfeasible = errors.New("assoc: no feasible assignment")

// Hungarian solves the rectangular assignment problem (rows ≤ cols) minimising total
// cost with the Kuhn–Munkres algorithm in O(n²m) using row/column potentials.
// cost[i][j] may be +Inf to forbid a pairing. It returns col[i] for each row i
// and the total cost.
func Hungarian(cost [][]float64) ([]int, float64, error) {
	n := len(cost)
	if n == 0 {
		return nil, 0, nil
	}
	m := len(cost[0])
	if n > m {
		return nil, 0, errors.New("assoc: Hungarian needs rows <= cols (pad with dummy columns)")
	}
	for _, r := range cost {
		if len(r) != m {
			return nil, 0, errors.New("assoc: ragged cost matrix")
		}
		for _, v := range r {
			if math.IsNaN(v) {
				return nil, 0, errors.New("assoc: NaN in cost matrix")
			}
		}
	}
	// Forbidden cells get a cost larger than any feasible total; if the optimum uses one, it's infeasible.
	big := 1.0
	for _, r := range cost {
		for _, v := range r {
			if !math.IsInf(v, 1) && math.Abs(v) > big {
				big = math.Abs(v)
			}
		}
	}
	big = big*float64(n+1)*4 + 1e6
	c := func(i, j int) float64 {
		if v := cost[i-1][j-1]; !math.IsInf(v, 1) {
			return v
		}
		return big
	}
	u := make([]float64, n+1)
	v := make([]float64, m+1)
	p := make([]int, m+1)   // p[j] = row matched to column j
	way := make([]int, m+1) // augmenting-path back pointers
	for i := 1; i <= n; i++ {
		p[0] = i
		j0 := 0
		minv := make([]float64, m+1)
		used := make([]bool, m+1)
		for j := range minv {
			minv[j] = math.Inf(1)
		}
		for {
			used[j0] = true
			i0, delta, j1 := p[j0], math.Inf(1), 0
			for j := 1; j <= m; j++ {
				if used[j] {
					continue
				}
				if cur := c(i0, j) - u[i0] - v[j]; cur < minv[j] {
					minv[j], way[j] = cur, j0
				}
				if minv[j] < delta {
					delta, j1 = minv[j], j
				}
			}
			for j := 0; j <= m; j++ {
				if used[j] {
					u[p[j]] += delta
					v[j] -= delta
				} else {
					minv[j] -= delta
				}
			}
			j0 = j1
			if p[j0] == 0 {
				break
			}
		}
		for j0 != 0 {
			j1 := way[j0]
			p[j0] = p[j1]
			j0 = j1
		}
	}
	col := make([]int, n)
	total := 0.0
	for j := 1; j <= m; j++ {
		if p[j] != 0 {
			col[p[j]-1] = j - 1
		}
	}
	for i, j := range col {
		if math.IsInf(cost[i][j], 1) {
			return nil, 0, ErrInfeasible
		}
		total += cost[i][j]
	}
	return col, total, nil
}
