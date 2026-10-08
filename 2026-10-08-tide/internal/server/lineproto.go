package server

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"tide/internal/store"
)

// ParseLines parses the text ingest format, one sample per line:
//
//	metric{label="value",other="x"} 12.5 1700000000000
//	metric 3
//
// The timestamp is optional (defaults to now). Integers below 1e11 are taken
// as seconds, otherwise milliseconds. '#' starts a comment line. Lines that
// fail to parse are reported but do not stop the others.
func ParseLines(body string, now time.Time) (pts []store.Point, errs []string) {
	for i, line := range strings.Split(body, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || line[0] == '#' {
			continue
		}
		p, err := parseLine(line, now)
		if err != nil {
			errs = append(errs, fmt.Sprintf("line %d: %v", i+1, err))
			continue
		}
		pts = append(pts, p)
	}
	return
}

func parseLine(line string, now time.Time) (store.Point, error) {
	var p store.Point
	m := map[string]string{}
	i := 0
	for i < len(line) && line[i] != '{' && line[i] != ' ' && line[i] != '\t' {
		i++
	}
	if i == 0 {
		return p, fmt.Errorf("missing metric name")
	}
	m[store.NameLabel] = line[:i]
	if i < len(line) && line[i] == '{' {
		i++
		for {
			for i < len(line) && line[i] == ' ' {
				i++
			}
			if i >= len(line) {
				return p, fmt.Errorf("unterminated label set")
			}
			if line[i] == '}' {
				i++
				break
			}
			j := i
			for j < len(line) && line[j] != '=' && line[j] != '}' {
				j++
			}
			if j >= len(line) || line[j] != '=' {
				return p, fmt.Errorf("label without '='")
			}
			name := strings.TrimSpace(line[i:j])
			j++
			if j >= len(line) || line[j] != '"' {
				return p, fmt.Errorf("label %q value must be a quoted string", name)
			}
			k := j + 1
			for k < len(line) && line[k] != '"' {
				if line[k] == '\\' {
					k++
				}
				k++
			}
			if k >= len(line) {
				return p, fmt.Errorf("unterminated label value")
			}
			val, err := strconv.Unquote(line[j : k+1])
			if err != nil {
				return p, fmt.Errorf("bad label value %s", line[j:k+1])
			}
			if _, dup := m[name]; dup {
				return p, fmt.Errorf("duplicate label %q", name)
			}
			m[name] = val
			i = k + 1
			for i < len(line) && line[i] == ' ' {
				i++
			}
			if i < len(line) && line[i] == ',' {
				i++
			}
		}
	}
	fields := strings.Fields(line[i:])
	if len(fields) < 1 || len(fields) > 2 {
		return p, fmt.Errorf("expected 'value [timestamp]' after labels")
	}
	v, err := strconv.ParseFloat(fields[0], 64)
	if err != nil {
		return p, fmt.Errorf("bad value %q", fields[0])
	}
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return p, fmt.Errorf("non-finite value %q", fields[0])
	}
	ts := now.UnixMilli()
	if len(fields) == 2 {
		n, err := strconv.ParseInt(fields[1], 10, 64)
		if err != nil {
			return p, fmt.Errorf("bad timestamp %q", fields[1])
		}
		if n >= 0 && n < 1e11 {
			n *= 1000
		}
		ts = n
	}
	ls := store.NewLabels(m)
	if err := ls.Validate(); err != nil {
		return p, err
	}
	return store.Point{Labels: ls, T: ts, V: v}, nil
}
