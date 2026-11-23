// Package tabula is a school/university timetabling solver: constraint search
// to find a feasible weekly timetable, simulated annealing to optimise it.
package tabula

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

// Slot is a (day, period) pair, JSON-encoded as [day, period], both 0-based.
type Slot [2]int

type Teacher struct {
	ID          string `json:"id"`
	Name        string `json:"name,omitempty"`
	Unavailable []Slot `json:"unavailable,omitempty"` // hard: cannot teach here
	Avoid       []Slot `json:"avoid,omitempty"`       // soft: would rather not
	MaxPerDay   int    `json:"max_per_day,omitempty"` // hard cap on periods/day; 0 = no cap
}

type Room struct {
	ID       string `json:"id"`
	Capacity int    `json:"capacity"`
	Kind     string `json:"kind,omitempty"` // e.g. "lab", "gym"; "" = ordinary classroom
}

type Group struct {
	ID   string `json:"id"`
	Size int    `json:"size"`
}

// Lesson is a weekly requirement: Sessions meetings of Duration periods each,
// taught by one teacher to one or more groups together. Sessions of a lesson
// always fall on different days.
type Lesson struct {
	ID       string   `json:"id"`
	Subject  string   `json:"subject"`
	Teacher  string   `json:"teacher"`
	Groups   []string `json:"groups"`
	Sessions int      `json:"sessions"`
	Duration int      `json:"duration"`
	// RoomKind "" means any room that is big enough and whose Kind is ""
	// (an ordinary classroom); otherwise the room's Kind must match exactly.
	RoomKind string `json:"room_kind,omitempty"`
	// Fixed pins the first len(Fixed) sessions to given start slots.
	Fixed []Slot `json:"fixed,omitempty"`
}

// Weights are the soft-constraint penalties (all integers, per unit).
type Weights struct {
	GroupGap   int `json:"group_gap"`   // empty period between two lessons of a group on one day
	TeacherGap int `json:"teacher_gap"` // same, for teachers
	LongDay    int `json:"long_day"`    // per period over MaxDaily for a group
	MaxDaily   int `json:"max_daily"`   // comfortable lessons per day for a group
	Late       int `json:"late"`        // per group period at/after LateFrom
	LateFrom   int `json:"late_from"`   // first "late" period index (0 disables)
	TeacherDay int `json:"teacher_day"` // per day a teacher has to come in
	Spread     int `json:"spread"`      // per pair of same-lesson sessions on adjacent days
	Avoid      int `json:"avoid"`       // per teacher period in an avoid slot
	RoomWaste  int `json:"room_waste"`  // per 10 surplus seats in the chosen room
	Stability  int `json:"stability"`   // per event that differs from the previous timetable
}

func DefaultWeights() Weights {
	return Weights{GroupGap: 10, TeacherGap: 4, LongDay: 5, MaxDaily: 6, Late: 1, LateFrom: 7,
		TeacherDay: 3, Spread: 2, Avoid: 3, RoomWaste: 1, Stability: 8}
}

type Problem struct {
	Name         string    `json:"name"`
	Days         int       `json:"days"`
	Periods      int       `json:"periods"`
	DayNames     []string  `json:"day_names,omitempty"`
	BreaksAfter  []int     `json:"breaks_after,omitempty"`  // a session may not span the gap after these period indices
	PeriodStarts []string  `json:"period_starts,omitempty"` // "HH:MM" per period, for calendars
	PeriodMins   int       `json:"period_minutes,omitempty"`
	Teachers     []Teacher `json:"teachers"`
	Rooms        []Room    `json:"rooms"`
	Groups       []Group   `json:"groups"`
	Lessons      []Lesson  `json:"lessons"`
	Weights      *Weights  `json:"weights,omitempty"`
}

func (p *Problem) W() Weights {
	if p.Weights != nil {
		return *p.Weights
	}
	return DefaultWeights()
}

func (p *Problem) DayName(d int) string {
	if d < len(p.DayNames) {
		return p.DayNames[d]
	}
	n := []string{"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
	if d < 7 {
		return n[d]
	}
	return fmt.Sprintf("D%d", d+1)
}

// LoadProblem reads and compiles a problem file.
func LoadProblem(path string) (*Problem, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var p Problem
	dec := json.NewDecoder(strings.NewReader(string(b)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p); err != nil {
		return nil, fmt.Errorf("%s: %v", path, err)
	}
	return &p, nil
}

// ValidationError lists every structural problem found.
type ValidationError struct{ Problems []string }

func (v *ValidationError) Error() string {
	return fmt.Sprintf("invalid problem (%d issues):\n  - %s", len(v.Problems), strings.Join(v.Problems, "\n  - "))
}

// Event is one session of a lesson, the unit that gets placed.
type Event struct {
	ID      int
	Lesson  int
	Session int
	Teacher int
	Groups  []int
	Dur     int
	Size    int
	Rooms   []int // allowed rooms (kind + capacity)
	Starts  []int // allowed start slots (d*P+p): availability, breaks, fixed
	Name    string
	bits    uint32 // (1<<Dur)-1
}

// Instance is a compiled, validated problem.
type Instance struct {
	P        *Problem
	D, N     int // days, periods
	W        Weights
	Events   []Event
	TeacherI map[string]int
	RoomI    map[string]int
	GroupI   map[string]int
	LessonI  map[string]int
	unavail  [][]uint32 // [teacher][day] mask
	avoid    [][]uint32
	breakAt  uint32 // bit p set: no session may span between p and p+1
	LessonEv [][]int
	prev     *Assignment
}

// Compile validates p and expands lessons into events.
func Compile(p *Problem) (*Instance, error) {
	var errs []string
	bad := func(f string, a ...any) { errs = append(errs, fmt.Sprintf(f, a...)) }
	if p.Days < 1 || p.Days > 7 {
		bad("days must be 1..7 (got %d)", p.Days)
	}
	if p.Periods < 1 || p.Periods > 24 {
		bad("periods must be 1..24 (got %d)", p.Periods)
	}
	if len(errs) > 0 {
		return nil, &ValidationError{errs}
	}
	in := &Instance{P: p, D: p.Days, N: p.Periods, W: p.W(),
		TeacherI: map[string]int{}, RoomI: map[string]int{}, GroupI: map[string]int{}, LessonI: map[string]int{}}
	if in.W.MaxDaily < 0 || in.W.LateFrom < 0 {
		bad("weights: max_daily and late_from must be >= 0")
	}
	if p.PeriodStarts != nil && len(p.PeriodStarts) != p.Periods {
		bad("period_starts has %d entries, expected %d", len(p.PeriodStarts), p.Periods)
	}
	for _, b := range p.BreaksAfter {
		if b < 0 || b >= p.Periods-1 {
			bad("breaks_after %d out of range 0..%d", b, p.Periods-2)
		} else {
			in.breakAt |= 1 << uint(b)
		}
	}
	inSlot := func(s Slot) bool { return s[0] >= 0 && s[0] < p.Days && s[1] >= 0 && s[1] < p.Periods }
	in.unavail = make([][]uint32, len(p.Teachers))
	in.avoid = make([][]uint32, len(p.Teachers))
	for i, t := range p.Teachers {
		if t.ID == "" {
			bad("teacher #%d has empty id", i)
		} else if _, dup := in.TeacherI[t.ID]; dup {
			bad("duplicate teacher id %q", t.ID)
		}
		in.TeacherI[t.ID] = i
		if t.MaxPerDay < 0 {
			bad("teacher %s: negative max_per_day", t.ID)
		}
		in.unavail[i] = make([]uint32, p.Days)
		in.avoid[i] = make([]uint32, p.Days)
		for _, s := range t.Unavailable {
			if !inSlot(s) {
				bad("teacher %s: unavailable slot %v outside the %dx%d week", t.ID, s, p.Days, p.Periods)
				continue
			}
			in.unavail[i][s[0]] |= 1 << uint(s[1])
		}
		for _, s := range t.Avoid {
			if !inSlot(s) {
				bad("teacher %s: avoid slot %v outside the week", t.ID, s)
				continue
			}
			in.avoid[i][s[0]] |= 1 << uint(s[1])
		}
	}
	for i, r := range p.Rooms {
		if r.ID == "" {
			bad("room #%d has empty id", i)
		} else if _, dup := in.RoomI[r.ID]; dup {
			bad("duplicate room id %q", r.ID)
		}
		in.RoomI[r.ID] = i
		if r.Capacity < 1 {
			bad("room %s: capacity must be >= 1", r.ID)
		}
	}
	for i, g := range p.Groups {
		if g.ID == "" {
			bad("group #%d has empty id", i)
		} else if _, dup := in.GroupI[g.ID]; dup {
			bad("duplicate group id %q", g.ID)
		}
		in.GroupI[g.ID] = i
		if g.Size < 1 {
			bad("group %s: size must be >= 1", g.ID)
		}
	}
	in.LessonEv = make([][]int, len(p.Lessons))
	for li, l := range p.Lessons {
		if l.ID == "" {
			bad("lesson #%d has empty id", li)
		} else if _, dup := in.LessonI[l.ID]; dup {
			bad("duplicate lesson id %q", l.ID)
		}
		in.LessonI[l.ID] = li
		ti, ok := in.TeacherI[l.Teacher]
		if !ok {
			bad("lesson %s: unknown teacher %q", l.ID, l.Teacher)
		}
		var gs []int
		seen := map[int]bool{}
		for _, gid := range l.Groups {
			gi, ok := in.GroupI[gid]
			if !ok {
				bad("lesson %s: unknown group %q", l.ID, gid)
				continue
			}
			if seen[gi] {
				bad("lesson %s: group %q listed twice", l.ID, gid)
				continue
			}
			seen[gi] = true
			gs = append(gs, gi)
		}
		if len(l.Groups) == 0 {
			bad("lesson %s: needs at least one group", l.ID)
		}
		if l.Sessions < 1 {
			bad("lesson %s: sessions must be >= 1", l.ID)
		}
		if l.Sessions > p.Days {
			bad("lesson %s: %d sessions but only %d days (sessions of a lesson must be on different days)", l.ID, l.Sessions, p.Days)
		}
		if l.Duration < 1 || l.Duration > 4 || l.Duration > p.Periods {
			bad("lesson %s: duration must be 1..%d (got %d)", l.ID, min(4, p.Periods), l.Duration)
		}
		if len(l.Fixed) > l.Sessions {
			bad("lesson %s: %d fixed slots for %d sessions", l.ID, len(l.Fixed), l.Sessions)
		}
		for _, s := range l.Fixed {
			if !inSlot(s) {
				bad("lesson %s: fixed slot %v outside the week", l.ID, s)
			}
		}
		_ = ti
	}
	if len(errs) > 0 {
		return nil, &ValidationError{errs}
	}
	// expand
	for li, l := range p.Lessons {
		ti := in.TeacherI[l.Teacher]
		var gs []int
		size := 0
		for _, gid := range l.Groups {
			gi := in.GroupI[gid]
			gs = append(gs, gi)
			size += p.Groups[gi].Size
		}
		var rooms []int
		for ri, r := range p.Rooms {
			if r.Kind == l.RoomKind && r.Capacity >= size {
				rooms = append(rooms, ri)
			}
		}
		for s := 0; s < l.Sessions; s++ {
			ev := Event{ID: len(in.Events), Lesson: li, Session: s, Teacher: ti, Groups: gs, Dur: l.Duration,
				Size: size, Rooms: rooms, bits: (1 << uint(l.Duration)) - 1,
				Name: fmt.Sprintf("%s#%d", l.ID, s+1)}
			if s < len(l.Fixed) {
				f := l.Fixed[s]
				if in.startOK(&ev, f[0]*in.N+f[1]) {
					ev.Starts = []int{f[0]*in.N + f[1]}
				} // else: leave empty -> reported by Diagnose
			} else {
				for d := 0; d < in.D; d++ {
					for pp := 0; pp < in.N; pp++ {
						if in.startOK(&ev, d*in.N+pp) {
							ev.Starts = append(ev.Starts, d*in.N+pp)
						}
					}
				}
			}
			in.LessonEv[li] = append(in.LessonEv[li], ev.ID)
			in.Events = append(in.Events, ev)
		}
	}
	return in, nil
}

// startOK: does a session of e fit the day, breaks and the teacher's availability at slot s?
func (in *Instance) startOK(e *Event, s int) bool {
	d, p := s/in.N, s%in.N
	if p+e.Dur > in.N {
		return false
	}
	for k := p; k < p+e.Dur-1; k++ {
		if in.breakAt&(1<<uint(k)) != 0 {
			return false
		}
	}
	return in.unavail[e.Teacher][d]&(e.bits<<uint(p)) == 0
}

// Placement is one scheduled session.
type Placement struct {
	Lesson   string `json:"lesson"`
	Session  int    `json:"session"`
	Day      int    `json:"day"`
	Period   int    `json:"period"`
	Duration int    `json:"duration"`
	Room     string `json:"room"`
}

// Solution is the portable result.
type Solution struct {
	Problem    string         `json:"problem"`
	Cost       int            `json:"cost"`
	Breakdown  map[string]int `json:"breakdown"`
	Placements []Placement    `json:"placements"`
}

// Assignment is the internal form: parallel to Instance.Events.
type Assignment struct {
	Slot []int // start slot index, -1 = unplaced
	Room []int
}

func newAssignment(n int) *Assignment {
	a := &Assignment{Slot: make([]int, n), Room: make([]int, n)}
	for i := range a.Slot {
		a.Slot[i], a.Room[i] = -1, -1
	}
	return a
}

func (a *Assignment) Clone() *Assignment {
	return &Assignment{Slot: append([]int(nil), a.Slot...), Room: append([]int(nil), a.Room...)}
}

// ToSolution converts an assignment into the portable form.
func (in *Instance) ToSolution(a *Assignment) *Solution {
	s := &Solution{Problem: in.P.Name}
	for i, e := range in.Events {
		if a.Slot[i] < 0 {
			continue
		}
		s.Placements = append(s.Placements, Placement{Lesson: in.P.Lessons[e.Lesson].ID, Session: e.Session + 1,
			Day: a.Slot[i] / in.N, Period: a.Slot[i] % in.N, Duration: e.Dur, Room: in.P.Rooms[a.Room[i]].ID})
	}
	sort.Slice(s.Placements, func(i, j int) bool {
		x, y := s.Placements[i], s.Placements[j]
		if x.Day != y.Day {
			return x.Day < y.Day
		}
		if x.Period != y.Period {
			return x.Period < y.Period
		}
		return x.Lesson < y.Lesson
	})
	c, b := in.Cost(a)
	s.Cost, s.Breakdown = c, b
	return s
}

// FromSolution maps a portable solution back onto the instance's events.
func (in *Instance) FromSolution(s *Solution) (*Assignment, error) {
	a := newAssignment(len(in.Events))
	for _, pl := range s.Placements {
		li, ok := in.LessonI[pl.Lesson]
		if !ok {
			return nil, fmt.Errorf("placement of unknown lesson %q", pl.Lesson)
		}
		if pl.Session < 1 || pl.Session > len(in.LessonEv[li]) {
			return nil, fmt.Errorf("lesson %s has no session %d", pl.Lesson, pl.Session)
		}
		ri, ok := in.RoomI[pl.Room]
		if !ok {
			return nil, fmt.Errorf("placement of %s in unknown room %q", pl.Lesson, pl.Room)
		}
		if pl.Day < 0 || pl.Day >= in.D || pl.Period < 0 || pl.Period >= in.N {
			return nil, fmt.Errorf("placement of %s#%d outside the week", pl.Lesson, pl.Session)
		}
		ei := in.LessonEv[li][pl.Session-1]
		if a.Slot[ei] >= 0 {
			return nil, fmt.Errorf("%s#%d placed twice", pl.Lesson, pl.Session)
		}
		a.Slot[ei], a.Room[ei] = pl.Day*in.N+pl.Period, ri
	}
	return a, nil
}
