package tabula

import (
	"crypto/sha1"
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// PartialFromSolution maps a previous solution onto this (possibly changed)
// instance, silently dropping placements whose lesson/session no longer exist.
// Used as the "stay close to this" reference for re-solving.
func (in *Instance) PartialFromSolution(s *Solution) (*Assignment, error) {
	a := newAssignment(len(in.Events))
	for _, pl := range s.Placements {
		li, ok := in.LessonI[pl.Lesson]
		if !ok || pl.Session < 1 || pl.Session > len(in.LessonEv[li]) {
			continue
		}
		ri, ok := in.RoomI[pl.Room]
		if !ok {
			ri = -1 // room no longer exists: only the time slot is worth preserving
		}
		if pl.Day < 0 || pl.Day >= in.D || pl.Period < 0 || pl.Period >= in.N {
			return nil, fmt.Errorf("placement of %s#%d is outside the %dx%d week", pl.Lesson, pl.Session, in.D, in.N)
		}
		ei := in.LessonEv[li][pl.Session-1]
		a.Slot[ei], a.Room[ei] = pl.Day*in.N+pl.Period, ri
	}
	return a, nil
}

// CountMoved counts events whose slot or room differs from prev (ignoring events prev lacks).
func (in *Instance) CountMoved(prev, a *Assignment) int {
	n := 0
	for e := range in.Events {
		if prev.Slot[e] >= 0 && (prev.Slot[e] != a.Slot[e] || (prev.Room[e] >= 0 && prev.Room[e] != a.Room[e])) {
			n++
		}
	}
	return n
}

// ---------- text grid ----------

// TextGrid renders every group's week as a plain-text table.
func TextGrid(p *Problem, s *Solution) string {
	lessons := map[string]Lesson{}
	for _, l := range p.Lessons {
		lessons[l.ID] = l
	}
	var sb strings.Builder
	for _, g := range p.Groups {
		cells := map[[2]int]string{}
		for _, pl := range s.Placements {
			l := lessons[pl.Lesson]
			for _, gid := range l.Groups {
				if gid == g.ID {
					for k := 0; k < pl.Duration; k++ {
						txt := fmt.Sprintf("%s/%s/%s", l.Subject, l.Teacher, pl.Room)
						if k > 0 {
							txt = "  \" \""
						}
						cells[[2]int{pl.Day, pl.Period + k}] = txt
					}
				}
			}
		}
		fmt.Fprintf(&sb, "== group %s (%d students) ==\n", g.ID, g.Size)
		fmt.Fprintf(&sb, "%-3s", "")
		for d := 0; d < p.Days; d++ {
			fmt.Fprintf(&sb, "| %-22s", p.DayName(d))
		}
		sb.WriteString("\n")
		for per := 0; per < p.Periods; per++ {
			fmt.Fprintf(&sb, "%-3d", per+1)
			for d := 0; d < p.Days; d++ {
				fmt.Fprintf(&sb, "| %-22s", trunc(cells[[2]int{d, per}], 22))
			}
			sb.WriteString("\n")
		}
		sb.WriteString("\n")
	}
	return sb.String()
}

func trunc(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n-1]) + "…"
	}
	return s
}

// ---------- HTML viewer ----------

//go:embed viewer.html
var viewerHTML string

// WriteHTML writes a single self-contained interactive timetable viewer.
func WriteHTML(path string, p *Problem, s *Solution) error {
	payload := struct {
		Problem  *Problem  `json:"problem"`
		Solution *Solution `json:"solution"`
	}{p, s}
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	// "<" escaped as \u003c so "</script>" or "<!--" inside data cannot break out of the script tag.
	js := strings.ReplaceAll(string(b), "<", "\\u003c")
	out := strings.Replace(viewerHTML, "/*DATA*/null", js, 1)
	return os.WriteFile(path, []byte(out), 0o644)
}

// ---------- iCalendar ----------

func icsEscape(s string) string {
	r := strings.NewReplacer("\\", "\\\\", ";", "\\;", ",", "\\,", "\n", "\\n")
	return r.Replace(s)
}

func hhmm(s string) (int, int, bool) {
	var h, m int
	if _, err := fmt.Sscanf(s, "%d:%d", &h, &m); err != nil || h < 0 || h > 23 || m < 0 || m > 59 {
		return 0, 0, false
	}
	return h, m, true
}

// periodTimes returns start minute-of-day for each period.
func periodTimes(p *Problem) []int {
	out := make([]int, p.Periods)
	for i := range out {
		out[i] = 8*60 + 30 + i*55
		if i < len(p.PeriodStarts) && len(p.PeriodStarts) == p.Periods {
			if h, m, ok := hhmm(p.PeriodStarts[i]); ok {
				out[i] = h*60 + m
			}
		}
	}
	return out
}

// WriteICS writes one weekly-recurring calendar per group and per teacher into dir.
// start is the Monday (YYYY-MM-DD) of the first week; "" means the next Monday.
func WriteICS(dir string, p *Problem, s *Solution, start string) (int, error) {
	var day0 time.Time
	if start == "" {
		now := time.Now()
		day0 = time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
		for day0.Weekday() != time.Monday || !day0.After(now) {
			day0 = day0.AddDate(0, 0, 1)
		}
	} else {
		t, err := time.Parse("2006-01-02", start)
		if err != nil {
			return 0, fmt.Errorf("bad start date %q (want YYYY-MM-DD)", start)
		}
		if t.Weekday() != time.Monday {
			return 0, fmt.Errorf("start date %s is a %s, not a Monday", start, t.Weekday())
		}
		day0 = t
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return 0, err
	}
	pt := periodTimes(p)
	mins := p.PeriodMins
	if mins <= 0 {
		mins = 50
	}
	lessons := map[string]Lesson{}
	for _, l := range p.Lessons {
		lessons[l.ID] = l
	}
	build := func(match func(Lesson) bool, cal string) string {
		var sb strings.Builder
		w := func(l string) { // RFC 5545: fold lines at 75 octets
			for len(l) > 75 {
				cut := 75
				for cut > 0 && l[cut]&0xC0 == 0x80 { // do not split a UTF-8 sequence
					cut--
				}
				sb.WriteString(l[:cut] + "\r\n ")
				l = l[cut:]
			}
			sb.WriteString(l + "\r\n")
		}
		w("BEGIN:VCALENDAR")
		w("VERSION:2.0")
		w("PRODID:-//Tabula//Timetable//EN")
		w("CALSCALE:GREGORIAN")
		w("X-WR-CALNAME:" + icsEscape(cal))
		for _, pl := range s.Placements {
			l := lessons[pl.Lesson]
			if !match(l) {
				continue
			}
			st := day0.AddDate(0, 0, pl.Day).Add(time.Duration(pt[pl.Period]) * time.Minute)
			en := day0.AddDate(0, 0, pl.Day).Add(time.Duration(pt[pl.Period+pl.Duration-1]+mins) * time.Minute)
			uid := fmt.Sprintf("%x@tabula", sha1.Sum([]byte(fmt.Sprintf("%s|%s|%d", p.Name, pl.Lesson, pl.Session))))
			w("BEGIN:VEVENT")
			w("UID:" + uid)
			w("DTSTAMP:20260101T000000Z")
			w("DTSTART:" + st.Format("20060102T150405"))
			w("DTEND:" + en.Format("20060102T150405"))
			w("RRULE:FREQ=WEEKLY")
			w("SUMMARY:" + icsEscape(l.Subject+" ("+strings.Join(l.Groups, "+")+")"))
			w("LOCATION:" + icsEscape(pl.Room))
			w("DESCRIPTION:" + icsEscape("Teacher: "+l.Teacher))
			w("END:VEVENT")
		}
		w("END:VCALENDAR")
		return sb.String()
	}
	n := 0
	write := func(name, body string) error {
		n++
		return os.WriteFile(filepath.Join(dir, safeName(name)+".ics"), []byte(body), 0o644)
	}
	for _, g := range p.Groups {
		g := g
		if err := write("group-"+g.ID, build(func(l Lesson) bool {
			for _, x := range l.Groups {
				if x == g.ID {
					return true
				}
			}
			return false
		}, "Group "+g.ID)); err != nil {
			return n, err
		}
	}
	ids := make([]string, 0)
	for _, t := range p.Teachers {
		ids = append(ids, t.ID)
	}
	sort.Strings(ids)
	for _, id := range ids {
		id := id
		if err := write("teacher-"+id, build(func(l Lesson) bool { return l.Teacher == id }, "Teacher "+id)); err != nil {
			return n, err
		}
	}
	return n, nil
}

func safeName(s string) string {
	var sb strings.Builder
	for _, r := range s {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' {
			sb.WriteRune(r)
		} else {
			sb.WriteRune('_')
		}
	}
	return sb.String()
}
