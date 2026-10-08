package server

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"

	"tide/internal/store"
)

var t0 = time.UnixMilli(1_700_000_000_000)

func TestParseLines(t *testing.T) {
	body := `# comment
cpu{host="a",dc="x"} 12.5 1700000000000
cpu 3
mem{host="b c",q="say \"hi\""} 1 1700000000
bad{host=a} 1
nan 1e999
x{a="1",a="2"} 1
{a="b"} 1
justname
cpu{host="a"} 1 notanumber
`
	pts, errs := ParseLines(body, t0)
	if len(pts) != 3 || len(errs) != 6 {
		t.Fatalf("pts=%d errs=%v", len(pts), errs)
	}
	if pts[0].T != 1_700_000_000_000 || pts[0].V != 12.5 || pts[0].Labels.Get("dc") != "x" {
		t.Fatalf("%+v", pts[0])
	}
	if pts[1].T != t0.UnixMilli() || pts[1].Labels.String() != "cpu" {
		t.Fatalf("default ts: %+v", pts[1])
	}
	if pts[2].T != 1_700_000_000_000 || pts[2].Labels.Get("host") != "b c" || pts[2].Labels.Get("q") != `say "hi"` {
		t.Fatalf("seconds/escapes: %+v", pts[2])
	}
}

func newServer(t *testing.T) (*httptest.Server, *store.Store) {
	st, err := store.Open(store.Options{Dir: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	srv := New(st)
	srv.Now = func() time.Time { return t0 }
	ts := httptest.NewServer(srv.Handler())
	t.Cleanup(func() { ts.Close(); st.Close() })
	return ts, st
}

func do(t *testing.T, method, u, body string) (int, map[string]any, string) {
	t.Helper()
	req, _ := http.NewRequest(method, u, strings.NewReader(body))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var m map[string]any
	json.Unmarshal(raw, &m)
	return resp.StatusCode, m, string(raw)
}

func TestEndToEndHTTP(t *testing.T) {
	ts, _ := newServer(t)
	var b strings.Builder
	for i := 0; i < 60; i++ {
		ms := t0.UnixMilli() - int64(60-i)*10_000
		b.WriteString("reqs{host=\"a\",code=\"200\"} " + strconv.Itoa(i*10) + " " + strconv.FormatInt(ms, 10) + "\n")
		b.WriteString("reqs{host=\"b\",code=\"200\"} " + strconv.Itoa(i*20) + " " + strconv.FormatInt(ms, 10) + "\n")
	}
	code, m, _ := do(t, "POST", ts.URL+"/write", b.String())
	if code != 200 || m["accepted"].(float64) != 120 {
		t.Fatalf("%d %v", code, m)
	}
	q := func(expr string) (int, map[string]any) {
		c, m, _ := do(t, "GET", ts.URL+"/query?q="+url.QueryEscape(expr), "")
		return c, m
	}
	code, m = q(`sum(rate(reqs{code="200"})) range 5m step 1m`)
	if code != 200 {
		t.Fatalf("%v", m)
	}
	pts := m["series"].([]any)[0].(map[string]any)["points"].([]any)
	// a: +1/s, b: +2/s => 3/s
	if v := pts[1].(map[string]any)["v"].(float64); v < 2.9 || v > 3.1 {
		t.Fatalf("rate=%v", v)
	}
	code, m = q(`sum(avg(reqs`)
	if code != 400 || m["error"] == nil || m["pos"] == nil {
		t.Fatalf("parse error response: %d %v", code, m)
	}
	code, m = q(`avg(reqs) range 365d step 1s`)
	if code != 422 {
		t.Fatalf("limit: %d %v", code, m)
	}
	_, _, raw := do(t, "GET", ts.URL+"/series?match="+url.QueryEscape(`reqs{host="a"}`), "")
	if !strings.Contains(raw, `"host":"a"`) || strings.Contains(raw, `"host":"b"`) {
		t.Fatal(raw)
	}
	code, m, _ = do(t, "POST", ts.URL+"/write", "garbage\nmore garbage")
	if code != 400 {
		t.Fatalf("all-bad write should be 400, got %d", code)
	}
	code, m, _ = do(t, "POST", ts.URL+"/flush", "")
	if code != 200 || m["blocks"].(float64) != 1 || m["headSamples"].(float64) != 0 {
		t.Fatalf("%v", m)
	}
	code, m = q(`reqs{host="b"} range 2m`) // still queryable from the block
	if code != 200 || len(m["series"].([]any)) != 1 {
		t.Fatalf("%v", m)
	}
	code, m, _ = do(t, "POST", ts.URL+"/retention?older=1x", "")
	if code != 400 {
		t.Fatal("bad retention duration accepted")
	}
	code, m, _ = do(t, "POST", ts.URL+"/retention?older=1m", "")
	if code != 200 || m["blocksDropped"].(float64) != 0 { // block holds data newer than now-1m
		t.Fatalf("%v", m)
	}
	if code, _, body := do(t, "GET", ts.URL+"/", ""); code != 200 || !strings.Contains(body, "<title>Tide</title>") {
		t.Fatal("dashboard not served")
	}
	if code, _, _ := do(t, "GET", ts.URL+"/nope", ""); code != 404 {
		t.Fatal("expected 404")
	}
}

func TestWriteBodyLimit(t *testing.T) {
	ts, _ := newServer(t)
	big := strings.Repeat("a", maxBody+10)
	code, m, _ := do(t, "POST", ts.URL+"/write", big)
	if code != 413 {
		t.Fatalf("%d %v", code, m)
	}
}
