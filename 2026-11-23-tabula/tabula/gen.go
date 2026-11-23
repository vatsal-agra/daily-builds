package tabula

import (
	"fmt"
	"math/rand"
)

// GenConfig sizes a generated instance.
type GenConfig struct {
	Seed     int64
	Groups   int
	Teachers int
	Rooms    int
	Days     int
	Periods  int
	Load     float64 // fraction of each group's week to fill (0.3..0.9)
}

var subjects = []string{"Maths", "English", "Physics", "Chemistry", "Biology", "History", "Geography", "Art", "Music", "PE", "CompSci", "French", "Drama", "Economics"}

// Generate builds a random problem that is guaranteed feasible: it first plants
// a timetable, derives the lessons from it, then only adds constraints (teacher
// unavailability) that the planted timetable already respects.
func Generate(c GenConfig) *Problem {
	rng := rand.New(rand.NewSource(c.Seed))
	if c.Days == 0 {
		c.Days = 5
	}
	if c.Periods == 0 {
		c.Periods = 8
	}
	if c.Load == 0 {
		c.Load = 0.6
	}
	p := &Problem{Name: fmt.Sprintf("generated-%d", c.Seed), Days: c.Days, Periods: c.Periods, BreaksAfter: []int{c.Periods/2 - 1}}
	p.PeriodMins = 50
	for i := 0; i < c.Periods; i++ {
		m := 8*60 + 30 + i*55
		if i >= c.Periods/2 {
			m += 30
		}
		p.PeriodStarts = append(p.PeriodStarts, fmt.Sprintf("%02d:%02d", m/60, m%60))
	}
	for i := 0; i < c.Groups; i++ {
		p.Groups = append(p.Groups, Group{ID: fmt.Sprintf("G%d", i+1), Size: 18 + rng.Intn(14)})
	}
	for i := 0; i < c.Rooms; i++ {
		r := Room{ID: fmt.Sprintf("R%d", i+1), Capacity: 30 + rng.Intn(10)}
		if i%5 == 4 {
			r.Kind, r.Capacity = "lab", 32
			r.ID = fmt.Sprintf("LAB%d", i/5+1)
		}
		if i == c.Rooms-1 && c.Rooms > 3 {
			r.Kind, r.Capacity, r.ID = "gym", 70, "GYM"
		}
		p.Rooms = append(p.Rooms, r)
	}
	for i := 0; i < c.Teachers; i++ {
		p.Teachers = append(p.Teachers, Teacher{ID: fmt.Sprintf("T%d", i+1), Name: fmt.Sprintf("Teacher %d", i+1)})
	}
	// planting grids
	type cellk struct{ k, id, d, p int } // k:0 teacher 1 group 2 room
	used := map[cellk]bool{}
	teacherMax := make([]map[int]int, c.Teachers)
	for i := range teacherMax {
		teacherMax[i] = map[int]int{}
	}
	free := func(k, id, d, per, dur int) bool {
		for x := 0; x < dur; x++ {
			if used[cellk{k, id, d, per + x}] {
				return false
			}
		}
		return true
	}
	mark := func(k, id, d, per, dur int) {
		for x := 0; x < dur; x++ {
			used[cellk{k, id, d, per + x}] = true
		}
	}
	spanOK := func(per, dur int) bool {
		if per+dur > c.Periods {
			return false
		}
		for k := per; k < per+dur-1; k++ {
			if k == c.Periods/2-1 {
				return false
			}
		}
		return true
	}
	// a teacher specialises in 1-2 subjects
	spec := make([][]string, c.Teachers)
	for i := range spec {
		spec[i] = []string{subjects[rng.Intn(len(subjects))], subjects[rng.Intn(len(subjects))]}
	}
	lid := 0
	for gi := range p.Groups {
		target := int(float64(c.Days*c.Periods) * c.Load)
		got := 0
		for tries := 0; got < target && tries < 400; tries++ {
			subj := subjects[rng.Intn(len(subjects))]
			kind := ""
			switch subj {
			case "Physics", "Chemistry", "Biology":
				kind = "lab"
			case "PE":
				kind = "gym"
			}
			if kind != "" && !hasKind(p.Rooms, kind) {
				kind = ""
			}
			var ts []int
			for ti := range spec {
				for _, s := range spec[ti] {
					if s == subj {
						ts = append(ts, ti)
					}
				}
			}
			ti := rng.Intn(c.Teachers)
			if len(ts) > 0 {
				ti = ts[rng.Intn(len(ts))]
			}
			dur := 1
			if rng.Intn(4) == 0 {
				dur = 2
			}
			want := 1 + rng.Intn(3)
			if want > c.Days {
				want = c.Days
			}
			// plant sessions on distinct days
			type pl struct{ d, per, r int }
			var plants []pl
			days := rng.Perm(c.Days)
			for _, d := range days {
				if len(plants) == want {
					break
				}
				for att := 0; att < 12; att++ {
					per := rng.Intn(c.Periods)
					if !spanOK(per, dur) || !free(0, ti, d, per, dur) || !free(1, gi, d, per, dur) {
						continue
					}
					if teacherMax[ti][d]+dur > c.Periods-1 {
						continue
					}
					r := -1
					for _, ri := range rng.Perm(len(p.Rooms)) {
						rm := p.Rooms[ri]
						if rm.Kind == kind && rm.Capacity >= p.Groups[gi].Size && free(2, ri, d, per, dur) {
							r = ri
							break
						}
					}
					if r < 0 {
						continue
					}
					plants = append(plants, pl{d, per, r})
					mark(0, ti, d, per, dur)
					mark(1, gi, d, per, dur)
					mark(2, r, d, per, dur)
					teacherMax[ti][d] += dur
					break
				}
			}
			if len(plants) == 0 {
				continue
			}
			lid++
			p.Lessons = append(p.Lessons, Lesson{ID: fmt.Sprintf("L%d", lid), Subject: subj, Teacher: p.Teachers[ti].ID,
				Groups: []string{p.Groups[gi].ID}, Sessions: len(plants), Duration: dur, RoomKind: kind})
			got += len(plants) * dur
		}
	}
	// derive constraints the planted timetable satisfies
	for ti := range p.Teachers {
		maxDay := 0
		for _, n := range teacherMax[ti] {
			if n > maxDay {
				maxDay = n
			}
		}
		if maxDay > 0 {
			p.Teachers[ti].MaxPerDay = maxDay + rng.Intn(2)
		}
		for d := 0; d < c.Days; d++ {
			for per := 0; per < c.Periods; per++ {
				if used[cellk{0, ti, d, per}] {
					continue
				}
				switch r := rng.Intn(10); {
				case r == 0:
					p.Teachers[ti].Unavailable = append(p.Teachers[ti].Unavailable, Slot{d, per})
				case r == 1:
					p.Teachers[ti].Avoid = append(p.Teachers[ti].Avoid, Slot{d, per})
				}
			}
		}
	}
	return p
}

func hasKind(rs []Room, k string) bool {
	for _, r := range rs {
		if r.Kind == k {
			return true
		}
	}
	return false
}
