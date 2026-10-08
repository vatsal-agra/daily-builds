package server

import (
	"strings"
	"testing"
	"time"

	"tide/internal/store"
)

func TestParseRulesValidation(t *testing.T) {
	bad := map[string]string{
		`not json`:                                          "alert rules",
		`[{"expr":"avg(m)","op":">"}]`:                      "name required",
		`[{"name":"a","expr":"avg(m)","op":"=>"}]`:          "op must be",
		`[{"name":"a","expr":"avg(m","op":">"}]`:            "parse error",
		`[{"name":"a","expr":"m","op":">"}]`:                "bare selector",
		`[{"name":"a","expr":"avg(m)","op":">","for":"5"}]`: "for:",
		`[{"name":"a","expr":"avg(m)","op":">"},{"name":"a","expr":"avg(m)","op":">"}]`: "duplicate",
	}
	for in, want := range bad {
		if _, err := ParseRules([]byte(in)); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: err=%v want %q", in, err, want)
		}
	}
	rs, err := ParseRules([]byte(`[{"name":"a","expr":"avg(m)","op":">=","threshold":1,"for":"90s"}]`))
	if err != nil || rs[0].dur != 90*time.Second || rs[0].q.Range != 5*time.Minute {
		t.Fatalf("%+v %v", rs, err)
	}
}

func TestAlertLifecycle(t *testing.T) {
	st, _ := store.Open(store.Options{Dir: t.TempDir()})
	defer st.Close()
	put := func(host string, ts int64, v float64) {
		st.Append([]store.Point{{Labels: store.NewLabels(map[string]string{store.NameLabel: "cpu", "host": host}), T: ts, V: v}})
	}
	rules, err := ParseRules([]byte(`[{"name":"Hot","expr":"avg(cpu) range 2m step 30s","op":">","threshold":80,"for":"60s"}]`))
	if err != nil {
		t.Fatal(err)
	}
	am := NewAlertManager(st, rules)
	base := time.UnixMilli(1_700_000_000_000)
	at := func(sec int) time.Time { return base.Add(time.Duration(sec) * time.Second) }
	state := func() map[string]string {
		m := map[string]string{}
		for _, a := range am.Snapshot() {
			m[a.Series] = a.State
		}
		return m
	}

	// healthy
	put("a", at(0).UnixMilli(), 10)
	am.EvalAll(at(1))
	if s := state(); s[""] != "ok" || len(s) != 1 {
		t.Fatalf("%v", s)
	}
	// host a goes hot, host b is healthy
	put("a", at(10).UnixMilli(), 95)
	put("b", at(10).UnixMilli(), 20)
	am.EvalAll(at(15))
	if s := state(); s[`cpu{host="a"}`] != "pending" || len(s) != 1 {
		t.Fatalf("expected a pending: %v", s)
	}
	// still hot 70 s later => firing
	put("a", at(70).UnixMilli(), 96)
	am.EvalAll(at(80))
	snap := am.Snapshot()
	if len(snap) != 1 || snap[0].State != "firing" || snap[0].Value == nil || *snap[0].Value != 96 || snap[0].Labels["host"] != "a" {
		t.Fatalf("%+v", snap)
	}
	// recovers => resolved
	put("a", at(100).UnixMilli(), 30)
	am.EvalAll(at(110))
	if s := state(); s[""] != "ok" {
		t.Fatalf("not resolved: %v", s)
	}
	// a dip below threshold resets the pending timer
	put("a", at(130).UnixMilli(), 99)
	am.EvalAll(at(135))
	put("a", at(150).UnixMilli(), 10)
	am.EvalAll(at(155))
	put("a", at(170).UnixMilli(), 99)
	am.EvalAll(at(175))
	if s := state(); s[`cpu{host="a"}`] != "pending" {
		t.Fatalf("timer should have restarted: %v", s)
	}
	// data stops entirely => series vanishes from the window => resolved, not stuck firing
	am.EvalAll(at(175 + 600))
	if s := state(); s[""] != "ok" {
		t.Fatalf("stale alert stuck: %v", s)
	}
}

func TestAlertEvalErrorSurfaced(t *testing.T) {
	st, _ := store.Open(store.Options{Dir: t.TempDir()})
	defer st.Close()
	rules, _ := ParseRules([]byte(`[{"name":"X","expr":"avg(m) range 365d step 1s","op":">","threshold":1}]`))
	am := NewAlertManager(st, rules)
	am.EvalAll(time.Now())
	s := am.Snapshot()
	if len(s) != 1 || s[0].State != "ok" || !strings.Contains(s[0].Error, "too many points") {
		t.Fatalf("%+v", s)
	}
}
