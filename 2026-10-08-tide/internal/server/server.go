// Package server exposes the store over HTTP and serves the dashboard.
package server

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"tide/internal/query"
	"tide/internal/store"
)

//go:embed ui/index.html
var indexHTML []byte

const maxBody = 32 << 20

type Server struct {
	Store  *store.Store
	Now    func() time.Time
	Alerts *AlertManager // optional
}

func New(s *store.Store) *Server { return &Server{Store: s, Now: time.Now} }

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(indexHTML)
	})
	mux.HandleFunc("POST /write", s.write)
	mux.HandleFunc("GET /query", s.query)
	mux.HandleFunc("GET /series", s.series)
	mux.HandleFunc("GET /stats", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, s.Store.Stats()) })
	mux.HandleFunc("POST /flush", func(w http.ResponseWriter, r *http.Request) {
		if err := s.Store.Flush(); err != nil {
			writeErr(w, 500, err)
			return
		}
		writeJSON(w, 200, s.Store.Stats())
	})
	mux.HandleFunc("POST /compact", func(w http.ResponseWriter, r *http.Request) {
		res, err := s.Store.Compact()
		if err != nil {
			writeErr(w, 500, err)
			return
		}
		writeJSON(w, 200, res)
	})
	mux.HandleFunc("POST /retention", s.retention)
	mux.HandleFunc("GET /alerts", s.alerts)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, "ok\n") })
	return mux
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	b, err := json.Marshal(v) // marshal first so an encoding failure can't produce a truncated 200
	if err != nil {
		b, code = []byte(`{"error":"internal: cannot encode response"}`), 500
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	w.Write(append(b, '\n'))
}

func writeErr(w http.ResponseWriter, code int, err error) {
	body := map[string]any{"error": err.Error()}
	var pe *query.ParseError
	if errors.As(err, &pe) {
		body["pos"] = pe.Pos
	}
	writeJSON(w, code, body)
}

func (s *Server) write(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxBody)
	b, err := io.ReadAll(r.Body)
	if err != nil {
		writeErr(w, http.StatusRequestEntityTooLarge, fmt.Errorf("body too large (max %d MB) or unreadable", maxBody>>20))
		return
	}
	pts, perrs := ParseLines(string(b), s.Now())
	res, err := s.Store.Append(pts)
	if err != nil {
		writeErr(w, 500, err)
		return
	}
	if len(perrs) > 10 {
		perrs = append(perrs[:10], fmt.Sprintf("... and %d more", len(perrs)-10))
	}
	code := 200
	if len(pts) == 0 && len(perrs) > 0 {
		code = 400
	}
	writeJSON(w, code, map[string]any{"accepted": res.Accepted, "outOfOrder": res.OutOfOrder,
		"invalid": res.Invalid, "firstInvalid": res.FirstInvalid, "parseErrors": perrs})
}

func (s *Server) query(w http.ResponseWriter, r *http.Request) {
	qs := r.URL.Query().Get("q")
	q, err := query.Parse(qs)
	if err != nil {
		writeErr(w, 400, err)
		return
	}
	now := s.Now()
	if e := r.URL.Query().Get("now"); e != "" { // lets clients pin the clock (tests, replays)
		ms, err := strconv.ParseInt(e, 10, 64)
		if err != nil {
			writeErr(w, 400, fmt.Errorf("bad now parameter"))
			return
		}
		now = time.UnixMilli(ms)
	}
	start := time.Now()
	res, err := query.Eval(q, s.Store, now)
	if err != nil {
		writeErr(w, 422, err)
		return
	}
	w.Header().Set("X-Tide-Eval-Ms", strconv.FormatFloat(float64(time.Since(start).Microseconds())/1000, 'f', 2, 64))
	writeJSON(w, 200, res)
}

func (s *Server) series(w http.ResponseWriter, r *http.Request) {
	var ms []*store.Matcher
	if m := r.URL.Query().Get("match"); m != "" {
		q, err := query.Parse(m)
		if err != nil {
			writeErr(w, 400, err)
			return
		}
		ms = q.Matchers
	}
	limit := 5000
	if l := r.URL.Query().Get("limit"); l != "" {
		n, err := strconv.Atoi(l)
		if err != nil || n < 1 {
			writeErr(w, 400, fmt.Errorf("bad limit"))
			return
		}
		limit = n
	}
	out := []map[string]string{}
	for _, ls := range s.Store.SeriesLabels(ms) {
		if len(out) >= limit {
			w.Header().Set("X-Tide-Truncated", "true")
			break
		}
		out = append(out, ls.Map())
	}
	writeJSON(w, 200, out)
}

func (s *Server) retention(w http.ResponseWriter, r *http.Request) {
	d, err := query.ParseDuration(r.URL.Query().Get("older"))
	if err != nil {
		writeErr(w, 400, fmt.Errorf("older: %v", err))
		return
	}
	_, mx, ok := s.Store.TimeRange()
	ref := s.Now().UnixMilli()
	if ok && r.URL.Query().Get("relativeTo") == "latest" {
		ref = mx
	}
	n, err := s.Store.DropBefore(ref - d.Milliseconds())
	if err != nil {
		writeErr(w, 500, err)
		return
	}
	writeJSON(w, 200, map[string]int{"blocksDropped": n})
}

func (s *Server) alerts(w http.ResponseWriter, r *http.Request) {
	if s.Alerts == nil {
		writeJSON(w, 200, []AlertState{})
		return
	}
	writeJSON(w, 200, s.Alerts.Snapshot())
}
