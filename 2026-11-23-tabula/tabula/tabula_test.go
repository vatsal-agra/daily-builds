package tabula

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func mustCompile(t *testing.T, p *Problem) *Instance {
	t.Helper()
	in, err := Compile(p)
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	return in
}

func loadEx(t *testing.T, name string) *Problem {
	t.Helper()
	p, err := LoadProblem(filepath.Join("..", "examples", name))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// tiny builds: 1 day x 4 periods, one teacher per lesson.
func tiny() *Problem {
	return &Problem{Name: "tiny", Days: 1, Periods: 4,
		Teachers: []Teacher{{ID: "a"}, {ID: "b"}},
		Rooms:    []Room{{ID: "r1", Capacity: 30}, {ID: "r2", Capacity: 30}},
		Groups:   []Group{{ID: "g", Size: 20}},
		Lessons: []Lesson{
			{ID: "x", Subject: "X", Teacher: "a", Groups: []string{"g"}, Sessions: 1, Duration: 1},
			{ID: "y", Subject: "Y", Teacher: "b", Groups: []string{"g"}, Sessions: 1, Duration: 1},
		},
		Weights: &Weights{GroupGap: 10, TeacherGap: 4, LongDay: 5, MaxDaily: 6, TeacherDay: 3, Spread: 2, Avoid: 3, Stability: 8}}
}

func place(t *testing.T, in *Instance, spec map[string][2]interface{}) *Assignment {
	t.Helper()
	s := &Solution{}
	for l, v := range spec {
		s.Placements = append(s.Placements, Placement{Lesson: l, Session: 1, Day: 0, Period: v[0].(int), Room: v[1].(string)})
	}
	a, err := in.FromSolution(s)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

// ---- feature 1: model + validation ----

func TestValidationMessages(t *testing.T) {
	cases := []struct {
		name string
		mut  func(p *Problem)
		want string
	}{
		{"days", func(p *Problem) { p.Days = 0 }, "days must be"},
		{"dup teacher", func(p *Problem) { p.Teachers = append(p.Teachers, Teacher{ID: "a"}) }, "duplicate teacher"},
		{"dup room", func(p *Problem) { p.Rooms = append(p.Rooms, Room{ID: "r1", Capacity: 3}) }, "duplicate room"},
		{"bad cap", func(p *Problem) { p.Rooms[0].Capacity = 0 }, "capacity"},
		{"unknown teacher", func(p *Problem) { p.Lessons[0].Teacher = "zed" }, "unknown teacher"},
		{"unknown group", func(p *Problem) { p.Lessons[0].Groups = []string{"nope"} }, "unknown group"},
		{"no groups", func(p *Problem) { p.Lessons[0].Groups = nil }, "at least one group"},
		{"too many sessions", func(p *Problem) { p.Lessons[0].Sessions = 2 }, "different days"},
		{"duration", func(p *Problem) { p.Lessons[0].Duration = 9 }, "duration"},
		{"slot range", func(p *Problem) { p.Teachers[0].Unavailable = []Slot{{3, 0}} }, "outside"},
		{"break range", func(p *Problem) { p.BreaksAfter = []int{3} }, "breaks_after"},
		{"fixed range", func(p *Problem) { p.Lessons[0].Fixed = []Slot{{0, 9}} }, "fixed slot"},
		{"period_starts", func(p *Problem) { p.PeriodStarts = []string{"08:00"} }, "period_starts"},
	}
	for _, c := range cases {
		p := tiny()
		c.mut(p)
		_, err := Compile(p)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: want error containing %q, got %v", c.name, c.want, err)
		}
	}
	if _, err := Compile(tiny()); err != nil {
		t.Errorf("valid problem rejected: %v", err)
	}
}

func TestValidationReportsAllIssues(t *testing.T) {
	p := tiny()
	p.Lessons[0].Teacher = "zed"
	p.Lessons[1].Groups = []string{"nope"}
	_, err := Compile(p)
	ve, ok := err.(*ValidationError)
	if !ok || len(ve.Problems) != 2 {
		t.Fatalf("want 2 problems, got %v", err)
	}
}

func TestSlotJSONStrict(t *testing.T) {
	var s Slot
	for _, bad := range []string{"[1]", "[1,2,3]", `["a",1]`, "5", "[]"} {
		if err := json.Unmarshal([]byte(bad), &s); err == nil {
			t.Errorf("slot %s accepted", bad)
		}
	}
	if err := json.Unmarshal([]byte("[2,3]"), &s); err != nil || s != (Slot{2, 3}) {
		t.Errorf("good slot rejected: %v %v", s, err)
	}
}

func TestLoadRejectsUnknownFields(t *testing.T) {
	f := filepath.Join(t.TempDir(), "p.json")
	os.WriteFile(f, []byte(`{"name":"x","days":1,"periods":1,"bogus":1}`), 0o644)
	if _, err := LoadProblem(f); err == nil || !strings.Contains(err.Error(), "bogus") {
		t.Fatalf("unknown field accepted: %v", err)
	}
}

func TestEventExpansionRespectsBreaksAndAvailability(t *testing.T) {
	p := tiny()
	p.BreaksAfter = []int{1}
	p.Lessons[0].Duration = 2
	p.Teachers[0].Unavailable = []Slot{{0, 3}}
	in := mustCompile(t, p)
	e := in.Events[in.LessonEv[0][0]]
	// double period can't start at 1 (spans break), 3 (runs off end / unavailable) -> only 0 and 2? 2..3 hits unavailable 3
	if len(e.Starts) != 1 || e.Starts[0] != 0 {
		t.Fatalf("starts = %v, want [0]", e.Starts)
	}
}

// ---- feature 4: diagnostics ----

func TestDiagnoseImpossibleExample(t *testing.T) {
	in := mustCompile(t, loadEx(t, "impossible.json"))
	ds := in.Diagnose()
	joined := ""
	for _, d := range ds {
		if !d.Fatal {
			t.Errorf("unexpected non-fatal %v", d)
		}
		joined += d.Msg + "\n"
	}
	for _, want := range []string{"chem needs a \"lab\" room seating 25", "assembly needs an ordinary classroom seating 90",
		"hist has 4 sessions but only 2 usable day", "fixed lessons pa#1 and pb#1 both claim teacher fox"} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing diagnostic %q in:\n%s", want, joined)
		}
	}
	if _, _, err := in.Solve(Options{}); err == nil || !strings.Contains(err.Error(), "no timetable can exist") {
		t.Errorf("Solve should refuse impossible problem, got %v", err)
	}
	// no duplicates
	seen := map[string]bool{}
	for _, d := range ds {
		if seen[d.Msg] {
			t.Errorf("duplicate diagnostic %q", d.Msg)
		}
		seen[d.Msg] = true
	}
}

func TestDiagnoseCountingProofs(t *testing.T) {
	// teacher overload
	p := tiny()
	p.Days = 1
	p.Periods = 2
	p.Lessons = []Lesson{{ID: "x", Subject: "X", Teacher: "a", Groups: []string{"g"}, Sessions: 1, Duration: 2},
		{ID: "z", Subject: "Z", Teacher: "a", Groups: []string{"g"}, Sessions: 1, Duration: 1}}
	ds := mustCompile(t, p).Diagnose()
	if !HasFatal(ds) || !strings.Contains(ds[0].Msg, "teacher a must teach 3 periods") {
		t.Errorf("teacher overload not diagnosed: %v", ds)
	}
	// max_per_day
	p = tiny()
	p.Teachers[0].MaxPerDay = 1
	p.Lessons[1].Teacher = "a"
	ds = mustCompile(t, p).Diagnose()
	if !HasFatal(ds) || !strings.Contains(ds[0].Msg, "max_per_day") {
		t.Errorf("max_per_day overload not diagnosed: %v", ds)
	}
	// room pigeonhole: 2 events of 3 periods only fit in 1 room x 4 slots
	p = tiny()
	p.Rooms = p.Rooms[:1]
	p.Lessons[0].Duration, p.Lessons[1].Duration = 3, 3
	p.Groups = append(p.Groups, Group{ID: "h", Size: 5})
	p.Lessons[1].Groups = []string{"h"}
	ds = mustCompile(t, p).Diagnose()
	found := false
	for _, d := range ds {
		found = found || strings.Contains(d.Msg, "room shortage")
	}
	if !found {
		t.Errorf("room pigeonhole not diagnosed: %v", ds)
	}
	// group overload
	p = tiny()
	p.Periods = 2
	ds = mustCompile(t, p).Diagnose()
	p.Lessons = append(p.Lessons, Lesson{ID: "w", Subject: "W", Teacher: "b", Groups: []string{"g"}, Sessions: 1, Duration: 1})
	ds = mustCompile(t, p).Diagnose()
	if !HasFatal(ds) {
		t.Errorf("group overload not diagnosed: %v", ds)
	}
}

func TestSchoolExampleNotFatal(t *testing.T) {
	if ds := mustCompile(t, loadEx(t, "school.json")).Diagnose(); HasFatal(ds) {
		t.Fatalf("school example flagged impossible: %v", ds)
	}
}

// ---- feature 2: constructor ----

func TestConstructProducesFeasibleTimetables(t *testing.T) {
	for seed := int64(1); seed <= 8; seed++ {
		p := Generate(GenConfig{Seed: seed, Groups: 6, Teachers: 8, Rooms: 6, Load: 0.7})
		in := mustCompile(t, p)
		r := in.Construct(seed, 10*time.Second, nil)
		if r.A == nil {
			t.Fatalf("seed %d: no timetable", seed)
		}
		if _, ok := in.LoadAssignment(r.A); !ok {
			t.Fatalf("seed %d: LoadAssignment says infeasible", seed)
		}
		if v, _, _ := Verify(p, in.ToSolution(r.A), nil); len(v) != 0 {
			t.Fatalf("seed %d: verifier violations: %v", seed, v)
		}
	}
}

func TestConstructHonoursFixedSlots(t *testing.T) {
	p := loadEx(t, "school.json")
	in := mustCompile(t, p)
	a, _, err := in.Solve(Options{Seed: 3})
	if err != nil {
		t.Fatal(err)
	}
	sol := in.ToSolution(a)
	got := map[string]Placement{}
	for _, pl := range sol.Placements {
		got[pl.Lesson] = pl
	}
	if pl := got["assembly"]; pl.Day != 0 || pl.Period != 0 {
		t.Errorf("assembly pinned to Mon p1, placed at %d/%d", pl.Day, pl.Period)
	}
	if pl := got["pe6"]; pl.Session == 1 && (pl.Day != 1 || pl.Period != 0) {
		t.Errorf("pe6#1 pinned to Tue p1, placed at %d/%d", pl.Day, pl.Period)
	}
}

func TestRepairSolvesTightInstance(t *testing.T) {
	p := Generate(GenConfig{Seed: 9, Groups: 10, Teachers: 10, Rooms: 6, Load: 0.9})
	in := mustCompile(t, p)
	a, rep, err := in.Solve(Options{Seed: 1, ConstructFor: 30 * time.Second})
	if err != nil {
		t.Fatalf("tight feasible instance not solved: %v", err)
	}
	if !rep.Construct.UsedRepair {
		t.Log("note: backtracking alone solved it")
	}
	if v, _, _ := Verify(p, in.ToSolution(a), nil); len(v) != 0 {
		t.Fatalf("violations: %v", v)
	}
}

func TestRepairDirect(t *testing.T) {
	p := Generate(GenConfig{Seed: 4, Groups: 8, Teachers: 9, Rooms: 6, Load: 0.8})
	in := mustCompile(t, p)
	a, left, _ := in.Repair(1, 20*time.Second, nil)
	if a == nil {
		t.Fatalf("repair left %d violations", left)
	}
	if _, ok := in.LoadAssignment(a); !ok {
		t.Fatal("repair returned an infeasible assignment")
	}
}

func TestRepairReportsConflictsWhenInfeasible(t *testing.T) {
	// Two sessions pinned... avoid diagnostics: 2 groups, 1 teacher, 1 room, 2 periods, 1 day,
	// each group needs 2 periods of the same teacher -> teacher overload is NOT caught if
	// availability counts only; build a case diagnostics miss: both lessons use one room and 1 period/day.
	p := &Problem{Name: "squeeze", Days: 1, Periods: 2,
		Teachers: []Teacher{{ID: "a"}, {ID: "b"}, {ID: "c"}},
		Rooms:    []Room{{ID: "r", Capacity: 9}},
		Groups:   []Group{{ID: "g1", Size: 1}, {ID: "g2", Size: 1}},
		Lessons: []Lesson{
			{ID: "l1", Subject: "s", Teacher: "a", Groups: []string{"g1"}, Sessions: 1, Duration: 1},
			{ID: "l2", Subject: "s", Teacher: "b", Groups: []string{"g1"}, Sessions: 1, Duration: 1},
			{ID: "l3", Subject: "s", Teacher: "c", Groups: []string{"g2"}, Sessions: 1, Duration: 1},
		}}
	in := mustCompile(t, p)
	// 3 sessions, 1 room x 2 periods: pigeonhole says impossible
	if !HasFatal(in.Diagnose()) {
		t.Fatal("expected room shortage proof")
	}
	_, _, err := in.Solve(Options{ConstructFor: time.Second})
	if err == nil {
		t.Fatal("impossible instance solved?!")
	}
}

// ---- feature 3: annealer + cost ----

func TestCostDefinitionsByHand(t *testing.T) {
	p := tiny()
	in := mustCompile(t, p)
	// x at p0, y at p3: group gap = 2 empty periods -> 20; each teacher teaches 1 period/day -> 3 each = 6
	a := place(t, in, map[string][2]interface{}{"x": {0, "r1"}, "y": {3, "r1"}})
	c, bd := in.Cost(a)
	if bd["group_gaps"] != 20 || bd["teacher_days"] != 6 || c != 26 {
		t.Fatalf("cost = %d %v, want 26 (gaps 20 + days 6)", c, bd)
	}
	a = place(t, in, map[string][2]interface{}{"x": {0, "r1"}, "y": {1, "r2"}})
	if c, _ := in.Cost(a); c != 6 {
		t.Fatalf("adjacent lessons should cost only teacher days (6), got %d", c)
	}
}

func TestCostTermsIndividually(t *testing.T) {
	p := tiny()
	p.Weights = &Weights{Late: 1, LateFrom: 2, Avoid: 7, RoomWaste: 10, LongDay: 3, MaxDaily: 1}
	p.Teachers[0].Avoid = []Slot{{0, 0}}
	p.Rooms[0].Capacity = 30 // size 20 -> 10 surplus -> waste 10*10/10 = 10
	in := mustCompile(t, p)
	a := place(t, in, map[string][2]interface{}{"x": {0, "r1"}, "y": {2, "r2"}})
	_, bd := in.Cost(a)
	want := map[string]int{"late_periods": 1, "avoided_slots": 7, "room_waste": 20, "long_days": 3}
	for k, v := range want {
		if bd[k] != v {
			t.Errorf("%s = %d, want %d (all: %v)", k, bd[k], v, bd)
		}
	}
	// spread: same lesson on adjacent days
	p = &Problem{Name: "sp", Days: 3, Periods: 2, Teachers: []Teacher{{ID: "a"}}, Rooms: []Room{{ID: "r", Capacity: 5}},
		Groups:  []Group{{ID: "g", Size: 5}},
		Lessons: []Lesson{{ID: "x", Subject: "X", Teacher: "a", Groups: []string{"g"}, Sessions: 2, Duration: 1}},
		Weights: &Weights{Spread: 9}}
	in = mustCompile(t, p)
	s := &Solution{Placements: []Placement{{Lesson: "x", Session: 1, Day: 0, Room: "r"}, {Lesson: "x", Session: 2, Day: 1, Room: "r"}}}
	a, _ = in.FromSolution(s)
	if c, _ := in.Cost(a); c != 9 {
		t.Errorf("adjacent-day spread cost = %d, want 9", c)
	}
	s.Placements[1].Day = 2
	a, _ = in.FromSolution(s)
	if c, _ := in.Cost(a); c != 0 {
		t.Errorf("separated sessions cost = %d, want 0", c)
	}
}

func TestAnnealImprovesStaysFeasibleAndMatchesVerifier(t *testing.T) {
	for _, seed := range []int64{1, 2, 3} {
		p := Generate(GenConfig{Seed: seed, Groups: 6, Teachers: 8, Rooms: 6, Load: 0.6})
		in := mustCompile(t, p)
		a, rep, err := in.Solve(Options{Seed: seed, AnnealIters: 400000})
		if err != nil {
			t.Fatal(err)
		}
		sol := in.ToSolution(a)
		if sol.Cost >= rep.Initial {
			t.Errorf("seed %d: annealing did not improve (%d -> %d)", seed, rep.Initial, sol.Cost)
		}
		v, c, bd := Verify(p, sol, nil)
		if len(v) != 0 {
			t.Fatalf("seed %d: annealed timetable violates hard constraints: %v", seed, v)
		}
		if c != sol.Cost {
			t.Errorf("seed %d: incremental cost %d != independent cost %d", seed, sol.Cost, c)
		}
		for k, x := range bd {
			if sol.Breakdown[k] != x {
				t.Errorf("seed %d: breakdown %s: %d vs %d", seed, k, sol.Breakdown[k], x)
			}
		}
	}
}

func TestIncrementalDeltaEqualsFullRecompute(t *testing.T) {
	p := Generate(GenConfig{Seed: 11, Groups: 5, Teachers: 6, Rooms: 5, Load: 0.6})
	in := mustCompile(t, p)
	r := in.Construct(1, 10*time.Second, nil)
	st, _ := in.LoadAssignment(r.A)
	sc := in.newScratch()
	cur, _ := in.Cost(st.A)
	moves := 0
	for e := range in.Events {
		ev := &in.Events[e]
		for _, s := range ev.Starts {
			rm := ev.Rooms[0]
			os, orm := st.A.Slot[e], st.A.Room[e]
			if s == os && rm == orm {
				continue
			}
			before := st.localCost(sc, e)
			st.Unplace(e)
			if !st.CanPlace(e, s, rm) {
				st.Place(e, os, orm)
				continue
			}
			st.Place(e, s, rm)
			cur += st.localCost(sc, e) - before
			moves++
			if full, _ := in.Cost(st.A); full != cur {
				t.Fatalf("after %d moves incremental=%d full=%d", moves, cur, full)
			}
		}
	}
	if moves < 50 {
		t.Fatalf("only %d moves exercised", moves)
	}
}

func TestAnnealDeterministicWithIters(t *testing.T) {
	p := Generate(GenConfig{Seed: 2, Groups: 5, Teachers: 6, Rooms: 5, Load: 0.6})
	var sols [2]string
	for i := range sols {
		in := mustCompile(t, p)
		a, _, err := in.Solve(Options{Seed: 7, AnnealIters: 100000})
		if err != nil {
			t.Fatal(err)
		}
		b, _ := json.Marshal(in.ToSolution(a))
		sols[i] = string(b)
	}
	if sols[0] != sols[1] {
		t.Fatal("same seed + iteration budget produced different timetables")
	}
}

func TestStatePlaceUnplaceRoundTrip(t *testing.T) {
	p := Generate(GenConfig{Seed: 6, Groups: 4, Teachers: 5, Rooms: 4, Load: 0.6})
	in := mustCompile(t, p)
	r := in.Construct(1, 10*time.Second, nil)
	st, ok := in.LoadAssignment(r.A)
	if !ok {
		t.Fatal("load")
	}
	for e := range in.Events {
		s, rm := st.A.Slot[e], st.A.Room[e]
		st.Unplace(e)
		if !st.CanPlace(e, s, rm) {
			t.Fatalf("event %d cannot return to its own slot after Unplace", e)
		}
		st.Place(e, s, rm)
	}
	if st.placed != len(in.Events) {
		t.Fatalf("placed=%d", st.placed)
	}
}

// ---- feature 6: verifier catches every kind of violation ----

func solvedSchool(t *testing.T) (*Problem, *Solution) {
	t.Helper()
	p := loadEx(t, "school.json")
	in := mustCompile(t, p)
	a, _, err := in.Solve(Options{Seed: 1, AnnealIters: 20000})
	if err != nil {
		t.Fatal(err)
	}
	return p, in.ToSolution(a)
}

func clone(s *Solution) *Solution {
	b, _ := json.Marshal(s)
	var c Solution
	json.Unmarshal(b, &c)
	return &c
}

func TestVerifyAcceptsGoodAndCatchesBad(t *testing.T) {
	p, good := solvedSchool(t)
	if v, _, _ := Verify(p, good, nil); len(v) != 0 {
		t.Fatalf("good solution rejected: %v", v)
	}
	find := func(s *Solution, lesson string) *Placement {
		for i := range s.Placements {
			if s.Placements[i].Lesson == lesson {
				return &s.Placements[i]
			}
		}
		t.Fatalf("no %s", lesson)
		return nil
	}
	cases := []struct {
		name string
		mut  func(s *Solution)
		want string
	}{
		{"missing", func(s *Solution) { s.Placements = s.Placements[1:] }, "not scheduled"},
		{"duplicate", func(s *Solution) { s.Placements = append(s.Placements, s.Placements[0]) }, "more than once"},
		{"teacher clash", func(s *Solution) {
			a, b := find(s, "maths4"), find(s, "maths5")
			b.Day, b.Period = a.Day, a.Period
		}, "double-booked"},
		{"room kind", func(s *Solution) { find(s, "sci6").Room = "A1" }, "kind"},
		{"capacity", func(s *Solution) { find(s, "eng4").Room = "A3" }, "seats 24"},
		{"unknown room", func(s *Solution) { find(s, "eng4").Room = "zz" }, "unknown room"},
		{"unavailable", func(s *Solution) { pl := find(s, "pe4"); pl.Day, pl.Period = 0, 3 }, "unavailable"},
		{"pinned", func(s *Solution) { pl := find(s, "assembly"); pl.Period = 5 }, "pinned"},
		{"off the day", func(s *Solution) { find(s, "sci6").Period = 5 }, "does not fit"},
		{"spans break", func(s *Solution) { pl := find(s, "sci6"); pl.Period = 2 }, "spans a break"},
		{"two on a day", func(s *Solution) {
			pls := []*Placement{}
			for i := range s.Placements {
				if s.Placements[i].Lesson == "maths4" {
					pls = append(pls, &s.Placements[i])
				}
			}
			pls[1].Day = pls[0].Day
		}, "two sessions"},
		{"unknown lesson", func(s *Solution) { s.Placements[0].Lesson = "ghost" }, "unknown lesson"},
		{"wrong duration", func(s *Solution) { find(s, "art").Duration = 1 }, "duration"},
	}
	for _, c := range cases {
		s := clone(good)
		c.mut(s)
		v, _, _ := Verify(p, s, nil)
		if len(v) == 0 {
			t.Errorf("%s: verifier found nothing", c.name)
			continue
		}
		hit := false
		for _, x := range v {
			hit = hit || strings.Contains(x, c.want)
		}
		if !hit {
			t.Errorf("%s: want violation containing %q, got %v", c.name, c.want, v)
		}
	}
}

func TestMaxPerDayHardConstraint(t *testing.T) {
	p, good := solvedSchool(t)
	// ames has max_per_day 5; stack 6 of her sessions on one day by hand -> must be flagged
	s := clone(good)
	n := 0
	for i := range s.Placements {
		l := p.Lessons[0]
		_ = l
		if s.Placements[i].Lesson == "assembly" || strings.HasPrefix(s.Placements[i].Lesson, "maths4") || strings.HasPrefix(s.Placements[i].Lesson, "maths5") {
			s.Placements[i].Day = 3
			s.Placements[i].Period = n % 6
			n++
		}
	}
	v, _, _ := Verify(p, s, nil)
	found := false
	for _, x := range v {
		found = found || strings.Contains(x, "max_per_day")
	}
	if !found {
		t.Errorf("max_per_day violation not flagged: %v", v)
	}
	// and the solver itself respects it
	in := mustCompile(t, p)
	a, _, _ := in.Solve(Options{Seed: 2, AnnealIters: 50000})
	st, ok := in.LoadAssignment(a)
	if !ok {
		t.Fatal("infeasible")
	}
	for d := 0; d < p.Days; d++ {
		if popcnt(st.tm[in.TeacherI["ames"]][d]) > 5 {
			t.Errorf("ames teaches > 5 periods on day %d", d)
		}
	}
}

// ---- feature 7: generator ----

func TestGeneratorIsFeasibleByConstruction(t *testing.T) {
	for seed := int64(1); seed <= 12; seed++ {
		p := Generate(GenConfig{Seed: seed, Groups: 4 + int(seed%5), Teachers: 6, Rooms: 5, Days: 5, Periods: 6 + int(seed%3), Load: 0.5 + float64(seed%4)*0.1})
		in := mustCompile(t, p)
		if HasFatal(in.Diagnose()) {
			t.Fatalf("seed %d: generated problem diagnosed impossible: %v", seed, in.Diagnose())
		}
		if len(p.Lessons) == 0 {
			t.Fatalf("seed %d: no lessons", seed)
		}
		if _, _, err := in.Solve(Options{Seed: 1, ConstructFor: 30 * time.Second}); err != nil {
			t.Fatalf("seed %d: planted-feasible problem unsolved: %v", seed, err)
		}
	}
	a, b := Generate(GenConfig{Seed: 5, Groups: 3, Teachers: 4, Rooms: 3}), Generate(GenConfig{Seed: 5, Groups: 3, Teachers: 4, Rooms: 3})
	ja, _ := json.Marshal(a)
	jb, _ := json.Marshal(b)
	if string(ja) != string(jb) {
		t.Error("generator is not deterministic")
	}
}

// ---- feature 8: minimal-disruption re-solve ----

func TestResolveMovesFarFewerSessionsThanFreshSolve(t *testing.T) {
	p, prev := solvedSchool(t)
	// block two sessions of one teacher + delete a used classroom
	var tid string
	var blocked []Slot
	for _, pl := range prev.Placements {
		for _, l := range p.Lessons {
			if l.ID == pl.Lesson && l.Teacher == "diaz" && len(blocked) < 2 {
				tid = l.Teacher
				blocked = append(blocked, Slot{pl.Day, pl.Period})
			}
		}
	}
	p2 := *p
	p2.Teachers = append([]Teacher(nil), p.Teachers...)
	for i := range p2.Teachers {
		if p2.Teachers[i].ID == tid {
			p2.Teachers[i].Unavailable = append(append([]Slot(nil), p2.Teachers[i].Unavailable...), blocked...)
		}
	}
	in2 := mustCompile(t, &p2)
	pa, err := in2.PartialFromSolution(prev)
	if err != nil {
		t.Fatal(err)
	}
	ra, _, err := in2.Solve(Options{Seed: 1, AnnealIters: 100000, Previous: pa})
	if err != nil {
		t.Fatal(err)
	}
	fresh := mustCompile(t, &p2)
	fa, _, err := fresh.Solve(Options{Seed: 1, AnnealIters: 100000})
	if err != nil {
		t.Fatal(err)
	}
	moved, freshMoved := in2.CountMoved(pa, ra), in2.CountMoved(pa, fa)
	if moved > 12 || moved*2 >= freshMoved {
		t.Fatalf("re-solve moved %d sessions, fresh solve moved %d", moved, freshMoved)
	}
	// with a very high stability weight only the forced sessions move
	w := DefaultWeights()
	w.Stability = 1000
	p3 := p2
	p3.Weights = &w
	in3 := mustCompile(t, &p3)
	pa3, _ := in3.PartialFromSolution(prev)
	a3, _, err := in3.Solve(Options{Seed: 1, AnnealIters: 100000, Previous: pa3})
	if err != nil {
		t.Fatal(err)
	}
	if m := in3.CountMoved(pa3, a3); m != len(blocked) {
		t.Fatalf("with stability=1000, %d sessions moved, want exactly the %d blocked ones", m, len(blocked))
	}
	sol := in2.ToSolution(ra)
	v, c, _ := Verify(&p2, sol, prev)
	if len(v) != 0 || c != sol.Cost {
		t.Fatalf("resolve solution: violations %v, verifier cost %d vs solver %d", v, c, sol.Cost)
	}
}

func TestResolveWhenPreviousRoomVanished(t *testing.T) {
	p, prev := solvedSchool(t)
	used := prev.Placements[0].Room
	p2 := *p
	p2.Rooms = nil
	for _, r := range p.Rooms {
		if r.ID != used || r.Kind != "" {
			p2.Rooms = append(p2.Rooms, r)
		}
	}
	in := mustCompile(t, &p2)
	pa, err := in.PartialFromSolution(prev)
	if err != nil {
		t.Fatal(err)
	}
	a, _, err := in.Solve(Options{Seed: 1, AnnealIters: 50000, Previous: pa})
	if err != nil {
		t.Fatal(err)
	}
	sol := in.ToSolution(a)
	v, c, _ := Verify(&p2, sol, prev)
	if len(v) != 0 || c != sol.Cost {
		t.Fatalf("violations %v; verifier cost %d vs solver %d", v, c, sol.Cost)
	}
}

// ---- features 5 & 9: HTML + ICS + text ----

func TestHTMLViewerSelfContainedAndEscaped(t *testing.T) {
	p := tiny()
	p.Name = `</script><!--<img src=x onerror=alert(1)>`
	p.Lessons[0].Subject = `<b>"X"</b> & </script>`
	in := mustCompile(t, p)
	a, _, err := in.Solve(Options{Seed: 1})
	if err != nil {
		t.Fatal(err)
	}
	f := filepath.Join(t.TempDir(), "v.html")
	if err := WriteHTML(f, p, in.ToSolution(a)); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(f)
	h := string(b)
	if strings.Count(h, "</script>") != 1 || strings.Contains(h, "<!--<img") {
		t.Fatal("embedded data can break out of the script element")
	}
	if strings.Contains(h, "/*DATA*/null") {
		t.Fatal("data placeholder not replaced")
	}
	if !strings.Contains(h, `"name":"\u003c/script`) {
		t.Fatal("expected escaped problem name in payload")
	}
	for _, bad := range []string{"http://", "https://", "src=\"http"} {
		if strings.Contains(h, bad) {
			t.Errorf("viewer references external resource %q", bad)
		}
	}
	// the data must still be valid JSON once extracted
	i := strings.Index(h, "const DATA=") + len("const DATA=")
	j := strings.Index(h[i:], ";\n(function")
	var back struct{ Problem Problem }
	if err := json.Unmarshal([]byte(h[i:i+j]), &back); err != nil || back.Problem.Name != p.Name {
		t.Fatalf("payload round-trip failed: %v", err)
	}
}

func TestICS(t *testing.T) {
	p, sol := solvedSchool(t)
	p.Lessons[0].Subject = strings.Repeat("Very long subject, with; punctuation ", 5)
	dir := t.TempDir()
	n, err := WriteICS(dir, p, sol, "2026-09-07")
	if err != nil {
		t.Fatal(err)
	}
	if want := len(p.Groups) + len(p.Teachers); n != want {
		t.Fatalf("wrote %d files, want %d", n, want)
	}
	b, err := os.ReadFile(filepath.Join(dir, "teacher-ames.ics"))
	if err != nil {
		t.Fatal(err)
	}
	txt := string(b)
	if !strings.HasPrefix(txt, "BEGIN:VCALENDAR\r\n") || !strings.HasSuffix(txt, "END:VCALENDAR\r\n") {
		t.Fatal("bad calendar framing")
	}
	events := strings.Count(txt, "BEGIN:VEVENT")
	if events != strings.Count(txt, "END:VEVENT") || events != strings.Count(txt, "RRULE:FREQ=WEEKLY") || events == 0 {
		t.Fatalf("event framing off: %d", events)
	}
	want := 0
	for _, pl := range sol.Placements {
		for _, l := range p.Lessons {
			if l.ID == pl.Lesson && l.Teacher == "ames" {
				want++
			}
		}
	}
	if events != want {
		t.Errorf("ames has %d sessions but calendar has %d events", want, events)
	}
	for _, line := range strings.Split(txt, "\r\n") {
		if len(line) > 75 {
			t.Errorf("unfolded line of %d octets: %.40s...", len(line), line)
		}
	}
	// first event of the school starts on a Monday 2026-09-07 + day offset
	if !strings.Contains(txt, "DTSTART:2026090") {
		t.Errorf("dates not anchored to 2026-09-07:\n%s", txt[:300])
	}
	// unfolded long line round-trips
	unf := strings.ReplaceAll(txt, "\r\n ", "")
	if !strings.Contains(unf, "Very long subject\\, with\\; punctuation") {
		t.Error("escaping/folding lost text")
	}
	if _, err := WriteICS(dir, p, sol, "2026-09-08"); err == nil {
		t.Error("non-Monday start accepted")
	}
	if _, err := WriteICS(dir, p, sol, "soon"); err == nil {
		t.Error("garbage start accepted")
	}
	// determinism: UIDs stable between runs
	n2, _ := WriteICS(t.TempDir(), p, sol, "2026-09-07")
	if n2 != n {
		t.Error("file count differs between runs")
	}
}

func TestTextGrid(t *testing.T) {
	p, sol := solvedSchool(t)
	g := TextGrid(p, sol)
	for _, grp := range p.Groups {
		if !strings.Contains(g, "== group "+grp.ID) {
			t.Errorf("missing group %s", grp.ID)
		}
	}
	if !strings.Contains(g, "Maths/ames/") {
		t.Error("expected maths lessons in grid")
	}
}

func TestEmptyProblem(t *testing.T) {
	p := &Problem{Name: "empty", Days: 5, Periods: 6}
	in := mustCompile(t, p)
	a, _, err := in.Solve(Options{AnnealIters: 100})
	if err != nil {
		t.Fatal(err)
	}
	sol := in.ToSolution(a)
	if len(sol.Placements) != 0 || sol.Cost != 0 {
		t.Fatalf("%+v", sol)
	}
	if err := WriteHTML(filepath.Join(t.TempDir(), "e.html"), p, sol); err != nil {
		t.Fatal(err)
	}
}

func TestFromSolutionRejectsGarbage(t *testing.T) {
	in := mustCompile(t, tiny())
	for _, pl := range []Placement{
		{Lesson: "nope", Session: 1, Room: "r1"},
		{Lesson: "x", Session: 3, Room: "r1"},
		{Lesson: "x", Session: 1, Room: "zz"},
		{Lesson: "x", Session: 1, Day: 5, Room: "r1"},
	} {
		if _, err := in.FromSolution(&Solution{Placements: []Placement{pl}}); err == nil {
			t.Errorf("accepted %+v", pl)
		}
	}
	if _, err := in.FromSolution(&Solution{Placements: []Placement{{Lesson: "x", Session: 1, Room: "r1"}, {Lesson: "x", Session: 1, Room: "r1"}}}); err == nil {
		t.Error("accepted double placement")
	}
}

func TestKempeChainsFireOnDenseInstancesAndStayCorrect(t *testing.T) {
	p := Generate(GenConfig{Seed: 7, Groups: 20, Teachers: 20, Rooms: 12, Load: 0.7})
	in := mustCompile(t, p)
	a, rep, err := in.Solve(Options{Seed: 1, AnnealIters: 400000, ConstructFor: 30 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Anneal.Kempe == 0 {
		t.Error("no Kempe-chain move was ever accepted on a dense instance")
	}
	sol := in.ToSolution(a)
	v, c, _ := Verify(p, sol, nil)
	if len(v) != 0 || c != sol.Cost {
		t.Fatalf("violations %v; cost %d vs %d", v, sol.Cost, c)
	}
	if sol.Cost >= rep.Initial {
		t.Errorf("no improvement: %d -> %d", rep.Initial, sol.Cost)
	}
}
