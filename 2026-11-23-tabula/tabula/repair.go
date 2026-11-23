package tabula

import (
	"fmt"
	"math/rand"
	"sort"
	"time"
)

// repair is a min-conflicts tabu search over *infeasible* timetables: every event
// always has a position, and we minimise the number of hard-constraint
// violations down to zero. It succeeds on tight instances where plain
// backtracking thrashes.
type repair struct {
	in     *Instance
	rng    *rand.Rand
	tc, gc [][]int16 // [teacher|group][slot] occupancy count
	rc     [][]int16 // [room][slot]
	ld     [][]int16 // [lesson][day] sessions on that day
	td     [][]int16 // [teacher][day] periods taught
	slot   []int
	room   []int
	viol   int
	tabu   []int32 // [event*S + slot] step until which re-entering is forbidden
	S      int
}

func (in *Instance) newRepair(rng *rand.Rand) *repair {
	r := &repair{in: in, rng: rng, S: in.D * in.N}
	mk := func(n, w int) [][]int16 {
		m := make([][]int16, n)
		for i := range m {
			m[i] = make([]int16, w)
		}
		return m
	}
	r.tc, r.gc, r.rc = mk(len(in.P.Teachers), r.S), mk(len(in.P.Groups), r.S), mk(len(in.P.Rooms), r.S)
	r.ld, r.td = mk(len(in.P.Lessons), in.D), mk(len(in.P.Teachers), in.D)
	r.slot, r.room = make([]int, len(in.Events)), make([]int, len(in.Events))
	for i := range r.slot {
		r.slot[i] = -1
	}
	r.tabu = make([]int32, len(in.Events)*r.S)
	return r
}

func over(td int16, max int) int {
	if max <= 0 || int(td) <= max {
		return 0
	}
	return int(td) - max
}

// addCost is the number of violations event e would add at (s, rm) (e must not be placed).
func (r *repair) addCost(e, s, rm int) int {
	in := r.in
	ev := &in.Events[e]
	d := s / in.N
	c := 0
	for k := 0; k < ev.Dur; k++ {
		x := s + k
		if r.tc[ev.Teacher][x] > 0 {
			c++
		}
		if r.rc[rm][x] > 0 {
			c++
		}
		for _, g := range ev.Groups {
			if r.gc[g][x] > 0 {
				c++
			}
		}
	}
	if r.ld[ev.Lesson][d] > 0 {
		c++
	}
	m := in.P.Teachers[ev.Teacher].MaxPerDay
	c += over(r.td[ev.Teacher][d]+int16(ev.Dur), m) - over(r.td[ev.Teacher][d], m)
	return c
}

func (r *repair) add(e, s, rm int) {
	r.viol += r.addCost(e, s, rm)
	in := r.in
	ev := &in.Events[e]
	d := s / in.N
	for k := 0; k < ev.Dur; k++ {
		r.tc[ev.Teacher][s+k]++
		r.rc[rm][s+k]++
		for _, g := range ev.Groups {
			r.gc[g][s+k]++
		}
	}
	r.ld[ev.Lesson][d]++
	r.td[ev.Teacher][d] += int16(ev.Dur)
	r.slot[e], r.room[e] = s, rm
}

func (r *repair) remove(e int) {
	in := r.in
	ev := &in.Events[e]
	s, rm := r.slot[e], r.room[e]
	d := s / in.N
	for k := 0; k < ev.Dur; k++ {
		r.tc[ev.Teacher][s+k]--
		r.rc[rm][s+k]--
		for _, g := range ev.Groups {
			r.gc[g][s+k]--
		}
	}
	r.ld[ev.Lesson][d]--
	r.td[ev.Teacher][d] -= int16(ev.Dur)
	r.slot[e], r.room[e] = -1, -1
	// violations the event contributed = what adding it back would cost now
	r.viol -= r.addCost(e, s, rm)
}

// conflicted: does e currently take part in any violation?
func (r *repair) conflicted(e int) bool {
	in := r.in
	ev := &in.Events[e]
	s, rm := r.slot[e], r.room[e]
	d := s / in.N
	for k := 0; k < ev.Dur; k++ {
		if r.tc[ev.Teacher][s+k] > 1 || r.rc[rm][s+k] > 1 {
			return true
		}
		for _, g := range ev.Groups {
			if r.gc[g][s+k] > 1 {
				return true
			}
		}
	}
	return r.ld[ev.Lesson][d] > 1 || over(r.td[ev.Teacher][d], in.P.Teachers[ev.Teacher].MaxPerDay) > 0
}

// Repair searches for a violation-free timetable within the budget.
func (in *Instance) Repair(seed int64, budget time.Duration, prev *Assignment) (*Assignment, int, []string) {
	rng := rand.New(rand.NewSource(seed))
	r := in.newRepair(rng)
	deadline := time.Now().Add(budget)
	n := len(in.Events)
	// greedy initial placement, most constrained (fewest starts*rooms) first
	order := make([]int, n)
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(a, b int) bool {
		ea, eb := &in.Events[order[a]], &in.Events[order[b]]
		return len(ea.Starts)*len(ea.Rooms) < len(eb.Starts)*len(eb.Rooms)
	})
	for _, e := range order {
		ev := &in.Events[e]
		bs, br, bc := -1, -1, 1<<30
		if prev != nil && prev.Slot[e] >= 0 && contains(ev.Starts, prev.Slot[e]) {
			rm := prev.Room[e]
			if rm < 0 || !contains(ev.Rooms, rm) {
				rm = ev.Rooms[rng.Intn(len(ev.Rooms))]
			}
			if c := r.addCost(e, prev.Slot[e], rm); c == 0 {
				r.add(e, prev.Slot[e], rm)
				continue
			}
		}
		ties := 0
		for _, s := range ev.Starts {
			for _, rm := range ev.Rooms {
				c := r.addCost(e, s, rm)
				if c < bc {
					bs, br, bc, ties = s, rm, c, 1
				} else if c == bc {
					ties++
					if rng.Intn(ties) == 0 {
						bs, br = s, rm
					}
				}
			}
		}
		r.add(e, bs, br)
	}
	best := r.viol
	var step int32
	stall := 0
	for r.viol > 0 {
		step++
		if step&127 == 0 && time.Now().After(deadline) {
			break
		}
		// pick a conflicted event (sample, then fall back to a scan)
		e := -1
		for t := 0; t < 30; t++ {
			x := rng.Intn(n)
			if r.conflicted(x) {
				e = x
				break
			}
		}
		if e < 0 {
			var cs []int
			for x := 0; x < n; x++ {
				if r.conflicted(x) {
					cs = append(cs, x)
				}
			}
			if len(cs) == 0 {
				break
			}
			e = cs[rng.Intn(len(cs))]
		}
		ev := &in.Events[e]
		os, orm := r.slot[e], r.room[e]
		r.remove(e)
		bs, br, bc, ties := -1, -1, 1<<30, 0
		if rng.Intn(50) == 0 { // noise
			bs, br = ev.Starts[rng.Intn(len(ev.Starts))], ev.Rooms[rng.Intn(len(ev.Rooms))]
		} else {
			for _, s := range ev.Starts {
				tb := r.tabu[e*r.S+s] > step
				for _, rm := range ev.Rooms {
					c := r.addCost(e, s, rm)
					if tb && !(r.viol+c < best) {
						continue
					}
					if c < bc {
						bs, br, bc, ties = s, rm, c, 1
					} else if c == bc {
						ties++
						if rng.Intn(ties) == 0 {
							bs, br = s, rm
						}
					}
				}
			}
			if bs < 0 {
				bs, br = os, orm
			}
		}
		r.tabu[e*r.S+os] = step + 8 + int32(rng.Intn(10))
		r.add(e, bs, br)
		if r.viol < best {
			best, stall = r.viol, 0
		} else if stall++; stall > 20000 { // stuck: shake a few events loose
			for k := 0; k < 4; k++ {
				x := rng.Intn(n)
				xe := &in.Events[x]
				r.remove(x)
				r.add(x, xe.Starts[rng.Intn(len(xe.Starts))], xe.Rooms[rng.Intn(len(xe.Rooms))])
			}
			stall = 0
		}
	}
	if r.viol == 0 {
		a := &Assignment{Slot: append([]int(nil), r.slot...), Room: append([]int(nil), r.room...)}
		return a, 0, nil
	}
	return nil, r.viol, r.describeConflicts()
}

func (r *repair) describeConflicts() []string {
	in := r.in
	var out []string
	for t := range in.P.Teachers {
		for s := 0; s < r.S; s++ {
			if r.tc[t][s] > 1 {
				out = append(out, fmt.Sprintf("teacher %s double-booked on %s period %d", in.P.Teachers[t].ID, in.P.DayName(s/in.N), s%in.N+1))
			}
		}
	}
	for g := range in.P.Groups {
		for s := 0; s < r.S; s++ {
			if r.gc[g][s] > 1 {
				out = append(out, fmt.Sprintf("group %s double-booked on %s period %d", in.P.Groups[g].ID, in.P.DayName(s/in.N), s%in.N+1))
			}
		}
	}
	for rm := range in.P.Rooms {
		for s := 0; s < r.S; s++ {
			if r.rc[rm][s] > 1 {
				out = append(out, fmt.Sprintf("room %s double-booked on %s period %d", in.P.Rooms[rm].ID, in.P.DayName(s/in.N), s%in.N+1))
			}
		}
	}
	if len(out) > 6 {
		out = append(out[:6], fmt.Sprintf("... and %d more", len(out)-6))
	}
	return out
}
