package query

import (
	"math"
	"strings"
	"testing"
	"time"

	"tide/internal/store"
)

func TestParseDuration(t *testing.T) {
	ok := map[string]time.Duration{"250ms": 250 * time.Millisecond, "90s": 90 * time.Second, "1h30m": 90 * time.Minute, "2d": 48 * time.Hour, "1w": 168 * time.Hour}
	for s, want := range ok {
		if got, err := ParseDuration(s); err != nil || got != want {
			t.Errorf("%s: %v %v", s, got, err)
		}
	}
	for _, s := range []string{"", "5", "m", "5x", "-5m", "1.5h", "99999999999999w"} {
		if _, err := ParseDuration(s); err == nil {
			t.Errorf("%q accepted", s)
		}
	}
}

func TestParseValid(t *testing.T) {
	q, err := Parse(`sum(rate(http_requests{job="api",code=~"5..",env!="dev",x!~"a|b"})) by (instance, code) range 2h step 30s at latest-5m`)
	if err != nil {
		t.Fatal(err)
	}
	if q.Agg != "sum" || q.Fn != "rate" || len(q.Matchers) != 5 || len(q.By) != 2 || q.Range != 2*time.Hour || q.Step != 30*time.Second || !q.AtLatest || q.AtOffset != -5*time.Minute {
		t.Fatalf("%+v", q)
	}
	q, err = Parse(`cpu`)
	if err != nil || q.Fn != "" || q.Agg != "" || q.Range != time.Hour {
		t.Fatalf("%+v %v", q, err)
	}
	q, err = Parse(`p95(latency{route="/x"})`)
	if err != nil || q.Quantile != 0.95 {
		t.Fatalf("%+v %v", q, err)
	}
	q, err = Parse(`sum(cpu)`) // sum as plain per-series function
	if err != nil || q.Agg != "" || q.Fn != "sum" {
		t.Fatalf("%+v %v", q, err)
	}
	q, err = Parse(`{__name__=~"cpu.*"}`)
	if err != nil || len(q.Matchers) != 1 {
		t.Fatalf("%+v %v", q, err)
	}
	q, err = Parse(`avg(cpu) at 1700000000`)
	if err != nil || !q.HasAt || q.AtMs != 1700000000000 {
		t.Fatalf("%+v %v", q, err)
	}
	q, err = Parse(`avg(cpu) at 2024-01-01T00:00:00Z`)
	if err != nil || q.AtMs != 1704067200000 {
		t.Fatalf("%+v %v", q, err)
	}
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		``:                                "empty",
		`   `:                             "empty",
		`avg(`:                            "expected metric",
		`avg(cpu`:                         `expected ")"`,
		`cpu{`:                            "label name",
		`cpu{a}`:                          "expected one of",
		`cpu{a=b}`:                        "quoted string",
		`cpu{a="b" c="d"}`:                "expected ','",
		`cpu{a=~"("}`:                     "bad regex",
		`cpu{a=="b"}`:                     "quoted string",
		`cpu{a="unterminated}`:            "unterminated",
		`cpu by (x)`:                      "requires an aggregation",
		`sum(avg(cpu)) by x`:              `expected "("`,
		`sum(avg(cpu)) range`:             "expected duration",
		`sum(avg(cpu)) range 5`:           "missing unit",
		`sum(avg(cpu)) range 5m range 6m`: "duplicate",
		`sum(avg(cpu)) frobnicate 5`:      "unknown clause",
		`cpu step 1m`:                     "step needs a function",
		`avg(cpu) at yesterday`:           "cannot parse time",
		`avg(cpu) at now-zz`:              "duration",
		`p0(cpu)`:                         "expected",
		`avg(cpu)) `:                      "unexpected",
		`{}`:                              "empty selector",
		`cpu!`:                            "unexpected",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil {
			t.Errorf("%q: expected error containing %q", src, want)
		} else if !strings.Contains(err.Error(), want) {
			t.Errorf("%q: error %q does not contain %q", src, err, want)
		}
	}
}

// ---- evaluation ----

func newStore(t *testing.T) *store.Store {
	s, err := store.Open(store.Options{Dir: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func ls(name string, kv ...string) store.Labels {
	m := map[string]string{store.NameLabel: name}
	for i := 0; i < len(kv); i += 2 {
		m[kv[i]] = kv[i+1]
	}
	return store.NewLabels(m)
}

func eval(t *testing.T, s *store.Store, q string, now int64) *Result {
	t.Helper()
	p, err := Parse(q)
	if err != nil {
		t.Fatal(err)
	}
	r, err := Eval(p, s, time.UnixMilli(now))
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func vals(r ResultSeries) []float64 {
	var o []float64
	for _, p := range r.Points {
		o = append(o, p.V)
	}
	return o
}

func approx(a, b float64) bool { return math.Abs(a-b) < 1e-9 }

func TestRawAndRange(t *testing.T) {
	s := newStore(t)
	var pts []store.Point
	for i := 0; i < 100; i++ {
		pts = append(pts, store.Point{Labels: ls("m", "h", "a"), T: int64(i) * 1000, V: float64(i)})
	}
	s.Append(pts)
	r := eval(t, s, `m{h="a"} range 10s`, 99_000)
	if r.Kind != "raw" || len(r.Series) != 1 || len(r.Series[0].Points) != 11 || r.Series[0].Points[0].V != 89 {
		t.Fatalf("%+v", r)
	}
	r = eval(t, s, `m{h="zzz"}`, 99_000)
	if len(r.Series) != 0 {
		t.Fatal("expected empty")
	}
}

func TestBucketFunctions(t *testing.T) {
	s := newStore(t)
	// samples at 0,10,20,...,590 s with value = t/10  -> 60 samples
	var pts []store.Point
	for i := 0; i < 60; i++ {
		pts = append(pts, store.Point{Labels: ls("m"), T: int64(i) * 10_000, V: float64(i)})
	}
	s.Append(pts)
	// 6 samples per 1m bucket: values 6k..6k+5
	r := eval(t, s, `avg(m) range 10m step 1m at 600`, 0)
	v := vals(r.Series[0])
	if len(v) != 10 || !approx(v[0], 2.5) || !approx(v[9], 56.5) {
		t.Fatalf("avg %v", v)
	}
	for fn, want := range map[string][2]float64{"min": {0, 54}, "max": {5, 59}, "sum": {15, 339}, "count": {6, 6}, "last": {5, 59}} {
		v := vals(eval(t, s, fn+`(m) range 10m step 1m at 600`, 0).Series[0])
		if !approx(v[0], want[0]) || !approx(v[9], want[1]) {
			t.Errorf("%s: %v want %v", fn, v, want)
		}
	}
	// p50 of 0..5 = 2.5 (interpolated)
	v = vals(eval(t, s, `p50(m) range 10m step 1m at 600`, 0).Series[0])
	if !approx(v[0], 2.5) {
		t.Fatalf("p50 %v", v)
	}
	v = vals(eval(t, s, `p99(m) range 10m step 1m at 600`, 0).Series[0])
	if !approx(v[0], 0.99*5) {
		t.Fatalf("p99 %v", v)
	}
	// increase over a 1m bucket = 6 (incl. delta from previous bucket's last sample)
	v = vals(eval(t, s, `increase(m) range 10m step 1m at 600`, 0).Series[0])
	if !approx(v[1], 6) || !approx(v[9], 6) {
		t.Fatalf("increase %v", v)
	}
	v = vals(eval(t, s, `rate(m) range 10m step 1m at 600`, 0).Series[0])
	if !approx(v[1], 0.1) { // 6 per 60 s
		t.Fatalf("rate %v", v)
	}
}

func TestRateCounterReset(t *testing.T) {
	s := newStore(t)
	// counter climbs 0,10,20,30 then resets to 5,15 (so +5 after reset, then +10)
	series := []float64{0, 10, 20, 30, 5, 15}
	var pts []store.Point
	for i, v := range series {
		pts = append(pts, store.Point{Labels: ls("c"), T: int64(i) * 10_000, V: v})
	}
	s.Append(pts)
	v := vals(eval(t, s, `increase(c) range 1m step 1m at 60`, 0).Series[0])
	// deltas: 10,10,10,5(reset: value itself),10 => 45 in bucket 0 (the first sample has no predecessor)
	if len(v) < 1 || !approx(v[0], 45) {
		t.Fatalf("increase with reset: %v", v)
	}
}

func TestAggregationAndBy(t *testing.T) {
	s := newStore(t)
	var pts []store.Point
	for i := 0; i < 12; i++ {
		ts := int64(i) * 10_000
		pts = append(pts,
			store.Point{Labels: ls("req", "host", "a", "dc", "x"), T: ts, V: 1},
			store.Point{Labels: ls("req", "host", "b", "dc", "x"), T: ts, V: 2},
			store.Point{Labels: ls("req", "host", "c", "dc", "y"), T: ts, V: 4},
		)
	}
	s.Append(pts)
	r := eval(t, s, `sum(avg(req)) by (dc) range 2m step 1m at 120`, 0)
	if len(r.Series) != 2 || r.Series[0].Labels["dc"] != "x" || !approx(r.Series[0].Points[0].V, 3) || !approx(r.Series[1].Points[0].V, 4) {
		t.Fatalf("%+v", r.Series)
	}
	r = eval(t, s, `max(avg(req)) range 2m step 1m at 120`, 0)
	if len(r.Series) != 1 || len(r.Series[0].Labels) != 0 || !approx(r.Series[0].Points[0].V, 4) {
		t.Fatalf("%+v", r.Series)
	}
	r = eval(t, s, `count(last(req{host=~"a|b"})) range 2m step 1m at 120`, 0)
	if !approx(r.Series[0].Points[0].V, 2) {
		t.Fatalf("%+v", r.Series)
	}
	// per-series function without aggregation keeps series separate
	r = eval(t, s, `avg(req) range 2m step 1m at 120`, 0)
	if len(r.Series) != 3 {
		t.Fatalf("%d series", len(r.Series))
	}
}

func TestEvalAtLatestAndLimits(t *testing.T) {
	s := newStore(t)
	s.Append([]store.Point{{Labels: ls("m"), T: 5_000_000, V: 1}, {Labels: ls("m"), T: 5_010_000, V: 2}})
	r := eval(t, s, `m range 1m at latest`, 123)
	if len(r.Series) != 1 || len(r.Series[0].Points) != 2 {
		t.Fatalf("%+v", r)
	}
	r = eval(t, newStore(t), `m at latest`, 1) // empty store
	if len(r.Series) != 0 {
		t.Fatal("expected no series")
	}
	p, _ := Parse(`avg(m) range 30d step 1s`)
	if _, err := Eval(p, s, time.Now()); err == nil || !strings.Contains(err.Error(), "too many points") {
		t.Fatalf("expected point limit error, got %v", err)
	}
}

func TestAutoStep(t *testing.T) {
	if got := autoStep(3_600_000); got != 30_000 {
		t.Fatal(got)
	}
	if got := autoStep(1000); got != 1000 {
		t.Fatal(got)
	}
	if got := autoStep(1 << 50); got != 86_400_000 {
		t.Fatal(got)
	}
}

func TestPartialTrailingBucketOmittedForExtensiveFns(t *testing.T) {
	s := newStore(t)
	var pts []store.Point
	for i := 0; i < 95; i++ { // 0..940 s, so the 15th minute bucket is only 40 s full
		pts = append(pts, store.Point{Labels: ls("c"), T: int64(i) * 10_000, V: float64(i * 10)})
	}
	s.Append(pts)
	r := eval(t, s, `rate(c) range 10m step 1m at 940`, 0)
	v := r.Series[0].Points
	if v[len(v)-1].T != 840_000 || !approx(v[len(v)-1].V, 1) {
		t.Fatalf("trailing partial bucket leaked: %+v", v[len(v)-1])
	}
	r = eval(t, s, `avg(c) range 10m step 1m at 940`, 0)
	if p := r.Series[0].Points; p[len(p)-1].T != 900_000 {
		t.Fatal("avg should keep the partial bucket")
	}
}
