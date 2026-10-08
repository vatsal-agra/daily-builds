// Package query implements Tide's query language:
//
//	[agg(] fn(selector) [)] [by (l1, l2)] [range D] [step D] [at T]
//
// e.g.  sum(rate(http_requests_total{job="api",code=~"5.."})) by (instance) range 1h step 1m
//
// A bare selector (cpu{host="a"}) returns raw samples. See the README for the
// full reference.
package query

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"tide/internal/store"
)

var seriesFns = map[string]bool{"avg": true, "min": true, "max": true, "sum": true, "count": true,
	"last": true, "rate": true, "increase": true}
var aggFns = map[string]bool{"sum": true, "avg": true, "min": true, "max": true, "count": true}

// Query is a parsed expression.
type Query struct {
	Agg      string // "" when no cross-series aggregation
	Fn       string // "" = raw samples; else series function; "pNN" = percentile
	Quantile float64
	Matchers []*store.Matcher
	By       []string
	HasBy    bool
	Range    time.Duration
	Step     time.Duration // 0 = auto (or raw when Fn == "")
	AtLatest bool          // evaluate at newest stored sample
	AtMs     int64         // explicit end (ms), valid if HasAt
	HasAt    bool
	AtOffset time.Duration // for "now-30m" / "latest-5m"
	AtRelNow bool
	Source   string
}

type tokKind int

const (
	tEOF tokKind = iota
	tWord
	tString
	tPunct
)

type token struct {
	kind tokKind
	text string
	pos  int
}

type ParseError struct {
	Pos int
	Msg string
}

func (e *ParseError) Error() string { return fmt.Sprintf("parse error at %d: %s", e.Pos, e.Msg) }

func lex(src string) ([]token, error) {
	var toks []token
	i := 0
	for i < len(src) {
		c := src[i]
		switch {
		case c == ' ' || c == '\t' || c == '\n' || c == '\r':
			i++
		case c == '"' || c == '`':
			j := i + 1
			for j < len(src) && src[j] != c {
				if c == '"' && src[j] == '\\' {
					j++
				}
				j++
			}
			if j >= len(src) {
				return nil, &ParseError{i, "unterminated string"}
			}
			lit := src[i : j+1]
			s, err := strconv.Unquote(lit)
			if err != nil {
				return nil, &ParseError{i, "bad string literal"}
			}
			toks = append(toks, token{tString, s, i})
			i = j + 1
		case c == '=' || c == '!':
			// = != =~ !~
			if i+1 < len(src) && (src[i+1] == '=' || src[i+1] == '~') && !(c == '=' && src[i+1] == '=') {
				toks = append(toks, token{tPunct, src[i : i+2], i})
				i += 2
			} else if c == '=' {
				toks = append(toks, token{tPunct, "=", i})
				i++
			} else {
				return nil, &ParseError{i, "unexpected '!'"}
			}
		case strings.IndexByte("(){},[]", c) >= 0:
			toks = append(toks, token{tPunct, string(c), i})
			i++
		default:
			j := i
			for j < len(src) && strings.IndexByte(" \t\n\r(){},=!~\"`[]", src[j]) < 0 {
				j++
			}
			if j == i {
				return nil, &ParseError{i, fmt.Sprintf("unexpected %q", c)}
			}
			toks = append(toks, token{tWord, src[i:j], i})
			i = j
		}
	}
	toks = append(toks, token{tEOF, "", len(src)})
	return toks, nil
}

type parser struct {
	toks []token
	i    int
}

func (p *parser) peek() token { return p.toks[p.i] }
func (p *parser) next() token { t := p.toks[p.i]; p.i++; return t }
func (p *parser) errf(t token, f string, a ...any) error {
	return &ParseError{t.pos, fmt.Sprintf(f, a...)}
}
func (p *parser) punct(s string) error {
	t := p.next()
	if t.kind != tPunct || t.text != s {
		return p.errf(t, "expected %q, found %s", s, describe(t))
	}
	return nil
}
func describe(t token) string {
	if t.kind == tEOF {
		return "end of query"
	}
	return fmt.Sprintf("%q", t.text)
}
func (p *parser) isPunct(s string) bool {
	t := p.peek()
	return t.kind == tPunct && t.text == s
}

// Parse parses a query string.
func Parse(src string) (*Query, error) {
	toks, err := lex(src)
	if err != nil {
		return nil, err
	}
	p := &parser{toks: toks}
	q := &Query{Source: src, Range: time.Hour}
	if p.peek().kind == tEOF {
		return nil, &ParseError{0, "empty query"}
	}
	// optional aggregation wrapper: agg( fn( ... ) )
	t := p.peek()
	if t.kind == tWord && aggFns[t.text] && p.toks[p.i+1].text == "(" && p.toks[p.i+1].kind == tPunct && p.isInnerCall() {
		q.Agg = p.next().text
		p.next() // (
		if err := p.parseCall(q); err != nil {
			return nil, err
		}
		if q.Fn == "" {
			return nil, p.errf(t, "%s() needs a function inside, e.g. %s(avg(metric)) — use avg/last/rate/...", q.Agg, q.Agg)
		}
		if err := p.punct(")"); err != nil {
			return nil, err
		}
	} else {
		if err := p.parseCall(q); err != nil {
			return nil, err
		}
	}
	// trailing clauses
	seen := map[string]bool{}
	for p.peek().kind != tEOF {
		t := p.next()
		if t.kind != tWord {
			return nil, p.errf(t, "unexpected %s", describe(t))
		}
		kw := strings.ToLower(t.text)
		if seen[kw] {
			return nil, p.errf(t, "duplicate %q clause", kw)
		}
		seen[kw] = true
		switch kw {
		case "by":
			if q.Agg == "" {
				return nil, p.errf(t, "'by' requires an aggregation like sum(...)")
			}
			if err := p.parseBy(q); err != nil {
				return nil, err
			}
		case "range":
			d, err := p.duration()
			if err != nil {
				return nil, err
			}
			q.Range = d
		case "step":
			d, err := p.duration()
			if err != nil {
				return nil, err
			}
			q.Step = d
		case "at":
			if err := p.parseAt(q); err != nil {
				return nil, err
			}
		default:
			return nil, p.errf(t, "unknown clause %q (expected by, range, step, at)", t.text)
		}
	}
	if q.Fn == "" && q.Step != 0 {
		return nil, &ParseError{0, "step needs a function, e.g. avg(metric) step 1m"}
	}
	if q.Range <= 0 {
		return nil, &ParseError{0, "range must be positive"}
	}
	return q, nil
}

// isInnerCall reports whether "agg (" is followed by "fn (" (so agg is a wrapper
// and not itself the series function, e.g. sum(cpu) vs sum(avg(cpu))).
func (p *parser) isInnerCall() bool {
	if p.i+3 >= len(p.toks) {
		return false
	}
	a, b := p.toks[p.i+2], p.toks[p.i+3]
	return a.kind == tWord && b.kind == tPunct && b.text == "(" && isFn(a.text)
}

func isFn(s string) bool {
	if seriesFns[s] {
		return true
	}
	_, ok := percentile(s)
	return ok
}

func percentile(s string) (float64, bool) {
	if len(s) < 2 || s[0] != 'p' {
		return 0, false
	}
	n, err := strconv.Atoi(s[1:])
	if err != nil || n < 1 || n > 99 {
		return 0, false
	}
	return float64(n) / 100, true
}

func (p *parser) parseCall(q *Query) error {
	t := p.peek()
	if t.kind == tWord && isFn(t.text) && p.toks[p.i+1].kind == tPunct && p.toks[p.i+1].text == "(" {
		p.next()
		p.next()
		q.Fn = t.text
		if f, ok := percentile(t.text); ok {
			q.Quantile = f
		}
		if err := p.parseSelector(q); err != nil {
			return err
		}
		return p.punct(")")
	}
	return p.parseSelector(q)
}

func (p *parser) parseSelector(q *Query) error {
	t := p.peek()
	if t.kind == tWord {
		p.next()
		m, err := store.NewMatcher(store.MatchEq, store.NameLabel, t.text)
		if err != nil {
			return p.errf(t, "%v", err)
		}
		q.Matchers = append(q.Matchers, m)
	} else if !p.isPunct("{") {
		return p.errf(t, "expected metric name or '{', found %s", describe(t))
	}
	if p.isPunct("{") {
		p.next()
		for !p.isPunct("}") {
			nt := p.next()
			if nt.kind != tWord {
				return p.errf(nt, "expected label name, found %s", describe(nt))
			}
			op := p.next()
			var mt store.MatchType
			switch {
			case op.kind == tPunct && op.text == "=":
				mt = store.MatchEq
			case op.kind == tPunct && op.text == "!=":
				mt = store.MatchNe
			case op.kind == tPunct && op.text == "=~":
				mt = store.MatchRe
			case op.kind == tPunct && op.text == "!~":
				mt = store.MatchNre
			default:
				return p.errf(op, "expected one of = != =~ !~, found %s", describe(op))
			}
			vt := p.next()
			if vt.kind != tString {
				return p.errf(vt, "label value must be a quoted string, found %s", describe(vt))
			}
			m, err := store.NewMatcher(mt, nt.text, vt.text)
			if err != nil {
				return p.errf(vt, "%v", err)
			}
			q.Matchers = append(q.Matchers, m)
			if p.isPunct(",") {
				p.next()
			} else if !p.isPunct("}") {
				return p.errf(p.peek(), "expected ',' or '}', found %s", describe(p.peek()))
			}
		}
		p.next()
	}
	if len(q.Matchers) == 0 {
		return p.errf(t, "empty selector")
	}
	return nil
}

func (p *parser) parseBy(q *Query) error {
	q.HasBy = true
	if err := p.punct("("); err != nil {
		return err
	}
	for !p.isPunct(")") {
		t := p.next()
		if t.kind != tWord {
			return p.errf(t, "expected label name, found %s", describe(t))
		}
		q.By = append(q.By, t.text)
		if p.isPunct(",") {
			p.next()
		} else if !p.isPunct(")") {
			return p.errf(p.peek(), "expected ',' or ')'")
		}
	}
	p.next()
	return nil
}

func (p *parser) duration() (time.Duration, error) {
	t := p.next()
	if t.kind != tWord {
		return 0, p.errf(t, "expected duration like 5m, found %s", describe(t))
	}
	d, err := ParseDuration(t.text)
	if err != nil {
		return 0, p.errf(t, "%v", err)
	}
	return d, nil
}

func (p *parser) parseAt(q *Query) error {
	t := p.next()
	if t.kind != tWord {
		return p.errf(t, "expected time after 'at'")
	}
	w := t.text
	for _, base := range []string{"now", "latest"} {
		if strings.HasPrefix(w, base) {
			rest := w[len(base):]
			var off time.Duration
			if rest != "" {
				if rest[0] != '-' && rest[0] != '+' {
					break
				}
				d, err := ParseDuration(rest[1:])
				if err != nil {
					return p.errf(t, "%v", err)
				}
				off = d
				if rest[0] == '-' {
					off = -d
				}
			}
			q.AtOffset = off
			q.AtLatest = base == "latest"
			q.AtRelNow = base == "now"
			q.HasAt = false
			return nil
		}
	}
	if n, err := strconv.ParseInt(w, 10, 64); err == nil {
		if n < 1e11 { // seconds
			n *= 1000
		}
		q.AtMs, q.HasAt = n, true
		return nil
	}
	if tm, err := time.Parse(time.RFC3339, w); err == nil {
		q.AtMs, q.HasAt = tm.UnixMilli(), true
		return nil
	}
	return p.errf(t, "cannot parse time %q (use now, latest, now-30m, unix seconds/ms, or RFC3339)", w)
}

// ParseDuration parses "90s", "5m", "1h30m", "2d", "1w", "250ms".
func ParseDuration(s string) (time.Duration, error) {
	if s == "" {
		return 0, fmt.Errorf("empty duration")
	}
	var total time.Duration
	rest := s
	for rest != "" {
		i := 0
		for i < len(rest) && rest[i] >= '0' && rest[i] <= '9' {
			i++
		}
		if i == 0 {
			return 0, fmt.Errorf("bad duration %q", s)
		}
		n, err := strconv.ParseInt(rest[:i], 10, 64)
		if err != nil {
			return 0, fmt.Errorf("bad duration %q", s)
		}
		rest = rest[i:]
		var unit time.Duration
		switch {
		case strings.HasPrefix(rest, "ms"):
			unit, rest = time.Millisecond, rest[2:]
		case strings.HasPrefix(rest, "s"):
			unit, rest = time.Second, rest[1:]
		case strings.HasPrefix(rest, "m"):
			unit, rest = time.Minute, rest[1:]
		case strings.HasPrefix(rest, "h"):
			unit, rest = time.Hour, rest[1:]
		case strings.HasPrefix(rest, "d"):
			unit, rest = 24*time.Hour, rest[1:]
		case strings.HasPrefix(rest, "w"):
			unit, rest = 7*24*time.Hour, rest[1:]
		default:
			return 0, fmt.Errorf("bad duration %q (missing unit ms/s/m/h/d/w)", s)
		}
		if n > int64(1<<62)/int64(unit) {
			return 0, fmt.Errorf("duration %q too large", s)
		}
		total += time.Duration(n) * unit
	}
	return total, nil
}
