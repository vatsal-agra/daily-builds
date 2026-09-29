package main

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// FactRef points at a stored tuple.
type FactRef struct {
	Pred string
	Idx  int
}

// Deriv records how a fact was first derived.
type Deriv struct {
	Rule *Rule
	Body []FactRef // per body literal; Pred=="" means a non-fact literal (see Notes)
	Note []string  // per body literal: rendered text for negation/comparison literals
	Agg  string
}

type Relation struct {
	Name   string
	Arity  int
	Tuples [][]Val
	Prov   []*Deriv
	set    map[string]int
	idx    map[uint64]map[string][]int
}

func newRelation(name string, arity int) *Relation {
	return &Relation{Name: name, Arity: arity, set: map[string]int{}, idx: map[uint64]map[string][]int{}}
}

func (r *Relation) has(t []Val) bool { _, ok := r.set[tupleKey(t)]; return ok }

func (r *Relation) add(t []Val, d *Deriv) bool {
	k := tupleKey(t)
	if _, ok := r.set[k]; ok {
		return false
	}
	i := len(r.Tuples)
	r.set[k] = i
	r.Tuples = append(r.Tuples, t)
	r.Prov = append(r.Prov, d)
	for mask, m := range r.idx {
		key := maskKey(t, mask)
		m[key] = append(m[key], i)
	}
	return true
}

func maskKey(t []Val, mask uint64) string {
	var b strings.Builder
	for c := 0; c < len(t); c++ {
		if mask&(1<<uint(c)) != 0 {
			writeKey(&b, t[c])
		}
	}
	return b.String()
}

func (r *Relation) lookup(mask uint64, key string) []int {
	m, ok := r.idx[mask]
	if !ok {
		m = map[string][]int{}
		for i, t := range r.Tuples {
			k := maskKey(t, mask)
			m[k] = append(m[k], i)
		}
		r.idx[mask] = m
	}
	return m[key]
}

// ---- compiled rules ----

type argC struct {
	Var  bool
	Slot int
	C    Val
}

type cexpr struct {
	Op   string
	L, R *cexpr
	Var  bool
	Slot int
	C    Val
}

type stepKind int

const (
	sAtom stepKind = iota
	sNeg
	sCmp
)

type step struct {
	Kind    stepKind
	Pred    string
	Args    []argC
	Mask    uint64 // columns known (const / already-bound var) when the step runs
	Op      string
	L, R    *cexpr
	Assign  int // slot assigned by "V = expr", or -1
	BodyIdx int
}

type aggSpec struct {
	Kind string
	Slot int // -1 for count(*)
}

type crule struct {
	Rule     *Rule
	Steps    []step
	NSlots   int
	Slots    map[string]int
	Head     []argC // for aggregates, agg columns hold Slot=-1 placeholder
	Aggs     []aggSpec
	AggCols  []int
	HeadPred string
}

// EvalError is raised (via panic) for runtime problems such as division by zero.
type EvalError struct{ Msg string }

func (e *EvalError) Error() string { return e.Msg }

type Stats struct {
	Iterations int
	Probes     int // candidate tuples examined by joins
	Derived    int
	Elapsed    time.Duration
}

type Engine struct {
	Prog    *Program
	Arity   map[string]int
	Strata  *Stratification
	Rels    map[string]*Relation
	Naive   bool
	Stats   Stats
	byLevel [][]*crule
}

// NewEngine validates and plans a program.
func NewEngine(p *Program) (*Engine, error) {
	arity, err := Check(p)
	if err != nil {
		return nil, err
	}
	st, err := Stratify(p, arity)
	if err != nil {
		return nil, err
	}
	e := &Engine{Prog: p, Arity: arity, Strata: st, Rels: map[string]*Relation{}}
	for pred, n := range arity {
		e.Rels[pred] = newRelation(pred, n)
	}
	e.byLevel = make([][]*crule, st.Count)
	for _, r := range p.Rules {
		if len(r.Body) == 0 {
			continue
		}
		cr, err := compileRule(r.Head, r.Body, r)
		if err != nil {
			return nil, err
		}
		l := st.Level[r.Head.Pred]
		e.byLevel[l] = append(e.byLevel[l], cr)
	}
	return e, nil
}

func litVars(l Literal) []string {
	var out []string
	switch l.Kind {
	case LCmp:
		l.L.vars(&out)
		l.R.vars(&out)
	default:
		for _, t := range l.Atom.Args {
			if t.Var {
				out = append(out, t.Name)
			}
		}
	}
	return out
}

func isAnon(n string) bool { return strings.HasPrefix(n, "_#") }

// compileRule orders the body greedily and checks range restriction.
func compileRule(head Atom, body []Literal, r *Rule) (*crule, error) {
	cr := &crule{Rule: r, Slots: map[string]int{}, HeadPred: head.Pred}
	bound := map[string]bool{}
	slot := func(n string) int {
		if s, ok := cr.Slots[n]; ok {
			return s
		}
		s := cr.NSlots
		cr.Slots[n] = s
		cr.NSlots++
		return s
	}
	used := make([]bool, len(body))
	remaining := len(body)
	unsafeErr := func(l Literal) error {
		var un []string
		seen := map[string]bool{}
		for _, v := range litVars(l) {
			if !bound[v] && !seen[v] {
				seen[v] = true
				un = append(un, v)
			}
		}
		sort.Strings(un)
		return fmt.Errorf("line %d: unsafe rule: variable(s) %s in `%s` are not bound by a positive body atom", r.Line, strings.Join(un, ", "), l)
	}
	for remaining > 0 {
		pick := -1
		var assign = -1
		// 1) filters that are ready
		for i, l := range body {
			if used[i] {
				continue
			}
			switch l.Kind {
			case LNeg:
				ok := true
				for _, t := range l.Atom.Args {
					if t.Var && !isAnon(t.Name) && !bound[t.Name] {
						ok = false
					}
				}
				if ok {
					pick = i
				}
			case LCmp:
				var lv, rv []string
				l.L.vars(&lv)
				l.R.vars(&rv)
				lu, ru := unbound(lv, bound), unbound(rv, bound)
				switch {
				case len(lu) == 0 && len(ru) == 0:
					pick = i
				case l.Op == "=" && len(lu) == 0 && l.R.Op == "" && l.R.T.Var && len(ru) == 1:
					pick, assign = i, -2 // assign right var
				case l.Op == "=" && len(ru) == 0 && l.L.Op == "" && l.L.T.Var && len(lu) == 1:
					pick, assign = i, -3 // assign left var
				}
			}
			if pick >= 0 {
				break
			}
		}
		// 2) otherwise the positive atom with most bound columns
		if pick < 0 {
			best := -1
			for i, l := range body {
				if used[i] || l.Kind != LPos {
					continue
				}
				score := 0
				for _, t := range l.Atom.Args {
					if !t.Var || bound[t.Name] {
						score += 2
					}
				}
				if score > best {
					best, pick = score, i
				}
			}
		}
		if pick < 0 {
			for i, l := range body {
				if !used[i] {
					return nil, unsafeErr(l)
				}
			}
		}
		l := body[pick]
		used[pick] = true
		remaining--
		st := step{BodyIdx: pick, Assign: -1}
		switch l.Kind {
		case LPos, LNeg:
			st.Kind = sAtom
			if l.Kind == LNeg {
				st.Kind = sNeg
			}
			st.Pred = l.Atom.Pred
			for c, t := range l.Atom.Args {
				if t.Var {
					s := slot(t.Name)
					if bound[t.Name] {
						st.Mask |= 1 << uint(c)
					}
					st.Args = append(st.Args, argC{Var: true, Slot: s})
				} else {
					st.Mask |= 1 << uint(c)
					st.Args = append(st.Args, argC{C: t.C})
				}
			}
			if l.Kind == LPos {
				for _, t := range l.Atom.Args {
					if t.Var {
						bound[t.Name] = true
					}
				}
			}
		case LCmp:
			st.Kind = sCmp
			st.Op = l.Op
			st.L, st.R = compileExpr(l.L, slot), compileExpr(l.R, slot)
			switch assign {
			case -2:
				st.Assign = slot(l.R.T.Name)
				bound[l.R.T.Name] = true
			case -3:
				st.Assign = slot(l.L.T.Name)
				bound[l.L.T.Name] = true
			}
		}
		cr.Steps = append(cr.Steps, st)
	}
	// head
	for _, t := range head.Args {
		switch {
		case t.Agg != "":
			spec := aggSpec{Kind: t.Agg, Slot: -1}
			if t.AggOf != "" {
				if !bound[t.AggOf] {
					return nil, fmt.Errorf("line %d: unsafe rule: aggregate variable %s is not bound in the body", r.Line, t.AggOf)
				}
				spec.Slot = slot(t.AggOf)
			}
			cr.AggCols = append(cr.AggCols, len(cr.Head))
			cr.Aggs = append(cr.Aggs, spec)
			cr.Head = append(cr.Head, argC{})
		case t.Var:
			if !bound[t.Name] {
				return nil, fmt.Errorf("line %d: unsafe rule: head variable %s does not appear in a positive body atom", r.Line, t.Name)
			}
			cr.Head = append(cr.Head, argC{Var: true, Slot: slot(t.Name)})
		default:
			cr.Head = append(cr.Head, argC{C: t.C})
		}
	}
	return cr, nil
}

func unbound(vs []string, bound map[string]bool) []string {
	var out []string
	for _, v := range vs {
		if !bound[v] {
			out = append(out, v)
		}
	}
	return out
}

func compileExpr(e *Expr, slot func(string) int) *cexpr {
	if e.Op == "" {
		if e.T.Var {
			return &cexpr{Var: true, Slot: slot(e.T.Name)}
		}
		return &cexpr{C: e.T.C}
	}
	return &cexpr{Op: e.Op, L: compileExpr(e.L, slot), R: compileExpr(e.R, slot)}
}

// ---- execution ----

type rng struct{ lo, hi int }

type runCtx struct {
	e       *Engine
	cr      *crule
	env     []Val
	bound   []bool
	ranges  []rng
	matched []int
	emit    func(c *runCtx)
	rels    []*Relation
}

func (c *runCtx) evalExpr(x *cexpr) Val {
	if x.Op == "" {
		if x.Var {
			return c.env[x.Slot]
		}
		return x.C
	}
	l, r := c.evalExpr(x.L), c.evalExpr(x.R)
	if l.IsStr || r.IsStr {
		panic(&EvalError{fmt.Sprintf("line %d: arithmetic on non-integer value in `%s`", c.cr.Rule.Line, c.cr.Rule)})
	}
	switch x.Op {
	case "+":
		return Int(l.I + r.I)
	case "-":
		return Int(l.I - r.I)
	case "*":
		return Int(l.I * r.I)
	case "/", "mod":
		if r.I == 0 {
			panic(&EvalError{fmt.Sprintf("line %d: division by zero in `%s`", c.cr.Rule.Line, c.cr.Rule)})
		}
		if x.Op == "/" {
			return Int(l.I / r.I)
		}
		m := l.I % r.I
		if m < 0 {
			if r.I < 0 {
				m -= r.I
			} else {
				m += r.I
			}
		}
		return Int(m)
	}
	panic("bad op")
}

func (c *runCtx) run(si int) {
	if si == len(c.cr.Steps) {
		c.emit(c)
		return
	}
	st := &c.cr.Steps[si]
	switch st.Kind {
	case sCmp:
		if st.Assign >= 0 {
			var v Val
			if st.R.Var && st.R.Slot == st.Assign {
				v = c.evalExpr(st.L)
			} else {
				v = c.evalExpr(st.R)
			}
			c.env[st.Assign], c.bound[st.Assign] = v, true
			c.run(si + 1)
			c.bound[st.Assign] = false
			return
		}
		l, r := c.evalExpr(st.L), c.evalExpr(st.R)
		cmp := l.Compare(r)
		ok := false
		switch st.Op {
		case "=":
			ok = cmp == 0
		case "!=":
			ok = cmp != 0
		case "<":
			ok = cmp < 0
		case "<=":
			ok = cmp <= 0
		case ">":
			ok = cmp > 0
		case ">=":
			ok = cmp >= 0
		}
		if ok {
			c.run(si + 1)
		}
	case sNeg:
		rel := c.rels[si]
		found := false
		if st.Mask == 0 {
			found = len(rel.Tuples) > 0
		} else {
			found = len(rel.lookup(st.Mask, c.maskKeyFor(st))) > 0
		}
		if !found {
			c.run(si + 1)
		}
	case sAtom:
		rel := c.rels[si]
		rg := c.ranges[si]
		if st.Mask == 0 {
			for i := rg.lo; i < rg.hi; i++ {
				c.tryTuple(si, st, rel, i)
			}
			return
		}
		list := rel.lookup(st.Mask, c.maskKeyFor(st))
		start := sort.SearchInts(list, rg.lo)
		for _, i := range list[start:] {
			if i >= rg.hi {
				break
			}
			c.tryTuple(si, st, rel, i)
		}
	}
}

func (c *runCtx) maskKeyFor(st *step) string {
	var b strings.Builder
	for col, a := range st.Args {
		if st.Mask&(1<<uint(col)) == 0 {
			continue
		}
		if a.Var {
			writeKey(&b, c.env[a.Slot])
		} else {
			writeKey(&b, a.C)
		}
	}
	return b.String()
}

func (c *runCtx) tryTuple(si int, st *step, rel *Relation, i int) {
	c.e.Stats.Probes++
	t := rel.Tuples[i]
	var newly [8]int
	nn := newly[:0]
	ok := true
	for col, a := range st.Args {
		if !a.Var {
			if a.C != t[col] {
				ok = false
				break
			}
			continue
		}
		if c.bound[a.Slot] {
			if c.env[a.Slot] != t[col] {
				ok = false
				break
			}
		} else {
			c.env[a.Slot], c.bound[a.Slot] = t[col], true
			nn = append(nn, a.Slot)
		}
	}
	if ok {
		c.matched[si] = i
		c.run(si + 1)
	}
	for _, s := range nn {
		c.bound[s] = false
	}
}

func (e *Engine) newCtx(cr *crule) *runCtx {
	c := &runCtx{e: e, cr: cr, env: make([]Val, cr.NSlots), bound: make([]bool, cr.NSlots),
		ranges: make([]rng, len(cr.Steps)), matched: make([]int, len(cr.Steps)), rels: make([]*Relation, len(cr.Steps))}
	for i, s := range cr.Steps {
		if s.Kind != sCmp {
			c.rels[i] = e.Rels[s.Pred]
		}
	}
	return c
}

func (c *runCtx) instantiate(args []argC) []Val {
	t := make([]Val, len(args))
	for i, a := range args {
		if a.Var {
			t[i] = c.env[a.Slot]
		} else {
			t[i] = a.C
		}
	}
	return t
}

func (c *runCtx) note(st *step) string {
	r := c.cr.Rule
	l := r.Body[st.BodyIdx]
	return strings.TrimSpace(c.render(l))
}

// render prints a literal with variables replaced by their current values.
func (c *runCtx) render(l Literal) string {
	sub := func(t Term) string {
		if t.Var && !isAnon(t.Name) {
			if s, ok := c.cr.Slots[t.Name]; ok && c.bound[s] {
				return c.env[s].String()
			}
		}
		return t.String()
	}
	var ex func(x *Expr) string
	ex = func(x *Expr) string {
		if x.Op == "" {
			return sub(x.T)
		}
		return "(" + ex(x.L) + " " + x.Op + " " + ex(x.R) + ")"
	}
	switch l.Kind {
	case LCmp:
		return fmt.Sprintf("%s %s %s", trimParens(ex(l.L)), l.Op, trimParens(ex(l.R)))
	}
	parts := make([]string, len(l.Atom.Args))
	for i, t := range l.Atom.Args {
		parts[i] = sub(t)
	}
	s := l.Atom.Pred
	if len(parts) > 0 {
		s += "(" + strings.Join(parts, ", ") + ")"
	}
	if l.Kind == LNeg {
		return "not " + s
	}
	return s
}

func trimParens(s string) string {
	if strings.HasPrefix(s, "(") && strings.HasSuffix(s, ")") {
		return s[1 : len(s)-1]
	}
	return s
}

func (c *runCtx) deriv() *Deriv {
	r := c.cr.Rule
	d := &Deriv{Rule: r, Body: make([]FactRef, len(r.Body)), Note: make([]string, len(r.Body))}
	for si := range c.cr.Steps {
		st := &c.cr.Steps[si]
		if st.Kind == sAtom {
			d.Body[st.BodyIdx] = FactRef{Pred: st.Pred, Idx: c.matched[si]}
		} else {
			d.Note[st.BodyIdx] = c.note(st)
		}
	}
	return d
}

// evalRule runs one rule with the given per-step ranges, adding new facts.
func (e *Engine) evalRule(cr *crule, ranges []rng) int {
	c := e.newCtx(cr)
	copy(c.ranges, ranges)
	head := e.Rels[cr.HeadPred]
	added := 0
	c.emit = func(c *runCtx) {
		t := c.instantiate(cr.Head)
		if head.has(t) {
			return
		}
		head.add(t, c.deriv())
		added++
	}
	c.run(0)
	e.Stats.Derived += added
	return added
}

func (e *Engine) fullRanges(cr *crule) []rng {
	rs := make([]rng, len(cr.Steps))
	for i, s := range cr.Steps {
		if s.Kind == sAtom {
			rs[i] = rng{0, len(e.Rels[s.Pred].Tuples)}
		}
	}
	return rs
}

// Run evaluates the whole program to its (perfect-model) fixpoint.
func (e *Engine) Run() (err error) {
	defer func() {
		if r := recover(); r != nil {
			if ee, ok := r.(*EvalError); ok {
				err = ee
				return
			}
			panic(r)
		}
	}()
	start := time.Now()
	for _, r := range e.Prog.Rules {
		if len(r.Body) == 0 {
			t := make([]Val, len(r.Head.Args))
			for i, a := range r.Head.Args {
				t[i] = a.C
			}
			e.Rels[r.Head.Pred].add(t, nil)
		}
	}
	for lvl := 0; lvl < e.Strata.Count; lvl++ {
		e.evalStratum(lvl)
	}
	e.Stats.Elapsed = time.Since(start)
	return nil
}

func (e *Engine) evalStratum(lvl int) {
	var plain, aggs []*crule
	for _, cr := range e.byLevel[lvl] {
		if cr.Rule.HasAgg() {
			aggs = append(aggs, cr)
		} else {
			plain = append(plain, cr)
		}
	}
	for _, cr := range aggs {
		e.evalAggregate(cr)
	}
	if len(plain) == 0 {
		return
	}
	inStratum := map[string]bool{}
	for p, l := range e.Strata.Level {
		if l == lvl {
			inStratum[p] = true
		}
	}
	if e.Naive {
		for {
			e.Stats.Iterations++
			added := 0
			for _, cr := range plain {
				added += e.evalRule(cr, e.fullRanges(cr))
			}
			if added == 0 {
				return
			}
		}
	}
	// iteration 0: everything against the full database
	before := map[string]int{}
	for p := range inStratum {
		before[p] = len(e.Rels[p].Tuples)
	}
	e.Stats.Iterations++
	for _, cr := range plain {
		e.evalRule(cr, e.fullRanges(cr))
	}
	dstart := before
	for {
		dend := map[string]int{}
		anyDelta := false
		for p := range inStratum {
			dend[p] = len(e.Rels[p].Tuples)
			if dend[p] > dstart[p] {
				anyDelta = true
			}
		}
		if !anyDelta {
			return
		}
		e.Stats.Iterations++
		for _, cr := range plain {
			for k, st := range cr.Steps {
				if st.Kind != sAtom || !inStratum[st.Pred] || dend[st.Pred] == dstart[st.Pred] {
					continue
				}
				rs := make([]rng, len(cr.Steps))
				for i, s := range cr.Steps {
					if s.Kind != sAtom {
						continue
					}
					n := len(e.Rels[s.Pred].Tuples)
					if !inStratum[s.Pred] {
						rs[i] = rng{0, n}
						continue
					}
					switch {
					case i < k:
						rs[i] = rng{0, dstart[s.Pred]}
					case i == k:
						rs[i] = rng{dstart[s.Pred], dend[s.Pred]}
					default:
						rs[i] = rng{0, dend[s.Pred]}
					}
				}
				e.evalRule(cr, rs)
			}
		}
		dstart = dend
	}
}

type aggGroup struct {
	key  []Val
	seen map[string]bool
	vals [][]Val // per agg: collected values
	n    int
}

func (e *Engine) evalAggregate(cr *crule) {
	c := e.newCtx(cr)
	copy(c.ranges, e.fullRanges(cr))
	groups := map[string]*aggGroup{}
	var order []string
	isAgg := map[int]bool{}
	for _, col := range cr.AggCols {
		isAgg[col] = true
	}
	c.emit = func(c *runCtx) {
		var key []Val
		for i, a := range cr.Head {
			if isAgg[i] {
				continue
			}
			if a.Var {
				key = append(key, c.env[a.Slot])
			} else {
				key = append(key, a.C)
			}
		}
		gk := tupleKey(key)
		g := groups[gk]
		if g == nil {
			g = &aggGroup{key: key, seen: map[string]bool{}, vals: make([][]Val, len(cr.Aggs))}
			groups[gk] = g
			order = append(order, gk)
		}
		// distinct body solutions (all bound slots) -- set semantics
		var b strings.Builder
		for s := 0; s < cr.NSlots; s++ {
			if c.bound[s] {
				writeKey(&b, c.env[s])
			}
		}
		sk := b.String()
		if g.seen[sk] {
			return
		}
		g.seen[sk] = true
		g.n++
		for i, ag := range cr.Aggs {
			if ag.Slot >= 0 {
				g.vals[i] = append(g.vals[i], c.env[ag.Slot])
			}
		}
	}
	c.run(0)
	head := e.Rels[cr.HeadPred]
	for _, gk := range order {
		g := groups[gk]
		t := make([]Val, len(cr.Head))
		ki, ai := 0, 0
		for i := range cr.Head {
			if isAgg[i] {
				t[i] = aggregate(cr, cr.Aggs[ai], g, ai)
				ai++
			} else {
				t[i] = g.key[ki]
				ki++
			}
		}
		if head.add(t, &Deriv{Rule: cr.Rule, Agg: fmt.Sprintf("aggregated over %d distinct body solution(s)", g.n)}) {
			e.Stats.Derived++
		}
	}
}

func aggregate(cr *crule, ag aggSpec, g *aggGroup, ai int) Val {
	if ag.Kind == "count" {
		if ag.Slot < 0 {
			return Int(int64(g.n))
		}
		return Int(int64(len(g.vals[ai])))
	}
	vs := g.vals[ai]
	switch ag.Kind {
	case "sum":
		var s int64
		for _, v := range vs {
			if v.IsStr {
				panic(&EvalError{fmt.Sprintf("line %d: sum over non-integer value %s", cr.Rule.Line, v)})
			}
			s += v.I
		}
		return Int(s)
	case "min", "max":
		best := vs[0]
		for _, v := range vs[1:] {
			c := v.Compare(best)
			if ag.Kind == "min" && c < 0 || ag.Kind == "max" && c > 0 {
				best = v
			}
		}
		return best
	}
	panic("bad aggregate")
}
