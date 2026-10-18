// Package mf implements the Mortisefile language: variables, functions,
// pattern rules and recipes.
package mf

import (
	"fmt"
	"os/exec"
	"path"
	"sort"
	"strings"
)

// Env is the evaluation context for $(...) expansion.
type Env struct {
	Vars map[string]string
	// Autos holds automatic variables ($@ $< $^ $* $+). When nil, automatic
	// variables are left untouched in the output (first, "parse-time" pass).
	Autos map[string]string
	// Final converts "$$" to "$". It is false during the parse-time pass so
	// that the run-time pass still sees the escape.
	Final bool
	// Glob resolves a glob pattern relative to the project root.
	Glob func(pattern string) ([]string, error)
	// Dir is the working directory for $(shell ...).
	Dir string
	// depth guards runaway self-referential variables.
	depth int
}

// Expand expands all variable references and function calls in s.
func (e *Env) Expand(s string) (string, error) {
	if !strings.Contains(s, "$") {
		return s, nil
	}
	if e.depth > 50 {
		return "", fmt.Errorf("variable expansion too deep (recursive definition?)")
	}
	e.depth++
	defer func() { e.depth-- }()

	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c != '$' {
			b.WriteByte(c)
			continue
		}
		if i+1 >= len(s) {
			return "", fmt.Errorf("dangling '$' at end of %q", s)
		}
		n := s[i+1]
		switch {
		case n == '$':
			if e.Final {
				b.WriteByte('$')
			} else {
				b.WriteString("$$")
			}
			i++
		case n == '(' || n == '{':
			closer := byte(')')
			if n == '{' {
				closer = '}'
			}
			end, err := matchClose(s, i+1, n, closer)
			if err != nil {
				return "", err
			}
			inner := s[i+2 : end]
			out, err := e.expandRef(inner, s[i:end+1])
			if err != nil {
				return "", err
			}
			b.WriteString(out)
			i = end
		case strings.IndexByte("@<^*+", n) >= 0:
			if e.Autos == nil {
				b.WriteByte('$')
				b.WriteByte(n)
			} else {
				b.WriteString(e.Autos[string(n)])
			}
			i++
		default:
			// single-character variable like $X
			v, ok := e.Vars[string(n)]
			if !ok {
				return "", fmt.Errorf("undefined variable $%c", n)
			}
			out, err := e.Expand(v)
			if err != nil {
				return "", err
			}
			b.WriteString(out)
			i++
		}
	}
	return b.String(), nil
}

func matchClose(s string, open int, o, c byte) (int, error) {
	depth := 0
	for j := open; j < len(s); j++ {
		switch s[j] {
		case o:
			depth++
		case c:
			depth--
			if depth == 0 {
				return j, nil
			}
		}
	}
	return 0, fmt.Errorf("unterminated %q (missing %q)", s[open-1:], string(c))
}

func (e *Env) expandRef(inner, whole string) (string, error) {
	// automatic variable with D/F modifier: $(@D) $(<F) ...
	if len(inner) == 2 && strings.IndexByte("@<^*+", inner[0]) >= 0 && (inner[1] == 'D' || inner[1] == 'F') {
		if e.Autos == nil {
			return whole, nil
		}
		fields := strings.Fields(e.Autos[string(inner[0])])
		for i, f := range fields {
			if inner[1] == 'D' {
				fields[i] = path.Dir(f)
			} else {
				fields[i] = path.Base(f)
			}
		}
		return strings.Join(fields, " "), nil
	}
	// function call: first word is a known function followed by whitespace
	if sp := strings.IndexAny(inner, " \t"); sp > 0 {
		name := inner[:sp]
		if fn, ok := funcs[name]; ok {
			args := splitArgs(strings.TrimLeft(inner[sp:], " \t"))
			if fn.nargs >= 0 && len(args) != fn.nargs {
				return "", fmt.Errorf("$(%s) takes %d argument(s), got %d", name, fn.nargs, len(args))
			}
			exp := make([]string, len(args))
			for i, a := range args {
				x, err := e.Expand(a)
				if err != nil {
					return "", err
				}
				exp[i] = x
			}
			return fn.f(e, exp)
		}
	}
	// substitution reference $(VAR:a=b)
	if colon := strings.IndexByte(inner, ':'); colon > 0 {
		if eq := strings.IndexByte(inner[colon:], '='); eq > 0 {
			name := inner[:colon]
			if v, ok := e.Vars[name]; ok {
				val, err := e.Expand(v)
				if err != nil {
					return "", err
				}
				from, to := inner[colon+1:colon+eq], inner[colon+eq+1:]
				from, err = e.Expand(from)
				if err != nil {
					return "", err
				}
				to, err = e.Expand(to)
				if err != nil {
					return "", err
				}
				return patsubst(from, to, val), nil
			}
		}
	}
	name := strings.TrimSpace(inner)
	v, ok := e.Vars[name]
	if !ok {
		return "", fmt.Errorf("undefined variable %q", name)
	}
	return e.Expand(v)
}

// splitArgs splits on top-level commas (respecting nested $(...)/${...}).
func splitArgs(s string) []string {
	var out []string
	depth, start := 0, 0
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case '(', '{':
			depth++
		case ')', '}':
			depth--
		case ',':
			if depth == 0 {
				out = append(out, s[start:i])
				start = i + 1
			}
		}
	}
	return append(out, s[start:])
}

type fn struct {
	nargs int // -1 = variadic (>=1)
	f     func(e *Env, a []string) (string, error)
}

func words(s string) []string { return strings.Fields(s) }

func mapWords(s string, f func(string) string) string {
	w := words(s)
	for i := range w {
		w[i] = f(w[i])
	}
	return strings.Join(w, " ")
}

// patsubst replaces the % pattern `from` with `to` in every word of s.
func patsubst(from, to, s string) string {
	return mapWords(s, func(w string) string {
		if i := strings.IndexByte(from, '%'); i >= 0 {
			pre, suf := from[:i], from[i+1:]
			if len(w) >= len(pre)+len(suf) && strings.HasPrefix(w, pre) && strings.HasSuffix(w, suf) {
				stem := w[len(pre) : len(w)-len(suf)]
				return strings.Replace(to, "%", stem, 1)
			}
			return w
		}
		if w == from {
			return to
		}
		// plain suffix form: $(X:.c=.o)
		if strings.HasSuffix(w, from) {
			return w[:len(w)-len(from)] + to
		}
		return w
	})
}

var funcs map[string]fn

func init() {
	funcs = map[string]fn{
		"glob": {1, func(e *Env, a []string) (string, error) {
			if e.Glob == nil {
				return "", fmt.Errorf("glob is unavailable here")
			}
			var all []string
			for _, p := range words(a[0]) {
				m, err := e.Glob(p)
				if err != nil {
					return "", err
				}
				all = append(all, m...)
			}
			return strings.Join(all, " "), nil
		}},
		"patsubst": {3, func(e *Env, a []string) (string, error) {
			return patsubst(strings.TrimSpace(a[0]), strings.TrimSpace(a[1]), a[2]), nil
		}},
		"subst": {3, func(e *Env, a []string) (string, error) {
			return strings.ReplaceAll(a[2], a[0], a[1]), nil
		}},
		"dir": {1, func(e *Env, a []string) (string, error) {
			return mapWords(a[0], func(w string) string { return path.Dir(w) }), nil
		}},
		"notdir": {1, func(e *Env, a []string) (string, error) {
			return mapWords(a[0], path.Base), nil
		}},
		"basename": {1, func(e *Env, a []string) (string, error) {
			return mapWords(a[0], func(w string) string { return strings.TrimSuffix(w, path.Ext(w)) }), nil
		}},
		"suffix": {1, func(e *Env, a []string) (string, error) {
			return mapWords(a[0], path.Ext), nil
		}},
		"addprefix": {2, func(e *Env, a []string) (string, error) {
			return mapWords(a[1], func(w string) string { return a[0] + w }), nil
		}},
		"addsuffix": {2, func(e *Env, a []string) (string, error) {
			return mapWords(a[1], func(w string) string { return w + a[0] }), nil
		}},
		"filter": {2, func(e *Env, a []string) (string, error) {
			return filter(a[0], a[1], true), nil
		}},
		"filter-out": {2, func(e *Env, a []string) (string, error) {
			return filter(a[0], a[1], false), nil
		}},
		"sort": {1, func(e *Env, a []string) (string, error) {
			w := words(a[0])
			sort.Strings(w)
			out := w[:0]
			for i, x := range w {
				if i == 0 || x != w[i-1] {
					out = append(out, x)
				}
			}
			return strings.Join(out, " "), nil
		}},
		"strip": {1, func(e *Env, a []string) (string, error) {
			return strings.Join(words(a[0]), " "), nil
		}},
		"words": {1, func(e *Env, a []string) (string, error) {
			return fmt.Sprint(len(words(a[0]))), nil
		}},
		"firstword": {1, func(e *Env, a []string) (string, error) {
			if w := words(a[0]); len(w) > 0 {
				return w[0], nil
			}
			return "", nil
		}},
		"if": {3, func(e *Env, a []string) (string, error) {
			if strings.TrimSpace(a[0]) != "" {
				return a[1], nil
			}
			return a[2], nil
		}},
		"shell": {1, func(e *Env, a []string) (string, error) {
			cmd := exec.Command("sh", "-c", strings.ReplaceAll(a[0], "$$", "$"))
			cmd.Dir = e.Dir
			out, err := cmd.Output()
			if err != nil {
				return "", fmt.Errorf("$(shell %s): %v", a[0], err)
			}
			// Escape '$' so the output is not re-expanded as variable references.
			return strings.ReplaceAll(strings.Join(strings.Fields(string(out)), " "), "$", "$$"), nil
		}},
	}
}

func filter(patterns, list string, keep bool) string {
	pats := words(patterns)
	var out []string
	for _, w := range words(list) {
		m := false
		for _, p := range pats {
			if matchPct(p, w) {
				m = true
				break
			}
		}
		if m == keep {
			out = append(out, w)
		}
	}
	return strings.Join(out, " ")
}

// matchPct reports whether w matches p, where p may contain one '%'.
func matchPct(p, w string) bool {
	_, ok := MatchStem(p, w)
	return ok
}

// MatchStem matches w against a pattern with at most one '%' and returns the
// stem. A pattern without '%' matches only itself (empty stem).
func MatchStem(pattern, w string) (string, bool) {
	i := strings.IndexByte(pattern, '%')
	if i < 0 {
		return "", pattern == w
	}
	pre, suf := pattern[:i], pattern[i+1:]
	if len(w) < len(pre)+len(suf) || !strings.HasPrefix(w, pre) || !strings.HasSuffix(w, suf) {
		return "", false
	}
	stem := w[len(pre) : len(w)-len(suf)]
	if stem == "" {
		return "", false
	}
	return stem, true
}
