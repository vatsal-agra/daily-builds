package tabula

import (
	"fmt"
	"sort"
)

// Verify re-checks a Solution against a Problem using only the problem's
// definitions (naive per-slot maps; none of the solver's bitmask code) and
// recomputes the soft cost independently. It returns every violation found
// and the independently computed cost.
func Verify(p *Problem, s *Solution, prev *Solution) (violations []string, cost int, breakdown map[string]int) {
	bad := func(f string, a ...any) { violations = append(violations, fmt.Sprintf(f, a...)) }
	w := p.W()
	tIdx, rIdx, gIdx, lIdx := map[string]Teacher{}, map[string]Room{}, map[string]Group{}, map[string]Lesson{}
	for _, t := range p.Teachers {
		tIdx[t.ID] = t
	}
	for _, r := range p.Rooms {
		rIdx[r.ID] = r
	}
	for _, g := range p.Groups {
		gIdx[g.ID] = g
	}
	for _, l := range p.Lessons {
		lIdx[l.ID] = l
	}
	breaks := map[int]bool{}
	for _, b := range p.BreaksAfter {
		breaks[b] = true
	}
	type cell struct {
		kind, id string
		d, p     int
	}
	occ := map[cell]string{}
	claim := func(c cell, who string) {
		if o, ok := occ[c]; ok {
			bad("%s %s is double-booked on %s period %d: %s vs %s", c.kind, c.id, p.DayName(c.d), c.p+1, o, who)
		} else {
			occ[c] = who
		}
	}
	seen := map[string]bool{}
	lessonDays := map[string]map[int]bool{}
	teacherDay := map[[2]interface{}]int{}
	type pk struct {
		l string
		s int
	}
	placed := map[pk]Placement{}
	for _, pl := range s.Placements {
		who := fmt.Sprintf("%s#%d", pl.Lesson, pl.Session)
		l, ok := lIdx[pl.Lesson]
		if !ok {
			bad("%s: unknown lesson", who)
			continue
		}
		if pl.Session < 1 || pl.Session > l.Sessions {
			bad("%s: session number out of range 1..%d", who, l.Sessions)
			continue
		}
		if seen[who] {
			bad("%s placed more than once", who)
			continue
		}
		seen[who] = true
		placed[pk{pl.Lesson, pl.Session}] = pl
		if pl.Duration != l.Duration {
			bad("%s: duration %d, lesson requires %d", who, pl.Duration, l.Duration)
		}
		if pl.Day < 0 || pl.Day >= p.Days || pl.Period < 0 || pl.Period+l.Duration > p.Periods {
			bad("%s: does not fit inside the week/day", who)
			continue
		}
		for k := 0; k < l.Duration-1; k++ {
			if breaks[pl.Period+k] {
				bad("%s: spans a break after period %d", who, pl.Period+k+1)
			}
		}
		r, ok := rIdx[pl.Room]
		if !ok {
			bad("%s: unknown room %q", who, pl.Room)
			continue
		}
		size := 0
		for _, g := range l.Groups {
			size += gIdx[g].Size
		}
		if r.Kind != l.RoomKind {
			bad("%s: room %s has kind %q, lesson needs %q", who, r.ID, r.Kind, l.RoomKind)
		}
		if r.Capacity < size {
			bad("%s: room %s seats %d but %d students attend", who, r.ID, r.Capacity, size)
		}
		if lessonDays[pl.Lesson] == nil {
			lessonDays[pl.Lesson] = map[int]bool{}
		}
		if lessonDays[pl.Lesson][pl.Day] {
			bad("lesson %s has two sessions on %s", pl.Lesson, p.DayName(pl.Day))
		}
		lessonDays[pl.Lesson][pl.Day] = true
		t := tIdx[l.Teacher]
		for k := 0; k < l.Duration; k++ {
			per := pl.Period + k
			for _, u := range t.Unavailable {
				if u[0] == pl.Day && u[1] == per {
					bad("%s: teacher %s is unavailable on %s period %d", who, t.ID, p.DayName(pl.Day), per+1)
				}
			}
			claim(cell{"teacher", t.ID, pl.Day, per}, who)
			claim(cell{"room", r.ID, pl.Day, per}, who)
			for _, g := range l.Groups {
				claim(cell{"group", g, pl.Day, per}, who)
			}
		}
		teacherDay[[2]interface{}{t.ID, pl.Day}] += l.Duration
		if pl.Session-1 < len(l.Fixed) {
			f := l.Fixed[pl.Session-1]
			if pl.Day != f[0] || pl.Period != f[1] {
				bad("%s: pinned to %s period %d but placed elsewhere", who, p.DayName(f[0]), f[1]+1)
			}
		}
	}
	for _, l := range p.Lessons {
		for k := 1; k <= l.Sessions; k++ {
			if !seen[fmt.Sprintf("%s#%d", l.ID, k)] {
				bad("%s#%d is not scheduled", l.ID, k)
			}
		}
	}
	for k, n := range teacherDay {
		t := tIdx[k[0].(string)]
		if t.MaxPerDay > 0 && n > t.MaxPerDay {
			bad("teacher %s teaches %d periods on %s, max_per_day is %d", t.ID, n, p.DayName(k[1].(int)), t.MaxPerDay)
		}
	}
	sort.Strings(violations)

	// ---- independent soft cost, straight from the definitions ----
	breakdown = map[string]int{}
	for _, n := range CatNames {
		breakdown[n] = 0
	}
	busy := func(kind, id string, d, per int) bool { _, ok := occ[cell{kind, id, d, per}]; return ok }
	for d := 0; d < p.Days; d++ {
		for _, g := range p.Groups {
			first, last, n := -1, -1, 0
			for per := 0; per < p.Periods; per++ {
				if busy("group", g.ID, d, per) {
					if first < 0 {
						first = per
					}
					last = per
					n++
					if w.LateFrom > 0 && per >= w.LateFrom {
						breakdown["late_periods"] += w.Late
					}
				}
			}
			if n > 0 {
				breakdown["group_gaps"] += (last - first + 1 - n) * w.GroupGap
				if w.MaxDaily > 0 && n > w.MaxDaily {
					breakdown["long_days"] += (n - w.MaxDaily) * w.LongDay
				}
			}
		}
		for _, t := range p.Teachers {
			first, last, n := -1, -1, 0
			for per := 0; per < p.Periods; per++ {
				if busy("teacher", t.ID, d, per) {
					if first < 0 {
						first = per
					}
					last = per
					n++
					for _, a := range t.Avoid {
						if a[0] == d && a[1] == per {
							breakdown["avoided_slots"] += w.Avoid
						}
					}
				}
			}
			if n > 0 {
				breakdown["teacher_gaps"] += (last - first + 1 - n) * w.TeacherGap
				breakdown["teacher_days"] += w.TeacherDay
			}
		}
	}
	for _, l := range p.Lessons {
		for d := 0; d+1 < p.Days; d++ {
			if lessonDays[l.ID][d] && lessonDays[l.ID][d+1] {
				breakdown["spread"] += w.Spread
			}
		}
	}
	for _, pl := range s.Placements {
		l, ok := lIdx[pl.Lesson]
		if !ok {
			continue
		}
		r, ok := rIdx[pl.Room]
		if !ok {
			continue
		}
		size := 0
		for _, g := range l.Groups {
			size += gIdx[g].Size
		}
		breakdown["room_waste"] += (r.Capacity - size) * w.RoomWaste / 10
		if prev != nil {
			for _, q := range prev.Placements {
				_, roomKnown := rIdx[q.Room]
				if q.Lesson == pl.Lesson && q.Session == pl.Session && (q.Day != pl.Day || q.Period != pl.Period || (roomKnown && q.Room != pl.Room)) {
					breakdown["instability"] += w.Stability
				}
			}
		}
	}
	for _, n := range CatNames {
		cost += breakdown[n]
	}
	return violations, cost, breakdown
}
