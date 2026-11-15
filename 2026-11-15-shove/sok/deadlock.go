package sok

import "math"

const inf = math.MaxInt32

// Analysis holds precomputed static data for a level.
type Analysis struct {
	Lv *Level
	// PushDist[g][c] = minimum number of pushes needed to bring a lone box
	// from cell c to goal cells[g] (ignoring other boxes); inf if impossible.
	Goals    []int
	PushDist [][]int32
	Dead     []bool // box on this cell can never reach any goal
}

// Analyze computes the reverse (pull) distance tables and dead squares.
// A box can be pushed c -> c+d iff c-d and c+d are both free of walls, so we
// BFS backwards from each goal with that rule.
func Analyze(lv *Level) *Analysis {
	n := lv.W * lv.H
	a := &Analysis{Lv: lv, Dead: make([]bool, n)}
	for i, g := range lv.Goal {
		if g {
			a.Goals = append(a.Goals, i)
		}
	}
	a.PushDist = make([][]int32, len(a.Goals))
	reach := make([]bool, n)
	for gi, g := range a.Goals {
		dist := make([]int32, n)
		for i := range dist {
			dist[i] = inf
		}
		dist[g] = 0
		q := []int{g}
		for len(q) > 0 {
			c := q[0]
			q = q[1:]
			for d := 0; d < 4; d++ {
				// A box at p=c-d pushed in direction d lands on c; player stands at c-2d.
				p := c - delta(d, lv.W)
				pl := p - delta(d, lv.W)
				if p < 0 || pl < 0 || lv.Wall[p] || lv.Wall[pl] || dist[p] != inf {
					continue
				}
				dist[p] = dist[c] + 1
				q = append(q, p)
			}
		}
		a.PushDist[gi] = dist
		for i, d := range dist {
			if d != inf {
				reach[i] = true
			}
		}
	}
	for i := 0; i < n; i++ {
		a.Dead[i] = !lv.Wall[i] && !reach[i]
	}
	return a
}

// FreezeDeadlock reports whether the box at cell p belongs to a frozen group
// that contains at least one box not on a goal. boxAt is a membership grid.
func (a *Analysis) FreezeDeadlock(boxAt []bool, p int) bool {
	var frozenList []int
	state := map[int]int8{} // 1 in progress, 2 frozen, 3 not frozen
	var frozen func(c int) bool
	blocked := func(c, d int) bool {
		step := 1
		if d == 1 {
			step = a.Lv.W
		}
		x, y := c-step, c+step
		if a.Lv.Wall[x] || a.Lv.Wall[y] {
			return true
		}
		if a.Dead[x] && a.Dead[y] {
			return true
		}
		for _, o := range [2]int{x, y} {
			if boxAt[o] {
				switch state[o] {
				case 1, 2:
					return true
				case 3:
					continue
				}
				if frozen(o) {
					return true
				}
			}
		}
		return false
	}
	frozen = func(c int) bool {
		state[c] = 1
		r := blocked(c, 0) && blocked(c, 1)
		if r {
			state[c] = 2
			frozenList = append(frozenList, c)
		} else {
			state[c] = 3
		}
		return r
	}
	if !frozen(p) {
		return false
	}
	for _, f := range frozenList {
		if !a.Lv.Goal[f] {
			return true
		}
	}
	return false
}
