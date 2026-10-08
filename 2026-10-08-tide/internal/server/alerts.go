package server

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
	"sync"
	"time"

	"tide/internal/query"
	"tide/internal/store"
)

// Rule is one alert definition as written in the rules file (JSON array).
//
//	{"name":"HighCPU","expr":"avg(cpu_usage_percent) range 2m step 1m","op":">","threshold":80,"for":"2m"}
//
// The expression is evaluated every interval; for every resulting series the
// newest point is compared against the threshold. A series whose condition has
// held continuously for `for` becomes firing; before that it is pending.
type Rule struct {
	Name      string  `json:"name"`
	Expr      string  `json:"expr"`
	Op        string  `json:"op"`
	Threshold float64 `json:"threshold"`
	For       string  `json:"for"`
	Summary   string  `json:"summary,omitempty"`

	q   *query.Query
	dur time.Duration
}

type AlertState struct {
	Name      string            `json:"name"`
	Expr      string            `json:"expr"`
	State     string            `json:"state"` // ok | pending | firing
	Labels    map[string]string `json:"labels,omitempty"`
	Series    string            `json:"series,omitempty"`
	Value     *float64          `json:"value"`
	Op        string            `json:"op"`
	Threshold float64           `json:"threshold"`
	Since     int64             `json:"since,omitempty"` // unix ms the condition became true
	Summary   string            `json:"summary,omitempty"`
	Error     string            `json:"error,omitempty"`
}

type instance struct {
	labels store.Labels
	since  int64
	value  float64
	state  string
}

type AlertManager struct {
	src      query.Source
	rules    []*Rule
	Interval time.Duration

	mu    sync.Mutex
	inst  map[string]map[string]*instance // rule name -> series key -> instance
	errs  map[string]string
	ready bool
}

var cmpOps = map[string]func(a, b float64) bool{
	">":  func(a, b float64) bool { return a > b },
	">=": func(a, b float64) bool { return a >= b },
	"<":  func(a, b float64) bool { return a < b },
	"<=": func(a, b float64) bool { return a <= b },
	"==": func(a, b float64) bool { return a == b },
	"!=": func(a, b float64) bool { return a != b },
}

// ParseRules validates a JSON rules document.
func ParseRules(data []byte) ([]*Rule, error) {
	var rules []*Rule
	if err := json.Unmarshal(data, &rules); err != nil {
		return nil, fmt.Errorf("alert rules: %w", err)
	}
	seen := map[string]bool{}
	for i, r := range rules {
		where := fmt.Sprintf("alert rule #%d (%q)", i+1, r.Name)
		if r.Name == "" {
			return nil, fmt.Errorf("%s: name required", where)
		}
		if seen[r.Name] {
			return nil, fmt.Errorf("%s: duplicate name", where)
		}
		seen[r.Name] = true
		if _, ok := cmpOps[r.Op]; !ok {
			return nil, fmt.Errorf("%s: op must be one of > >= < <= == != (got %q)", where, r.Op)
		}
		if math.IsNaN(r.Threshold) || math.IsInf(r.Threshold, 0) {
			return nil, fmt.Errorf("%s: threshold must be finite", where)
		}
		q, err := query.Parse(r.Expr)
		if err != nil {
			return nil, fmt.Errorf("%s: %v", where, err)
		}
		if q.Fn == "" {
			return nil, fmt.Errorf("%s: expr must use a function such as avg(...) or rate(...), not a bare selector", where)
		}
		if !q.RangeSet {
			q.Range = 5 * time.Minute
		}
		r.q = q
		if r.For != "" {
			d, err := query.ParseDuration(r.For)
			if err != nil {
				return nil, fmt.Errorf("%s: for: %v", where, err)
			}
			r.dur = d
		}
	}
	return rules, nil
}

func NewAlertManager(src query.Source, rules []*Rule) *AlertManager {
	return &AlertManager{src: src, rules: rules, Interval: 15 * time.Second,
		inst: map[string]map[string]*instance{}, errs: map[string]string{}}
}

func LoadAlerts(path string, st *store.Store) (*AlertManager, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	rules, err := ParseRules(data)
	if err != nil {
		return nil, err
	}
	return NewAlertManager(st, rules), nil
}

func (a *AlertManager) RuleCount() int { return len(a.rules) }

// Run evaluates all rules every Interval until ctx is cancelled.
func (a *AlertManager) Run(ctx context.Context, now func() time.Time) {
	a.EvalAll(now())
	t := time.NewTicker(a.Interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			a.EvalAll(now())
		}
	}
}

// EvalAll runs one evaluation round at time now.
func (a *AlertManager) EvalAll(now time.Time) {
	for _, r := range a.rules {
		res, err := query.Eval(r.q, a.src, now)
		a.mu.Lock()
		a.ready = true
		if err != nil {
			a.errs[r.Name] = err.Error()
			a.mu.Unlock()
			continue
		}
		delete(a.errs, r.Name)
		cur := a.inst[r.Name]
		if cur == nil {
			cur = map[string]*instance{}
			a.inst[r.Name] = cur
		}
		cmp := cmpOps[r.Op]
		seen := map[string]bool{}
		for _, s := range res.Series {
			if len(s.Points) == 0 {
				continue
			}
			last := s.Points[len(s.Points)-1]
			ls := store.NewLabels(s.Labels)
			key := ls.Key()
			seen[key] = true
			in := cur[key]
			if !cmp(last.V, r.Threshold) {
				delete(cur, key) // condition cleared: resolved
				continue
			}
			if in == nil {
				in = &instance{labels: ls, since: now.UnixMilli()}
				cur[key] = in
			}
			in.value = last.V
			in.state = "pending"
			if now.UnixMilli()-in.since >= r.dur.Milliseconds() {
				in.state = "firing"
			}
		}
		for key := range cur {
			if !seen[key] { // series disappeared (no recent data): resolve
				delete(cur, key)
			}
		}
		a.mu.Unlock()
	}
}

// Snapshot returns every active alert instance plus one "ok" row per rule
// that has none, sorted firing → pending → ok.
func (a *AlertManager) Snapshot() []AlertState {
	a.mu.Lock()
	defer a.mu.Unlock()
	out := []AlertState{}
	for _, r := range a.rules {
		base := AlertState{Name: r.Name, Expr: r.Expr, Op: r.Op, Threshold: r.Threshold, Summary: r.Summary, Error: a.errs[r.Name]}
		cur := a.inst[r.Name]
		if len(cur) == 0 {
			base.State = "ok"
			out = append(out, base)
			continue
		}
		for _, in := range cur {
			s := base
			s.State, s.Since, s.Labels, s.Series = in.state, in.since, in.labels.Map(), in.labels.String()
			v := in.value
			s.Value = &v
			out = append(out, s)
		}
	}
	rank := map[string]int{"firing": 0, "pending": 1, "ok": 2}
	sort.SliceStable(out, func(i, j int) bool {
		if rank[out[i].State] != rank[out[j].State] {
			return rank[out[i].State] < rank[out[j].State]
		}
		if out[i].Name != out[j].Name {
			return out[i].Name < out[j].Name
		}
		return out[i].Series < out[j].Series
	})
	return out
}
