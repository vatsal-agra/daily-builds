package tabula

import (
	"fmt"
	"sort"
	"strings"
)

// Diagnostic is one finding from pre-flight analysis.
type Diagnostic struct {
	Fatal bool   `json:"fatal"` // true = provably no timetable exists
	Msg   string `json:"msg"`
}

func (d Diagnostic) String() string {
	if d.Fatal {
		return "IMPOSSIBLE: " + d.Msg
	}
	return "warning: " + d.Msg
}

func popcnt(m uint32) int {
	n := 0
	for ; m != 0; m &= m - 1 {
		n++
	}
	return n
}

// Diagnose looks for counting/pigeonhole proofs that no feasible timetable exists
// (and suspicious-but-legal setups). A problem with no fatal diagnostics may
// still be infeasible; the constructive search settles that.
func (in *Instance) Diagnose() []Diagnostic {
	var out []Diagnostic
	seenMsg := map[string]bool{}
	add := func(fatal bool, f string, a ...any) {
		m := fmt.Sprintf(f, a...)
		if !seenMsg[m] {
			seenMsg[m] = true
			out = append(out, Diagnostic{fatal, m})
		}
	}
	fatal := func(f string, a ...any) { add(true, f, a...) }
	warn := func(f string, a ...any) { add(false, f, a...) }
	p := in.P
	total := in.D * in.N

	// 1. events that can never be placed
	for i := range in.Events {
		e := &in.Events[i]
		l := p.Lessons[e.Lesson]
		if len(e.Rooms) == 0 {
			kind := "an ordinary classroom"
			if l.RoomKind != "" {
				kind = fmt.Sprintf("a %q room", l.RoomKind)
			}
			fatal("lesson %s needs %s seating %d, but no such room exists (largest matching: %d)",
				l.ID, kind, e.Size, in.largestRoom(l.RoomKind))
		}
		if len(e.Starts) == 0 {
			if e.Session < len(l.Fixed) {
				f := l.Fixed[e.Session]
				fatal("lesson %s session %d is fixed at %s period %d, which teacher %s cannot do (unavailable, break, or runs past the day)",
					l.ID, e.Session+1, p.DayName(f[0]), f[1]+1, p.Teachers[e.Teacher].ID)
			} else {
				fatal("lesson %s (%d-period sessions) fits nowhere in teacher %s's availability", l.ID, e.Dur, p.Teachers[e.Teacher].ID)
			}
		}
	}

	// 2. lesson sessions need distinct days
	for li, l := range p.Lessons {
		days := map[int]bool{}
		for _, ei := range in.LessonEv[li] {
			for _, s := range in.Events[ei].Starts {
				days[s/in.N] = true
			}
		}
		if len(days) > 0 && len(days) < l.Sessions {
			fatal("lesson %s has %d sessions but only %d usable day(s) for teacher %s", l.ID, l.Sessions, len(days), l.Teacher)
		}
	}

	// 3. teacher load
	for ti, t := range p.Teachers {
		need := 0
		var lessons []string
		for _, e := range in.Events {
			if e.Teacher == ti {
				need += e.Dur
			}
		}
		for _, l := range p.Lessons {
			if l.Teacher == t.ID {
				lessons = append(lessons, l.ID)
			}
		}
		avail, capDays := 0, 0
		for d := 0; d < in.D; d++ {
			free := in.N - popcnt(in.unavail[ti][d])
			avail += free
			if t.MaxPerDay > 0 && free > t.MaxPerDay {
				free = t.MaxPerDay
			}
			capDays += free
		}
		if need > avail {
			fatal("teacher %s must teach %d periods/week but is available for only %d (lessons: %s)", t.ID, need, avail, strings.Join(lessons, ", "))
		} else if need > capDays {
			fatal("teacher %s must teach %d periods/week but max_per_day=%d allows only %d", t.ID, need, t.MaxPerDay, capDays)
		} else if need*10 > avail*9 && need > 0 {
			warn("teacher %s is %d%% booked (%d of %d available periods) - little room to optimise", t.ID, need*100/avail, need, avail)
		}
	}

	// 4. group load
	for _, g := range p.Groups {
		need := 0
		var lessons []string
		for _, l := range p.Lessons {
			for _, id := range l.Groups {
				if id == g.ID {
					need += l.Sessions * l.Duration
					lessons = append(lessons, l.ID)
				}
			}
		}
		if need > total {
			fatal("group %s must attend %d periods/week but the week has only %d (lessons: %s)", g.ID, need, total, strings.Join(lessons, ", "))
		}
	}

	// 5. room pigeonhole (Hall's condition on each distinct allowed-room set)
	type setInfo struct {
		rooms map[int]bool
		key   string
	}
	sets := map[string]*setInfo{}
	for i := range in.Events {
		e := &in.Events[i]
		if len(e.Rooms) == 0 {
			continue
		}
		k := fmt.Sprint(e.Rooms)
		if sets[k] == nil {
			si := &setInfo{rooms: map[int]bool{}, key: k}
			for _, r := range e.Rooms {
				si.rooms[r] = true
			}
			sets[k] = si
		}
	}
	var keys []string
	for k := range sets {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		si := sets[k]
		need := 0
		for i := range in.Events {
			e := &in.Events[i]
			if len(e.Rooms) == 0 {
				continue
			}
			sub := true
			for _, r := range e.Rooms {
				if !si.rooms[r] {
					sub = false
					break
				}
			}
			if sub {
				need += e.Dur
			}
		}
		if have := len(si.rooms) * total; need > have {
			var names []string
			for r := range si.rooms {
				names = append(names, p.Rooms[r].ID)
			}
			sort.Strings(names)
			fatal("room shortage: %d room-periods are needed by lessons that can only use {%s}, but those rooms offer %d", need, strings.Join(names, ","), have)
		}
	}

	// 6. fixed-slot clashes
	type key struct {
		kind string
		id   int
		slot int
	}
	owner := map[key]string{}
	for i := range in.Events {
		e := &in.Events[i]
		l := p.Lessons[e.Lesson]
		if e.Session >= len(l.Fixed) || len(e.Starts) != 1 {
			continue
		}
		s := e.Starts[0]
		for k := 0; k < e.Dur; k++ {
			ks := []key{{"teacher", e.Teacher, s + k}}
			for _, g := range e.Groups {
				ks = append(ks, key{"group", g, s + k})
			}
			for _, kk := range ks {
				if o, ok := owner[kk]; ok && o != e.Name {
					nm := p.Teachers[e.Teacher].ID
					if kk.kind == "group" {
						nm = p.Groups[kk.id].ID
					}
					fatal("fixed lessons %s and %s both claim %s %s at %s period %d", o, e.Name, kk.kind, nm, p.DayName(kk.slot/in.N), kk.slot%in.N+1)
				} else {
					owner[kk] = e.Name
				}
			}
		}
	}
	return out
}

func (in *Instance) largestRoom(kind string) int {
	m := 0
	for _, r := range in.P.Rooms {
		if r.Kind == kind && r.Capacity > m {
			m = r.Capacity
		}
	}
	return m
}

// HasFatal reports whether any diagnostic is a proof of infeasibility.
func HasFatal(ds []Diagnostic) bool {
	for _, d := range ds {
		if d.Fatal {
			return true
		}
	}
	return false
}
