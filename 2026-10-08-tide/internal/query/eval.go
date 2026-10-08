package query

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"tide/internal/store"
)

// Source is what the evaluator needs from the storage engine.
type Source interface {
	Select(ms []*store.Matcher, mint, maxt int64) ([]store.Series, error)
	TimeRange() (minT, maxT int64, ok bool)
}

type Point struct {
	T int64   `json:"t"`
	V float64 `json:"v"`
}

type ResultSeries struct {
	Labels map[string]string `json:"labels"`
	Name   string            `json:"name"` // display string
	Points []Point           `json:"points"`
}

type Result struct {
	Query  string         `json:"query"`
	Kind   string         `json:"kind"` // "raw" or "matrix"
	Start  int64          `json:"start"`
	End    int64          `json:"end"`
	StepMs int64          `json:"stepMs"`
	Series []ResultSeries `json:"series"`
}

const maxPoints = 11000

// Eval executes q against src. now is the wall clock used for "now" and the
// default end of range.
func Eval(q *Query, src Source, now time.Time) (*Result, error) {
	end := now.UnixMilli()
	if q.AtLatest {
		_, mx, ok := src.TimeRange()
		if !ok {
			return &Result{Query: q.Source, Kind: kind(q), Start: end, End: end, Series: []ResultSeries{}}, nil
		}
		end = mx + q.AtOffset.Milliseconds()
	} else if q.HasAt {
		end = q.AtMs
	} else if q.AtRelNow {
		end += q.AtOffset.Milliseconds()
	}
	rangeMs := q.Range.Milliseconds()
	if rangeMs < 1 {
		return nil, fmt.Errorf("range too small")
	}
	start := end - rangeMs
	res := &Result{Query: q.Source, Kind: kind(q), Start: start, End: end, Series: []ResultSeries{}}

	if q.Fn == "" {
		ss, err := src.Select(q.Matchers, start, end)
		if err != nil {
			return nil, err
		}
		for _, s := range ss {
			rs := ResultSeries{Labels: s.Labels.Map(), Name: s.Labels.String(), Points: make([]Point, len(s.Samples))}
			for i, x := range s.Samples {
				rs.Points[i] = Point{x.T, x.V}
			}
			res.Series = append(res.Series, rs)
		}
		return res, nil
	}

	step := q.Step.Milliseconds()
	if step <= 0 {
		step = autoStep(rangeMs)
	}
	if rangeMs/step > maxPoints {
		return nil, fmt.Errorf("too many points: range/step = %d (max %d); use a larger step", rangeMs/step, maxPoints)
	}
	res.StepMs = step
	res.Start = floorDiv(start, step) * step // first bucket boundary, so the axis starts at a real point
	// Buckets are aligned to multiples of step. rate/increase additionally
	// need the sample preceding the first bucket as a baseline.
	first := floorDiv(start, step) * step
	ss, err := src.Select(q.Matchers, first-step, end)
	if err != nil {
		return nil, err
	}
	type seriesBuckets struct {
		labels store.Labels
		vals   map[int64]float64
	}
	var per []seriesBuckets
	for _, s := range ss {
		vals := finite(bucketize(q, s.Samples, first, end, step))
		if len(vals) > 0 {
			per = append(per, seriesBuckets{s.Labels, vals})
		}
	}
	if q.Agg == "" {
		for _, sb := range per {
			res.Series = append(res.Series, ResultSeries{Labels: sb.labels.Map(), Name: sb.labels.String(), Points: sortedPoints(sb.vals)})
		}
		return res, nil
	}
	// cross-series aggregation, grouped by `by` labels
	type group struct {
		labels store.Labels
		cols   map[int64][]float64
	}
	groups := map[string]*group{}
	for _, sb := range per {
		gl := groupLabels(sb.labels, q.By)
		g := groups[gl.Key()]
		if g == nil {
			g = &group{labels: gl, cols: map[int64][]float64{}}
			groups[gl.Key()] = g
		}
		for t, v := range sb.vals {
			g.cols[t] = append(g.cols[t], v)
		}
	}
	keys := make([]string, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		g := groups[k]
		vals := make(map[int64]float64, len(g.cols))
		for t, vs := range g.cols {
			vals[t] = aggregate(q.Agg, vs)
		}
		vals = finite(vals)
		if len(vals) == 0 {
			continue
		}
		name := q.Agg + g.labels.String()
		if len(g.labels) == 0 {
			name = q.Agg + "()"
		}
		res.Series = append(res.Series, ResultSeries{Labels: g.labels.Map(), Name: name, Points: sortedPoints(vals)})
	}
	return res, nil
}

// finite drops buckets whose value overflowed to ±Inf/NaN (JSON cannot carry them).
func finite(m map[int64]float64) map[int64]float64 {
	for t, v := range m {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			delete(m, t)
		}
	}
	return m
}

func kind(q *Query) string {
	if q.Fn == "" {
		return "raw"
	}
	return "matrix"
}

func groupLabels(ls store.Labels, by []string) store.Labels {
	m := map[string]string{}
	for _, n := range by {
		if v := ls.Get(n); v != "" {
			m[n] = v
		}
	}
	return store.NewLabels(m)
}

func floorDiv(a, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// autoStep targets ~120 points, snapped to a human-friendly size.
func autoStep(rangeMs int64) int64 {
	target := rangeMs / 120
	nice := []int64{1000, 2000, 5000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000, 600_000, 900_000,
		1_800_000, 3_600_000, 7_200_000, 21_600_000, 43_200_000, 86_400_000}
	for _, n := range nice {
		if n >= target {
			return n
		}
	}
	return nice[len(nice)-1]
}

func sortedPoints(m map[int64]float64) []Point {
	out := make([]Point, 0, len(m))
	for t, v := range m {
		out = append(out, Point{t, v})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].T < out[j].T })
	return out
}

// extensive functions scale with how much time a bucket covers, so a bucket
// still being filled (it ends after the query end) would plot a misleading
// cliff; those are omitted. Intensive ones (avg, min, max, last, pNN) are fine.
func extensive(fn string) bool {
	return fn == "rate" || fn == "increase" || fn == "sum" || fn == "count"
}

// bucketize reduces one series' samples to one value per step bucket
// [t, t+step). Buckets before the query start are dropped; buckets with no
// data produce no point.
func bucketize(q *Query, samples []store.Sample, first, end, step int64) map[int64]float64 {
	out := map[int64]float64{}
	switch q.Fn {
	case "rate", "increase":
		inc := map[int64]float64{}
		for i := 1; i < len(samples); i++ {
			d := samples[i].V - samples[i-1].V
			if d < 0 { // counter reset: the counter restarted from zero
				d = samples[i].V
			}
			inc[floorDiv(samples[i].T, step)*step] += d
		}
		for b, v := range inc {
			if b < first || b > end || b+step-1 > end {
				continue
			}
			if q.Fn == "rate" {
				v /= float64(step) / 1000
			}
			out[b] = v
		}
		return out
	}
	buckets := map[int64][]float64{}
	for _, s := range samples {
		b := floorDiv(s.T, step) * step
		if b < first || b > end || (extensive(q.Fn) && b+step-1 > end) {
			continue
		}
		buckets[b] = append(buckets[b], s.V)
	}
	for b, vs := range buckets {
		switch {
		case q.Quantile > 0:
			out[b] = quantile(q.Quantile, vs)
		case q.Fn == "last":
			out[b] = vs[len(vs)-1] // samples are time-ordered
		default:
			out[b] = aggregate(q.Fn, vs)
		}
	}
	return out
}

func aggregate(fn string, vs []float64) float64 {
	switch fn {
	case "count":
		return float64(len(vs))
	case "min":
		m := math.Inf(1)
		for _, v := range vs {
			m = math.Min(m, v)
		}
		return m
	case "max":
		m := math.Inf(-1)
		for _, v := range vs {
			m = math.Max(m, v)
		}
		return m
	}
	sum := 0.0
	for _, v := range vs {
		sum += v
	}
	if fn == "avg" {
		return sum / float64(len(vs))
	}
	return sum
}

// quantile uses linear interpolation between closest ranks.
func quantile(phi float64, vs []float64) float64 {
	s := append([]float64(nil), vs...)
	sort.Float64s(s)
	if len(s) == 1 {
		return s[0]
	}
	rank := phi * float64(len(s)-1)
	lo := int(math.Floor(rank))
	hi := int(math.Ceil(rank))
	return s[lo] + (s[hi]-s[lo])*(rank-float64(lo))
}

// Describe renders a short human summary of how q will be evaluated.
func (q *Query) Describe() string {
	var parts []string
	if q.Agg != "" {
		parts = append(parts, q.Agg+" across series")
		if len(q.By) > 0 {
			parts = append(parts, "grouped by "+strings.Join(q.By, ","))
		}
	}
	if q.Fn != "" {
		parts = append(parts, q.Fn+" per series")
	} else {
		parts = append(parts, "raw samples")
	}
	return strings.Join(parts, ", ")
}
