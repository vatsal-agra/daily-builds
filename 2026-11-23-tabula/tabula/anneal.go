package tabula

import (
	"math"
	"math/rand"
	"time"
)

// AnnealStats reports what the optimiser did.
type AnnealStats struct {
	Iters               int
	Accepted            int
	StartCost           int
	FinalCost           int
	Moves, Swaps, Kempe int
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
		switch k := rng.Intn(10); {
		case k >= 8:
			// KEMPE chain: swap two whole time slots for the connected set of events
			// that would otherwise clash (classic move for dense timetables).
			s2 := ev.Starts[rng.Intn(len(ev.Starts))]
			chain, ok := st.kempeChain(e, s2, sc)
			if !ok {
				continue
			}
			before := st.localCost(sc, chain...)
			saved := make([][2]int, len(chain))
			for i, x := range chain {
				saved[i] = [2]int{st.A.Slot[x], st.A.Room[x]}
			}
			s1 := st.A.Slot[e]
			for _, x := range chain {
				st.Unplace(x)
			}
			okAll := true
			for i, x := range chain {
				to := s2
				if saved[i][0] == s2 {
					to = s1
				}
				placedRoom := -1
				for _, r := range roomOrder(in.Events[x].Rooms, saved[i][1], rng) {
					if st.CanPlace(x, to, r) {
						placedRoom = r
						break
					}
				}
				if placedRoom < 0 {
					for _, y := range chain[:i] {
						st.Unplace(y)
					}
					okAll = false
					break
				}
				st.Place(x, to, placedRoom)
			}
			if okAll {
				delta := st.localCost(sc, chain...) - before
				if delta <= 0 || rng.Float64() < math.Exp(-float64(delta)/T) {
					cur += delta
					stats.Accepted++
					stats.Kempe++
					break
				}
				for _, x := range chain {
					st.Unplace(x)
				}
			}
			for i, x := range chain {
				st.Place(x, saved[i][0], saved[i][1])
			}
		case k >= 0 && k < 5:
			// MOVE e: with probability 1/4 only change its room, otherwise relocate it to a
			// randomly chosen *feasible* (slot, room) - several random probes, since in a dense
			// timetable most uniformly random targets clash.
			os, or := st.A.Slot[e], st.A.Room[e]
			before := st.localCost(sc, e)
			st.Unplace(e)
			s, r, found := os, or, false
			if rng.Intn(4) == 0 {
				if len(ev.Rooms) > 1 {
					r = ev.Rooms[rng.Intn(len(ev.Rooms))]
					found = r != or && st.CanPlace(e, s, r)
				}
			} else {
				for try := 0; try < 12 && !found; try++ {
					s = ev.Starts[rng.Intn(len(ev.Starts))]
					r = ev.Rooms[rng.Intn(len(ev.Rooms))]
					found = (s != os || r != or) && st.CanPlace(e, s, r)
				}
			}
			if !found {
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
		default:
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

// kempeChain returns the set of events that must move together if e moves to start
// slot s2 and the events occupying s2 are bounced back to e's old slot. The chain
// closes over teacher/group conflicts. Only equal-length sessions on disjoint slot
// ranges are chained; anything else aborts (ok=false).
func (st *State) kempeChain(e, s2 int, sc *scratch) ([]int, bool) {
	in := st.in
	s1 := st.A.Slot[e]
	d := in.Events[e].Dur
	if s1 == s2 || (s1 < s2 && s1+d > s2) || (s2 < s1 && s2+d > s1) {
		return nil, false
	}
	sc.stamp++
	if sc.eSeen == nil {
		sc.eSeen = make([]int, len(in.Events))
	}
	chain := []int{e}
	sc.eSeen[e] = sc.stamp
	for i := 0; i < len(chain); i++ {
		x := chain[i]
		ex := &in.Events[x]
		to := s2
		if st.A.Slot[x] == s2 {
			to = s1
		}
		if !contains(ex.Starts, to) {
			return nil, false
		}
		for _, y := range st.startAt[to] {
			if sc.eSeen[y] == sc.stamp {
				continue
			}
			ey := &in.Events[y]
			clash := ey.Teacher == ex.Teacher
			for _, g := range ex.Groups {
				for _, h := range ey.Groups {
					clash = clash || g == h
				}
			}
			if !clash {
				continue
			}
			if ey.Dur != d || len(chain) >= 12 {
				return nil, false
			}
			sc.eSeen[y] = sc.stamp
			chain = append(chain, y)
		}
	}
	return chain, true
}
