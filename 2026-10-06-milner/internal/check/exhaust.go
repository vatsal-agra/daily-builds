// Package check performs pattern-match analysis: exhaustiveness (with a concrete witness of a missing
// case) and redundancy, using Maranget's usefulness algorithm ("Warnings for pattern matching", 2007).
package check

import (
	"fmt"
	"sort"
	"strings"

	"milner/internal/syntax"
	"milner/internal/types"
)

type ctor struct {
	name    string
	arity   int      // number of sub-patterns (columns it expands to)
	family  []*ctor  // all constructors of the type; nil when the signature is infinite (ints, strings)
	kind    string   // "con", "tuple", "lit", "bool", "unit"
	payload int      // declared argument count of a data constructor (for display)
	labels  []string // field names of a record constructor (for display)
}

type ipat struct {
	c    *ctor // nil for wildcard / or
	subs []*ipat
	alts []*ipat // non-nil for or-patterns
}

var wild = &ipat{}

func (p *ipat) isWild() bool { return p.c == nil && p.alts == nil }

type row []*ipat

// Checker analyses patterns against a constructor table.
type Checker struct {
	cons   map[string]*types.ConInfo
	fams   map[*types.TypeInfo][]*ctor
	lits   map[string]*ctor
	tuples map[int]*ctor
	unit   *ctor
	bools  [2]*ctor
	budget int
	// Budget bounds the work of one analysis (usefulness checks can be exponential); 0 = default.
	Budget int
	gaveUp bool
	fields []string // union of record field names in the match being analysed (record patterns lower to tuples over it)
}

// New returns a checker for the constructors in cons.
func New(cons map[string]*types.ConInfo) *Checker {
	c := &Checker{cons: cons, fams: map[*types.TypeInfo][]*ctor{}, lits: map[string]*ctor{}, tuples: map[int]*ctor{}}
	c.unit = &ctor{name: "()", kind: "unit"}
	c.unit.family = []*ctor{c.unit}
	c.bools[0] = &ctor{name: "false", kind: "bool"}
	c.bools[1] = &ctor{name: "true", kind: "bool"}
	fam := []*ctor{c.bools[0], c.bools[1]}
	c.bools[0].family, c.bools[1].family = fam, fam
	return c
}

func (c *Checker) tupleCtor(n int) *ctor {
	if t, ok := c.tuples[n]; ok {
		return t
	}
	t := &ctor{name: fmt.Sprintf("tuple%d", n), arity: n, kind: "tuple"}
	t.family = []*ctor{t}
	c.tuples[n] = t
	return t
}

func (c *Checker) recordCtor(labels []string) *ctor {
	key := "{" + strings.Join(labels, ",") + "}"
	if t, ok := c.lits[key]; ok {
		return t
	}
	t := &ctor{name: key, arity: len(labels), kind: "record", labels: labels}
	t.family = []*ctor{t}
	c.lits[key] = t
	return t
}

func (c *Checker) litCtor(key, shown string) *ctor {
	if t, ok := c.lits[key]; ok {
		return t
	}
	t := &ctor{name: shown, kind: "lit"}
	c.lits[key] = t
	return t
}

func (c *Checker) famOf(ti *types.TypeInfo) []*ctor {
	if f, ok := c.fams[ti]; ok {
		return f
	}
	f := make([]*ctor, len(ti.Cons))
	for i, ci := range ti.Cons {
		a := 0
		if ci.Arity > 0 {
			a = 1
		}
		f[i] = &ctor{name: ci.Name, arity: a, kind: "con", payload: ci.Arity}
	}
	for _, x := range f {
		x.family = f
	}
	c.fams[ti] = f
	return f
}

func (c *Checker) conCtor(name string) *ctor {
	ci := c.cons[name]
	return c.famOf(ci.Type)[ci.Index]
}

// lower converts a surface pattern to the analysis form.
func (c *Checker) lower(p syntax.Pat) *ipat {
	switch x := p.(type) {
	case *syntax.PWild, *syntax.PVar:
		return wild
	case *syntax.PAs:
		return c.lower(x.P)
	case *syntax.PAnnot:
		return c.lower(x.P)
	case *syntax.PInt:
		return &ipat{c: c.litCtor(fmt.Sprintf("i%d", x.Val), fmt.Sprint(x.Val))}
	case *syntax.PStr:
		return &ipat{c: c.litCtor(fmt.Sprintf("s%q", x.Val), fmt.Sprintf("%q", x.Val))}
	case *syntax.PBool:
		if x.Val {
			return &ipat{c: c.bools[1]}
		}
		return &ipat{c: c.bools[0]}
	case *syntax.PUnit:
		return &ipat{c: c.unit}
	case *syntax.PTuple:
		subs := make([]*ipat, len(x.Elems))
		for i, e := range x.Elems {
			subs[i] = c.lower(e)
		}
		return &ipat{c: c.tupleCtor(len(subs)), subs: subs}
	case *syntax.PRecord:
		subs := make([]*ipat, len(c.fields))
		for i := range subs {
			subs[i] = wild
		}
		for _, f := range x.Fields {
			for i, n := range c.fields {
				if n == f.Name {
					subs[i] = c.lower(f.Pat)
				}
			}
		}
		return &ipat{c: c.recordCtor(c.fields), subs: subs}
	case *syntax.PCon:
		k := c.conCtor(x.Name)
		if x.Arg == nil {
			return &ipat{c: k}
		}
		return &ipat{c: k, subs: []*ipat{c.lower(x.Arg)}}
	case *syntax.POr:
		return &ipat{alts: []*ipat{c.lower(x.L), c.lower(x.R)}}
	}
	panic(fmt.Sprintf("check: unhandled pattern %T", p))
}

// expandHeads replaces rows whose head is an or-pattern by one row per alternative.
func expandHeads(rows []row) []row {
	var out []row
	for _, r := range rows {
		if len(r) > 0 && r[0].alts != nil {
			var sub []row
			for _, a := range r[0].alts {
				nr := append(row{a}, r[1:]...)
				sub = append(sub, nr)
			}
			out = append(out, expandHeads(sub)...)
		} else {
			out = append(out, r)
		}
	}
	return out
}

func wilds(n int) []*ipat {
	w := make([]*ipat, n)
	for i := range w {
		w[i] = wild
	}
	return w
}

func specialize(k *ctor, rows []row) []row {
	var out []row
	for _, r := range rows {
		h := r[0]
		switch {
		case h.isWild():
			out = append(out, append(append(row{}, wilds(k.arity)...), r[1:]...))
		case h.c == k:
			subs := h.subs
			if len(subs) != k.arity {
				subs = wilds(k.arity)
			}
			out = append(out, append(append(row{}, subs...), r[1:]...))
		}
	}
	return out
}

func defaultRows(rows []row) []row {
	var out []row
	for _, r := range rows {
		if r[0].isWild() {
			out = append(out, r[1:])
		}
	}
	return out
}

func headCtors(rows []row) []*ctor {
	var out []*ctor
	seen := map[*ctor]bool{}
	for _, r := range rows {
		if h := r[0]; h.c != nil && !seen[h.c] {
			seen[h.c] = true
			out = append(out, h.c)
		}
	}
	return out
}

func complete(heads []*ctor) bool {
	if len(heads) == 0 {
		return false
	}
	fam := heads[0].family
	if fam == nil {
		return false
	}
	return len(heads) == len(fam)
}

const budgetLimit = 3_000_000

func (c *Checker) tick() {
	c.budget++
	limit := c.Budget
	if limit == 0 {
		limit = budgetLimit
	}
	if c.budget > limit {
		c.gaveUp = true
		panic(giveUp{})
	}
}

type giveUp struct{}

// useful reports whether vector q matches some value that no row of rows matches.
func (c *Checker) useful(rows []row, q row) bool {
	c.tick()
	if len(q) == 0 {
		return len(rows) == 0
	}
	if q[0].alts != nil {
		for _, a := range q[0].alts {
			if c.useful(rows, append(row{a}, q[1:]...)) {
				return true
			}
		}
		return false
	}
	rows = expandHeads(rows)
	if k := q[0].c; k != nil {
		subs := q[0].subs
		if len(subs) != k.arity {
			subs = wilds(k.arity)
		}
		return c.useful(specialize(k, rows), append(append(row{}, subs...), q[1:]...))
	}
	heads := headCtors(rows)
	if complete(heads) {
		for _, k := range heads[0].family {
			if c.useful(specialize(k, rows), append(wilds(k.arity), q[1:]...)) {
				return true
			}
		}
		return false
	}
	return c.useful(defaultRows(rows), q[1:])
}

// witness returns a vector of n patterns (as display trees) matching a value no row matches, or nil.
func (c *Checker) witness(rows []row, n int) []*wit {
	c.tick()
	if n == 0 {
		if len(rows) == 0 {
			return []*wit{}
		}
		return nil
	}
	rows = expandHeads(rows)
	heads := headCtors(rows)
	if complete(heads) {
		for _, k := range heads[0].family {
			r := c.witness(specialize(k, rows), k.arity+n-1)
			if r != nil {
				w := &wit{c: k, subs: r[:k.arity]}
				return append([]*wit{w}, r[k.arity:]...)
			}
		}
		return nil
	}
	r := c.witness(defaultRows(rows), n-1)
	if r == nil {
		return nil
	}
	head := &wit{}
	if len(heads) > 0 && heads[0].family != nil {
		// pick a constructor of the signature that no row mentions
		have := map[*ctor]bool{}
		for _, h := range heads {
			have[h] = true
		}
		for _, k := range heads[0].family {
			if !have[k] {
				head = &wit{c: k, subs: make([]*wit, k.arity)}
				for i := range head.subs {
					head.subs[i] = &wit{}
				}
				break
			}
		}
	}
	return append([]*wit{head}, r...)
}

// wit is a witness pattern for display.
type wit struct {
	c    *ctor
	subs []*wit
}

func (w *wit) String() string { return w.show(0) }

// prec: 0 top, 1 argument of constructor / left of ::
func (w *wit) show(prec int) string {
	if w.c == nil {
		return "_"
	}
	switch w.c.kind {
	case "tuple":
		parts := make([]string, len(w.subs))
		for i, s := range w.subs {
			parts[i] = s.show(0)
		}
		return "(" + strings.Join(parts, ", ") + ")"
	case "record":
		parts := make([]string, len(w.subs))
		for i, s := range w.subs {
			parts[i] = w.c.labels[i] + " = " + s.show(0)
		}
		return "{ " + strings.Join(parts, "; ") + " }"
	case "con":
		if w.c.name == "[]" {
			return "[]"
		}
		if w.c.name == "::" {
			t := w.subs[0] // tuple of (head, tail)
			if t.c == nil {
				return paren(prec > 0, "_ :: _")
			}
			return paren(prec > 0, t.subs[0].show(1)+" :: "+t.subs[1].show(0))
		}
		if len(w.subs) == 0 {
			return w.c.name
		}
		arg := w.subs[0]
		if arg.c == nil && w.c.payload > 1 {
			return paren(prec > 0, w.c.name+" ("+strings.TrimSuffix(strings.Repeat("_, ", w.c.payload), ", ")+")")
		}
		return paren(prec > 0, w.c.name+" "+arg.show(1))
	}
	return w.c.name
}

func paren(b bool, s string) string {
	if b {
		return "(" + s + ")"
	}
	return s
}

// ---------- public analysis entry points ----------

// MatchResult is the analysis of one match.
type MatchResult struct {
	Missing   string // witness text; empty when exhaustive
	Redundant []syntax.Span
	GaveUp    bool
}

type armIn struct {
	pat     syntax.Pat
	guarded bool
}

func topAlts(p syntax.Pat) []syntax.Pat {
	if o, ok := p.(*syntax.POr); ok {
		return append(topAlts(o.L), topAlts(o.R)...)
	}
	return []syntax.Pat{p}
}

// Analyze checks a list of arms (patterns plus whether each is guarded).
func (c *Checker) Analyze(arms []armIn) (res MatchResult) {
	c.budget, c.gaveUp = 0, false
	defer func() {
		if r := recover(); r != nil {
			if _, ok := r.(giveUp); ok {
				res = MatchResult{GaveUp: true}
				return
			}
			panic(r)
		}
	}()
	c.fields = collectFields(arms)
	var rows []row
	for _, a := range arms {
		for _, alt := range topAlts(a.pat) {
			ip := c.lower(alt)
			if !c.useful(rows, row{ip}) {
				res.Redundant = append(res.Redundant, alt.PSpan())
			}
			if !a.guarded {
				rows = append(rows, row{ip})
			}
		}
	}
	if w := c.witness(rows, 1); w != nil {
		res.Missing = w[0].String()
	}
	return res
}

// collectFields returns the sorted union of field names used by record patterns in the arms.
func collectFields(arms []armIn) []string {
	set := map[string]bool{}
	var walk func(p syntax.Pat)
	walk = func(p syntax.Pat) {
		switch x := p.(type) {
		case *syntax.PRecord:
			for _, f := range x.Fields {
				set[f.Name] = true
				walk(f.Pat)
			}
		case *syntax.PTuple:
			for _, e := range x.Elems {
				walk(e)
			}
		case *syntax.PCon:
			if x.Arg != nil {
				walk(x.Arg)
			}
		case *syntax.POr:
			walk(x.L)
			walk(x.R)
		case *syntax.PAs:
			walk(x.P)
		case *syntax.PAnnot:
			walk(x.P)
		}
	}
	for _, a := range arms {
		walk(a.pat)
	}
	out := make([]string, 0, len(set))
	for n := range set {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}
