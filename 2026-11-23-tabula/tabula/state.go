package tabula

import "math/bits"

// State tracks occupancy of a (partial) timetable with per-day bitmasks, so
// feasibility tests and updates are a handful of machine instructions.
type State struct {
	in      *Instance
	A       *Assignment
	tm, gm  [][]uint32 // [teacher|group][day] busy periods
	rm      [][]uint32 // [room][day]
	lessonD []uint32   // [lesson] bitmask of days used
	startAt [][]int    // [slot] events starting there (kept in sync by Place/Unplace)
	placed  int
}

func NewState(in *Instance) *State {
	st := &State{in: in, A: newAssignment(len(in.Events))}
	mk := func(n int) [][]uint32 {
		m := make([][]uint32, n)
		for i := range m {
			m[i] = make([]uint32, in.D)
		}
		return m
	}
	st.tm, st.gm, st.rm = mk(len(in.P.Teachers)), mk(len(in.P.Groups)), mk(len(in.P.Rooms))
	st.lessonD = make([]uint32, len(in.P.Lessons))
	st.startAt = make([][]int, in.D*in.N)
	return st
}

// CanPlace reports whether event e could start at slot s in room r given what is placed
// (e itself must currently be unplaced).
func (st *State) CanPlace(e, s, r int) bool {
	in := st.in
	ev := &in.Events[e]
	d, p := s/in.N, uint(s%in.N)
	b := ev.bits << p
	if st.tm[ev.Teacher][d]&b != 0 || st.rm[r][d]&b != 0 || st.lessonD[ev.Lesson]&(1<<uint(d)) != 0 {
		return false
	}
	if m := in.P.Teachers[ev.Teacher].MaxPerDay; m > 0 && bits.OnesCount32(st.tm[ev.Teacher][d])+ev.Dur > m {
		return false
	}
	for _, g := range ev.Groups {
		if st.gm[g][d]&b != 0 {
			return false
		}
	}
	return true
}

func (st *State) Place(e, s, r int) {
	in := st.in
	ev := &in.Events[e]
	d, p := s/in.N, uint(s%in.N)
	b := ev.bits << p
	st.tm[ev.Teacher][d] |= b
	st.rm[r][d] |= b
	for _, g := range ev.Groups {
		st.gm[g][d] |= b
	}
	st.lessonD[ev.Lesson] |= 1 << uint(d)
	st.A.Slot[e], st.A.Room[e] = s, r
	st.startAt[s] = append(st.startAt[s], e)
	st.placed++
}

func (st *State) Unplace(e int) {
	in := st.in
	ev := &in.Events[e]
	s, r := st.A.Slot[e], st.A.Room[e]
	d, p := s/in.N, uint(s%in.N)
	b := ev.bits << p
	st.tm[ev.Teacher][d] &^= b
	st.rm[r][d] &^= b
	for _, g := range ev.Groups {
		st.gm[g][d] &^= b
	}
	st.lessonD[ev.Lesson] &^= 1 << uint(d)
	st.A.Slot[e], st.A.Room[e] = -1, -1
	l := st.startAt[s]
	for i, x := range l {
		if x == e {
			l[i] = l[len(l)-1]
			st.startAt[s] = l[:len(l)-1]
			break
		}
	}
	st.placed--
}

// LoadAssignment places a complete assignment into a fresh state, failing if it conflicts.
func (in *Instance) LoadAssignment(a *Assignment) (*State, bool) {
	st := NewState(in)
	for e := range in.Events {
		if a.Slot[e] < 0 {
			return st, false
		}
		if !st.CanPlace(e, a.Slot[e], a.Room[e]) {
			return st, false
		}
		st.Place(e, a.Slot[e], a.Room[e])
	}
	return st, true
}
