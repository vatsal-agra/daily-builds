package tabula

import "math/bits"

// Cost categories (stable names are used in JSON/HTML output).
const (
	cGroupGap = iota
	cTeacherGap
	cLongDay
	cLate
	cTeacherDay
	cSpread
	cAvoid
	cRoomWaste
	cStability
	nCat
)

var CatNames = [nCat]string{"group_gaps", "teacher_gaps", "long_days", "late_periods", "teacher_days", "spread", "avoided_slots", "room_waste", "instability"}

// gaps counts empty periods strictly between the first and last used period.
func gaps(m uint32) int {
	if m == 0 {
		return 0
	}
	lo := bits.TrailingZeros32(m)
	hi := 31 - bits.LeadingZeros32(m)
	return hi - lo + 1 - bits.OnesCount32(m)
}

func (in *Instance) groupDayCost(m uint32, acc *[nCat]int) int {
	if m == 0 {
		return 0
	}
	w := in.W
	g := gaps(m) * w.GroupGap
	l := 0
	if n := bits.OnesCount32(m); w.MaxDaily > 0 && n > w.MaxDaily {
		l = (n - w.MaxDaily) * w.LongDay
	}
	late := 0
	if w.LateFrom > 0 {
		late = bits.OnesCount32(m>>uint(w.LateFrom)) * w.Late
	}
	if acc != nil {
		acc[cGroupGap] += g
		acc[cLongDay] += l
		acc[cLate] += late
	}
	return g + l + late
}

func (in *Instance) teacherDayCost(t, d int, m uint32, acc *[nCat]int) int {
	if m == 0 {
		return 0
	}
	g := gaps(m) * in.W.TeacherGap
	day := in.W.TeacherDay
	av := bits.OnesCount32(m&in.avoid[t][d]) * in.W.Avoid
	if acc != nil {
		acc[cTeacherGap] += g
		acc[cTeacherDay] += day
		acc[cAvoid] += av
	}
	return g + day + av
}

func (in *Instance) spreadCost(dm uint32, acc *[nCat]int) int {
	c := bits.OnesCount32(dm&(dm>>1)) * in.W.Spread
	if acc != nil {
		acc[cSpread] += c
	}
	return c
}

func (in *Instance) eventCost(e, s, r int, prev *Assignment, acc *[nCat]int) int {
	ev := &in.Events[e]
	waste := (in.P.Rooms[r].Capacity - ev.Size) * in.W.RoomWaste / 10
	stab := 0
	if prev != nil && prev.Slot[e] >= 0 && (prev.Slot[e] != s || (prev.Room[e] >= 0 && prev.Room[e] != r)) {
		stab = in.W.Stability
	}
	if acc != nil {
		acc[cRoomWaste] += waste
		acc[cStability] += stab
	}
	return waste + stab
}

// Prev is the previous timetable used by the stability term (nil = none).
// It is stored on the Instance so Cost and the optimiser agree.
func (in *Instance) SetPrevious(a *Assignment) { in.prev = a }

// Cost recomputes the full soft cost of a complete assignment from scratch.
func (in *Instance) Cost(a *Assignment) (int, map[string]int) {
	st := NewState(in)
	for e := range in.Events {
		if a.Slot[e] >= 0 {
			st.Place(e, a.Slot[e], a.Room[e])
		}
	}
	var acc [nCat]int
	total := 0
	for g := range in.P.Groups {
		for d := 0; d < in.D; d++ {
			total += in.groupDayCost(st.gm[g][d], &acc)
		}
	}
	for t := range in.P.Teachers {
		for d := 0; d < in.D; d++ {
			total += in.teacherDayCost(t, d, st.tm[t][d], &acc)
		}
	}
	for l := range in.P.Lessons {
		total += in.spreadCost(st.lessonD[l], &acc)
	}
	for e := range in.Events {
		if a.Slot[e] >= 0 {
			total += in.eventCost(e, a.Slot[e], a.Room[e], in.prev, &acc)
		}
	}
	bd := map[string]int{}
	for i, n := range CatNames {
		bd[n] = acc[i]
	}
	return total, bd
}

// local evaluates the cost of everything touched by a set of events in the
// current state; used for before/after deltas.
type scratch struct {
	tSeen, gSeen, lSeen []int
	stamp               int
}

func (in *Instance) newScratch() *scratch {
	return &scratch{tSeen: make([]int, len(in.P.Teachers)), gSeen: make([]int, len(in.P.Groups)), lSeen: make([]int, len(in.P.Lessons))}
}

// localCost sums costs of the teachers/groups/lessons touched by evs plus the
// per-event terms for evs (only those currently placed).
func (st *State) localCost(sc *scratch, evs ...int) int {
	in := st.in
	sc.stamp++
	total := 0
	for _, e := range evs {
		ev := &in.Events[e]
		if sc.tSeen[ev.Teacher] != sc.stamp {
			sc.tSeen[ev.Teacher] = sc.stamp
			for d := 0; d < in.D; d++ {
				total += in.teacherDayCost(ev.Teacher, d, st.tm[ev.Teacher][d], nil)
			}
		}
		for _, g := range ev.Groups {
			if sc.gSeen[g] != sc.stamp {
				sc.gSeen[g] = sc.stamp
				for d := 0; d < in.D; d++ {
					total += in.groupDayCost(st.gm[g][d], nil)
				}
			}
		}
		if sc.lSeen[ev.Lesson] != sc.stamp {
			sc.lSeen[ev.Lesson] = sc.stamp
			total += in.spreadCost(st.lessonD[ev.Lesson], nil)
		}
		if st.A.Slot[e] >= 0 {
			total += in.eventCost(e, st.A.Slot[e], st.A.Room[e], in.prev, nil)
		}
	}
	return total
}
