package store

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// NameLabel is the label holding the metric name.
const NameLabel = "__name__"

type Label struct{ Name, Value string }

// Labels is a set of labels sorted by name.
type Labels []Label

func NewLabels(m map[string]string) Labels {
	ls := make(Labels, 0, len(m))
	for k, v := range m {
		ls = append(ls, Label{k, v})
	}
	sort.Slice(ls, func(i, j int) bool { return ls[i].Name < ls[j].Name })
	return ls
}

func (ls Labels) Get(name string) string {
	for _, l := range ls {
		if l.Name == name {
			return l.Value
		}
	}
	return ""
}

func (ls Labels) Map() map[string]string {
	m := make(map[string]string, len(ls))
	for _, l := range ls {
		m[l.Name] = l.Value
	}
	return m
}

// Key is a canonical identity string for the label set.
func (ls Labels) Key() string {
	var b strings.Builder
	for _, l := range ls {
		b.WriteString(l.Name)
		b.WriteByte(0xff)
		b.WriteString(l.Value)
		b.WriteByte(0xfe)
	}
	return b.String()
}

// String renders like  name{a="b",c="d"}.
func (ls Labels) String() string {
	var b strings.Builder
	b.WriteString(ls.Get(NameLabel))
	first := true
	for _, l := range ls {
		if l.Name == NameLabel {
			continue
		}
		if first {
			b.WriteByte('{')
			first = false
		} else {
			b.WriteByte(',')
		}
		fmt.Fprintf(&b, "%s=%q", l.Name, l.Value)
	}
	if !first {
		b.WriteByte('}')
	}
	return b.String()
}

var labelNameRE = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$`)

// Validate checks names are legal, unique, and a metric name is present.
func (ls Labels) Validate() error {
	if ls.Get(NameLabel) == "" {
		return fmt.Errorf("missing metric name")
	}
	for i, l := range ls {
		if !labelNameRE.MatchString(l.Name) {
			return fmt.Errorf("invalid label name %q", l.Name)
		}
		if i > 0 && ls[i-1].Name == l.Name {
			return fmt.Errorf("duplicate label %q", l.Name)
		}
	}
	return nil
}

type MatchType int

const (
	MatchEq MatchType = iota
	MatchNe
	MatchRe
	MatchNre
)

func (m MatchType) String() string { return [...]string{"=", "!=", "=~", "!~"}[m] }

// Matcher selects series by one label. A missing label counts as "".
type Matcher struct {
	Type  MatchType
	Name  string
	Value string
	re    *regexp.Regexp
}

func NewMatcher(t MatchType, name, value string) (*Matcher, error) {
	m := &Matcher{Type: t, Name: name, Value: value}
	if t == MatchRe || t == MatchNre {
		re, err := regexp.Compile("^(?:" + value + ")$")
		if err != nil {
			return nil, fmt.Errorf("bad regex %q: %v", value, err)
		}
		m.re = re
	}
	return m, nil
}

func (m *Matcher) Matches(v string) bool {
	switch m.Type {
	case MatchEq:
		return v == m.Value
	case MatchNe:
		return v != m.Value
	case MatchRe:
		return m.re.MatchString(v)
	default:
		return !m.re.MatchString(v)
	}
}

func (m *Matcher) String() string { return fmt.Sprintf("%s%s%q", m.Name, m.Type, m.Value) }

func matchAll(ms []*Matcher, ls Labels) bool {
	for _, m := range ms {
		if !m.Matches(ls.Get(m.Name)) {
			return false
		}
	}
	return true
}
