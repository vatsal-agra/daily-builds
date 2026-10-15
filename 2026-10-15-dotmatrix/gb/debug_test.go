package gb

import "testing"

func TestConditionOperators(t *testing.T) {
	g := onlyOp(t, 0)
	g.a, g.b, g.c = 5, 0x12, 0x34
	g.write(0xC000, 7)
	type tc struct {
		cond string
		want bool
	}
	for _, c := range []tc{
		{"a == 5", true}, {"a == 6", false}, {"a != 5", false}, {"a != 6", true},
		{"a < 6", true}, {"a < 5", false}, {"a <= 5", true}, {"a <= 4", false},
		{"a > 4", true}, {"a > 5", false}, {"a >= 5", true}, {"a >= 6", false},
		{"bc == 0x1234", true}, {"bc == $1234", true}, {"b == 18", true},
		{"[0xC000] == 7", true}, {"[0xC000] != 7", false}, {"[$C000] >= 8", false},
		{"a == 5 && b == 0x12", true}, {"a == 5 && b == 0x13", false}, {"a == 4 && b == 0x12", false},
		{"pc == 0x150", true}, {"sp > 0xFF00", true}, {"a == -1", false},
	} {
		cond, err := ParseCondition(c.cond)
		if err != nil {
			t.Errorf("%q: %v", c.cond, err)
			continue
		}
		if got := cond.Eval(g); got != c.want {
			t.Errorf("%q = %v, want %v", c.cond, got, c.want)
		}
	}
	for _, bad := range []string{"", "a", "a ==", "zz == 1", "[zz] == 1", "[0x10000] == 1", "a = 1", "a == x"} {
		if _, err := ParseCondition(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
}

func TestSetRegAndWatchpoints(t *testing.T) {
	g := onlyOp(t, 0)
	for _, c := range []struct {
		reg string
		v   int
		ok  bool
	}{{"a", 0xFF, true}, {"a", 0x100, false}, {"hl", 0xFFFF, true}, {"hl", 0x10000, false}, {"f", 0xFF, true}, {"xx", 1, false}, {"a", -1, false}} {
		err := g.SetReg(c.reg, c.v)
		if (err == nil) != c.ok {
			t.Errorf("SetReg(%s,%d): %v", c.reg, c.v, err)
		}
	}
	if g.f != 0xF0 {
		t.Errorf("F low nibble must stay 0: %02X", g.f)
	}
	// write watch fires once per write, read watch on reads only
	g = buildRaw(t, "\t.org 0x100\n\tjp main\n\t.org 0x150\nmain:\n\tld a, 1\n\tld [0xC000], a\n\tld a, [0xC000]\n\tnop\n\thalt\n")
	g.Dbg = NewDebugger()
	w := g.Dbg.AddWatch(0xC000, WatchWrite)
	r := g.Dbg.AddWatch(0xC000, WatchRead)
	stops := map[string]int{}
	for i := 0; i < 20; i++ {
		if err := g.StepChecked(); err != nil {
			if st, ok := err.(*StopError); ok {
				stops[st.Kind]++
				continue
			}
			t.Fatal(err)
		}
	}
	if w.Hits != 1 || r.Hits != 1 || stops["watchpoint"] != 2 {
		t.Errorf("write hits=%d read hits=%d stops=%v", w.Hits, r.Hits, stops)
	}
	if !g.Dbg.Delete(w.ID) || g.Dbg.Delete(999) {
		t.Error("Delete")
	}
	if h := g.Dbg.History(5); len(h) != 5 {
		t.Errorf("history length %d", len(h))
	}
}
