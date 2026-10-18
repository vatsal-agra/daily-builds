package mf

import (
	"fmt"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Cmd is one recipe command.
type Cmd struct {
	Text      string // variables expanded; automatic variables not yet
	IgnoreErr bool   // leading '-'
	Line      int
}

// Rule is one parsed rule. Targets containing '%' make it a pattern rule.
type Rule struct {
	Targets []string
	Grouped bool // "a b &: deps": one command run produces all targets
	Deps    []string
	Cmds    []Cmd
	Depfile string // "@depfile path" (may use automatic variables)
	Desc    string // "@desc text"
	Phony   bool
	Line    int
}

// IsPattern reports whether the rule is a %-pattern rule.
func (r *Rule) IsPattern() bool { return strings.Contains(r.Targets[0], "%") }

// File is a parsed Mortisefile.
type File struct {
	Name    string
	Rules   []*Rule
	Default []string
	Vars    map[string]string
	Phony   map[string]bool
}

// Error is a positioned parse error.
type Error struct {
	File string
	Line int
	Msg  string
}

func (e *Error) Error() string { return fmt.Sprintf("%s:%d: %s", e.File, e.Line, e.Msg) }

var assignRe = regexp.MustCompile(`^([A-Za-z_][A-Za-z0-9_.\-]*)\s*(:=|\+=|\?=|=)\s*(.*)$`)

// ParseFile reads and parses the Mortisefile at name; root is the project
// directory used for globbing and $(shell).
func ParseFile(name, root string) (*File, error) {
	data, err := os.ReadFile(name)
	if err != nil {
		return nil, err
	}
	return Parse(name, string(data), root)
}

// Parse parses Mortisefile source text.
func Parse(name, src, root string) (*File, error) {
	f := &File{Name: name, Vars: map[string]string{}, Phony: map[string]bool{}}
	// builtin variables
	f.Vars["MORTISE"] = "mortise"

	lines := joinContinuations(src)
	env := &Env{Vars: f.Vars, Final: true, Dir: root,
		Glob: func(p string) ([]string, error) { return Glob(root, p) }}
	penv := &Env{Vars: f.Vars, Final: false, Dir: root, Glob: env.Glob}

	var cur *Rule
	fail := func(line int, format string, a ...any) error {
		return &Error{File: name, Line: line, Msg: fmt.Sprintf(format, a...)}
	}

	for _, ln := range lines {
		raw := ln.text
		trim := strings.TrimSpace(raw)
		if trim == "" {
			continue
		}
		indented := raw[0] == ' ' || raw[0] == '\t'
		if strings.HasPrefix(trim, "#") {
			continue
		}
		if !indented { // recipe lines go to the shell verbatim, '#' included
			trim = stripComment(trim)
			if trim == "" {
				continue
			}
		}
		if indented {
			if cur == nil {
				return nil, fail(ln.n, "recipe line outside of a rule: %q", trim)
			}
			if strings.HasPrefix(trim, "@") {
				if err := directive(cur, f, trim, ln.n, penv, name); err != nil {
					return nil, err
				}
				continue
			}
			c := Cmd{Line: ln.n}
			if strings.HasPrefix(trim, "-") {
				c.IgnoreErr = true
				trim = strings.TrimSpace(trim[1:])
			}
			x, err := penv.Expand(trim)
			if err != nil {
				return nil, fail(ln.n, "%v", err)
			}
			c.Text = x
			cur.Cmds = append(cur.Cmds, c)
			continue
		}
		cur = nil

		// assignment?
		if m := assignRe.FindStringSubmatch(trim); m != nil {
			k, op, v := m[1], m[2], m[3]
			// Keep "$$" escapes intact in stored values so recipes still see them.
			ex2, err := penv.Expand(v)
			if err != nil {
				return nil, fail(ln.n, "%v", err)
			}
			switch op {
			case "=", ":=":
				f.Vars[k] = ex2
			case "+=":
				if old, ok := f.Vars[k]; ok && old != "" {
					f.Vars[k] = old + " " + ex2
				} else {
					f.Vars[k] = ex2
				}
			case "?=":
				if _, ok := f.Vars[k]; !ok {
					f.Vars[k] = ex2
				}
			}
			continue
		}

		// keywords
		if w, rest, ok := keyword(trim); ok {
			x, err := env.Expand(rest)
			if err != nil {
				return nil, fail(ln.n, "%v", err)
			}
			switch w {
			case "default":
				f.Default = append(f.Default, strings.Fields(x)...)
			case "phony":
				for _, p := range strings.Fields(x) {
					f.Phony[p] = true
				}
			case "include":
				for _, p := range strings.Fields(x) {
					inc, err := os.ReadFile(filepath.Join(root, p))
					if err != nil {
						return nil, fail(ln.n, "include: %v", err)
					}
					sub, err := Parse(p, string(inc), root)
					if err != nil {
						return nil, err
					}
					for k, v := range sub.Vars {
						f.Vars[k] = v
					}
					f.Rules = append(f.Rules, sub.Rules...)
					f.Default = append(f.Default, sub.Default...)
					for k := range sub.Phony {
						f.Phony[k] = true
					}
				}
			}
			continue
		}

		// rule header
		ci := topLevelColon(trim)
		if ci < 0 {
			return nil, fail(ln.n, "expected a rule (\"targets: deps\"), assignment, or directive; got %q", trim)
		}
		lhs := trim[:ci]
		grouped := false
		if strings.HasSuffix(lhs, "&") {
			grouped = true
			lhs = strings.TrimSuffix(lhs, "&")
		}
		lx, err := env.Expand(lhs)
		if err != nil {
			return nil, fail(ln.n, "%v", err)
		}
		rx, err := env.Expand(trim[ci+1:])
		if err != nil {
			return nil, fail(ln.n, "%v", err)
		}
		targets := strings.Fields(lx)
		if len(targets) == 0 {
			return nil, fail(ln.n, "rule has no targets")
		}
		pat := strings.Contains(targets[0], "%")
		for _, t := range targets {
			if strings.Contains(t, "%") != pat {
				return nil, fail(ln.n, "cannot mix pattern and plain targets in one rule (%q)", t)
			}
			if strings.Count(t, "%") > 1 {
				return nil, fail(ln.n, "pattern %q has more than one '%%'", t)
			}
			if err := checkPath(t); err != nil {
				return nil, fail(ln.n, "%v", err)
			}
		}
		r := &Rule{Targets: targets, Grouped: grouped, Deps: strings.Fields(rx), Line: ln.n}
		if len(targets) > 1 && !grouped {
			return nil, fail(ln.n, "multiple targets need '&:' (grouped outputs) or separate rules")
		}
		for _, d := range r.Deps {
			if d == "|" {
				return nil, fail(ln.n, "order-only dependencies ('|') are not supported")
			}
		}
		f.Rules = append(f.Rules, r)
		cur = r
	}

	for _, r := range f.Rules {
		for _, t := range r.Targets {
			if f.Phony[t] {
				r.Phony = true
			}
		}
		if r.Phony && r.IsPattern() {
			return nil, &Error{File: name, Line: r.Line, Msg: "pattern rules cannot be phony"}
		}
	}
	return f, nil
}

func checkPath(t string) error {
	if strings.HasPrefix(t, "/") || strings.HasPrefix(t, "../") || t == ".." || strings.Contains(t, "/../") {
		return fmt.Errorf("target %q escapes the project root", t)
	}
	return nil
}

func directive(r *Rule, f *File, line string, n int, env *Env, name string) error {
	word, rest, _ := strings.Cut(line, " ")
	rest = strings.TrimSpace(rest)
	switch word {
	case "@depfile":
		if rest == "" {
			return &Error{name, n, "@depfile needs a path"}
		}
		x, err := env.Expand(rest)
		if err != nil {
			return &Error{name, n, err.Error()}
		}
		r.Depfile = x
	case "@desc":
		x, err := env.Expand(rest)
		if err != nil {
			return &Error{name, n, err.Error()}
		}
		r.Desc = x
	case "@phony":
		r.Phony = true
	default:
		return &Error{name, n, fmt.Sprintf("unknown directive %q (known: @depfile @desc @phony)", word)}
	}
	return nil
}

func keyword(s string) (word, rest string, ok bool) {
	for _, k := range []string{"default", "phony", "include"} {
		if s == k {
			return k, "", true
		}
		if strings.HasPrefix(s, k+" ") || strings.HasPrefix(s, k+"\t") {
			// "default: x" style rule named default is not matched here because of the space.
			r := strings.TrimSpace(s[len(k):])
			if strings.HasPrefix(r, ":") {
				return "", "", false
			}
			return k, r, true
		}
	}
	return "", "", false
}

// topLevelColon finds the first ':' that is not inside $( ) / ${ }.
func topLevelColon(s string) int {
	depth := 0
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case '$':
			if i+1 < len(s) && (s[i+1] == '(' || s[i+1] == '{') {
				depth++
				i++
			}
		case ')', '}':
			if depth > 0 {
				depth--
			}
		case ':':
			if depth == 0 {
				return i
			}
		}
	}
	return -1
}

type srcLine struct {
	n    int
	text string
}

// joinContinuations joins lines ending in a backslash.
func joinContinuations(src string) []srcLine {
	src = strings.ReplaceAll(src, "\r\n", "\n")
	raw := strings.Split(src, "\n")
	var out []srcLine
	for i := 0; i < len(raw); i++ {
		start := i + 1
		text := raw[i]
		for strings.HasSuffix(text, "\\") && i+1 < len(raw) {
			i++
			text = strings.TrimRight(strings.TrimSuffix(text, "\\"), " \t") + " " + strings.TrimSpace(raw[i])
		}
		out = append(out, srcLine{start, strings.TrimRight(text, " \t")})
	}
	return out
}

// ExpandRun performs the run-time expansion pass of a stored string with
// automatic variables available.
func ExpandRun(vars map[string]string, autos map[string]string, s string) (string, error) {
	e := &Env{Vars: vars, Autos: autos, Final: true}
	return e.Expand(s)
}

// Glob expands a glob pattern relative to root. Supports *, ?, [...] and
// "**" as a whole path segment (any number of directories). Only regular
// files are returned, sorted, with forward slashes.
func Glob(root, pattern string) ([]string, error) {
	pattern = path.Clean(filepath.ToSlash(pattern))
	if err := checkPath(pattern); err != nil {
		return nil, err
	}
	segs := strings.Split(pattern, "/")
	var out []string
	var walk func(dir string, rel string, segs []string) error
	walk = func(dir, rel string, segs []string) error {
		if len(segs) == 0 {
			return nil
		}
		seg := segs[0]
		entries, err := os.ReadDir(filepath.Join(root, filepath.FromSlash(dir)))
		if err != nil {
			return nil // missing directory: no matches
		}
		if seg == "**" {
			// zero directories
			if err := walk(dir, rel, segs[1:]); err != nil {
				return err
			}
			for _, e := range entries {
				if e.IsDir() && !strings.HasPrefix(e.Name(), ".") {
					if err := walk(join(dir, e.Name()), join(rel, e.Name()), segs); err != nil {
						return err
					}
				}
			}
			return nil
		}
		if _, err := path.Match(seg, "x"); err != nil {
			return fmt.Errorf("bad glob pattern %q: %v", pattern, err)
		}
		for _, e := range entries {
			ok, _ := path.Match(seg, e.Name())
			if !ok || (strings.HasPrefix(e.Name(), ".") && !strings.HasPrefix(seg, ".")) {
				continue
			}
			p := join(dir, e.Name())
			if len(segs) == 1 {
				if e.Type().IsRegular() || e.Type()&os.ModeSymlink != 0 {
					if st, err := os.Stat(filepath.Join(root, filepath.FromSlash(p))); err == nil && st.Mode().IsRegular() {
						out = append(out, p)
					}
				}
			} else if e.IsDir() {
				if err := walk(p, join(rel, e.Name()), segs[1:]); err != nil {
					return err
				}
			}
		}
		return nil
	}
	if err := walk(".", "", segs); err != nil {
		return nil, err
	}
	for i, p := range out {
		out[i] = strings.TrimPrefix(p, "./")
	}
	sort.Strings(out)
	// dedupe (** can reach a file by one path only, but be safe)
	d := out[:0]
	for i, p := range out {
		if i == 0 || p != out[i-1] {
			d = append(d, p)
		}
	}
	return d, nil
}

func join(a, b string) string {
	if a == "." || a == "" {
		return b
	}
	return a + "/" + b
}

// stripComment removes a trailing " # comment" (a '#' at the start of the line
// or after whitespace, outside $( ) / ${ }). "\#" yields a literal '#'.
func stripComment(s string) string {
	if !strings.Contains(s, "#") {
		return s
	}
	var b strings.Builder
	depth := 0
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '\\' && i+1 < len(s) && s[i+1] == '#':
			b.WriteByte('#')
			i++
			continue
		case c == '$' && i+1 < len(s) && (s[i+1] == '(' || s[i+1] == '{'):
			depth++
			b.WriteByte(c)
			b.WriteByte(s[i+1])
			i++
			continue
		case (c == ')' || c == '}') && depth > 0:
			depth--
		case c == '#' && depth == 0 && (i == 0 || s[i-1] == ' ' || s[i-1] == '\t'):
			return strings.TrimRight(b.String(), " \t")
		}
		b.WriteByte(c)
	}
	return b.String()
}
