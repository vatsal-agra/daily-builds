package tabula

import (
	"math"
	"math/rand"
	"time"
)

// AnnealStats reports what the optimiser did.
type AnnealStats struct {
	Iters        int
	Accepted     int
	StartCost    int
	FinalCost    int
	Moves, Swaps int
}

// Anneal improves a complete, feasible assignment by simulated annealing.
// Every neighbour is checked against the hard constraints, so the search never
// leaves the feasible region. Deltas are evaluated incrementally (only the
// teachers/groups/lessons touched by the move are re-costed).
func (in *Instance) Anneal(start *Assignment, seed int64, budget time.Duration, maxIters int) (*Assignment, AnnealStats) {
	rng := rand.New(rand.NewSource(seed))
	st, ok := in.LoadAssignment(start)
	if !ok {
		panic("Anneal: starting assignment is not feasible")
	}
	sc := in.newScratch()
	cur, _ := in.Cost(st.A)
	stats := AnnealStats{StartCost: cur}
	best := st.A.Clone()
	bestCost := cur
	n := len(in.Events)
	if n == 0 {
		stats.FinalCost = cur
		return best, stats
	}
	w := in.W
	t0 := float64(max(w.GroupGap, w.TeacherGap, 4)) * 1.5
	t1 := 0.15
	deadline := time.Now().Add(budget)
	if maxIters <= 0 {
		maxIters = 1 << 62
	}
	// temperature is a function of elapsed fraction (time budget) or iteration fraction
	frac := func(i int) float64 {
		if maxIters < 1<<62 {
			return float64(i) / float64(maxIters)
		}
		el := float64(time.Since(deadline.Add(-budget))) / float64(budget)
		return el
	}
	T := t0
	for it := 0; it < maxIters; it++ {
		if it&255 == 0 {
			f := frac(it)
			if f >= 1 {
				break
			}
			T = t0 * math.Pow(t1/t0, f)
		}
		stats.Iters++
		e := rng.Intn(n)
		ev := &in.Events[e]
		if rng.Intn(3) != 0 {
			// MOVE e to a random (slot, room)
			s := ev.Starts[rng.Intn(len(ev.Starts))]
			r := ev.Rooms[rng.Intn(len(ev.Rooms))]
			os, or := st.A.Slot[e], st.A.Room[e]
			if s == os && r == or {
				continue
			}
			before := st.localCost(sc, e)
			st.Unplace(e)
			if !st.CanPlace(e, s, r) {
				st.Place(e, os, or)
				continue
			}
			st.Place(e, s, r)
			delta := st.localCost(sc, e) - before
			if delta <= 0 || rng.Float64() < math.Exp(-float64(delta)/T) {
				cur += delta
				stats.Accepted++
				stats.Moves++
			} else {
				st.Unplace(e)
				st.Place(e, os, or)
			}
		} else {
			// SWAP the start slots of e and a random f (rooms re-picked if needed)
			f := rng.Intn(n)
			if f == e {
				continue
			}
			fe := &in.Events[f]
			se, re := st.A.Slot[e], st.A.Room[e]
			sf, rf := st.A.Slot[f], st.A.Room[f]
			if se == sf || !contains(ev.Starts, sf) || !contains(fe.Starts, se) {
				continue
			}
			before := st.localCost(sc, e, f)
			st.Unplace(e)
			st.Unplace(f)
			ne, nf := -1, -1
			// e goes to sf; try f's old room first, else any allowed room
			for _, r := range roomOrder(ev.Rooms, rf, rng) {
				if st.CanPlace(e, sf, r) {
					ne = r
					break
				}
			}
			if ne >= 0 {
				st.Place(e, sf, ne)
				for _, r := range roomOrder(fe.Rooms, re, rng) {
					if st.CanPlace(f, se, r) {
						nf = r
						break
					}
				}
				if nf >= 0 {
					st.Place(f, se, nf)
					delta := st.localCost(sc, e, f) - before
					if delta <= 0 || rng.Float64() < math.Exp(-float64(delta)/T) {
						cur += delta
						stats.Accepted++
						stats.Swaps++
						goto done
					}
					st.Unplace(f)
				}
				st.Unplace(e)
			}
			st.Place(e, se, re)
			st.Place(f, sf, rf)
		}
	done:
		if cur < bestCost {
			bestCost = cur
			copy(best.Slot, st.A.Slot)
			copy(best.Room, st.A.Room)
		}
	}
	stats.FinalCost = bestCost
	return best, stats
}

func contains(xs []int, v int) bool {
	for _, x := range xs {
		if x == v {
			return true
		}
	}
	return false
}

// roomOrder yields `pref` first (if allowed) then the other allowed rooms in random order.
func roomOrder(rooms []int, pref int, rng *rand.Rand) []int {
	out := make([]int, 0, len(rooms))
	if contains(rooms, pref) {
		out = append(out, pref)
	}
	start := rng.Intn(len(rooms))
	for i := range rooms {
		r := rooms[(start+i)%len(rooms)]
		if r != pref {
			out = append(out, r)
		}
	}
	return out
}
